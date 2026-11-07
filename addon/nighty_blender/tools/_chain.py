# SPDX-License-Identifier: GPL-3.0-or-later
# Running one tool from inside another tool's job (generate_3d -> cleanup_mesh, make_asset -> every step): call the
# tool like the dispatcher would, and when it hands back a job, wait for that job on the same job runner (the addon's
# JobManager steps both), mirroring its progress into a share of the caller's bar. A tool that changes the scene at
# once (not a job) gets its "AI: <tool>" undo step here, as the dispatcher would have pushed it.
# (Leading underscore: the tool loader skips this module.)

import json
import re

from . import ACTIONS, ToolError

_EXC = re.compile(r"^[\w.]*(Error|Exception|Failed|Cancelled)[\w.]*: (.*)$")


class StepFailed(Exception):
    def __init__(self, tool, message):
        super().__init__(f"{tool}: {message}")
        self.tool, self.message = tool, message


def push_undo(label):
    try:
        from ..dispatch import push_ai_undo
        push_ai_undo(label)
        return
    except Exception:  # noqa: BLE001 - no addon core (plain tests)
        pass
    try:
        import bpy
        bpy.ops.ed.undo_push(message="AI: " + label)
    except Exception:  # noqa: BLE001
        pass


def as_data(result):
    """A tool result as plain data: a dict stays, MCP content blocks become the JSON of their first text block
    (plus 'images': how many pictures came with it)."""
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        data, pics = None, 0
        for b in result:
            if isinstance(b, dict) and b.get("type") == "text" and data is None:
                try:
                    data = json.loads(b["text"])
                except (ValueError, TypeError):
                    data = {"text": b.get("text")}
            elif isinstance(b, dict) and b.get("type") == "image":
                pics += 1
        data = data if isinstance(data, dict) else {"value": data}
        if pics:
            data["images"] = pics
        return data
    return {"value": result}


def run_tool(ctx, name, args, start=0.0, end=1.0, label=None, parent=None):
    """Generator: runs tool `name` and waits for it. Yields (progress, message) inside start..end; returns the
    tool's result as data. Raises StepFailed when the tool refuses or its job fails / is cancelled.
    parent: the calling job (the addon's job object): cancelling it cancels this step's job too."""
    t = ACTIONS.get(name)
    if t is None:
        raise StepFailed(name, "this step isn't installed")
    label = label or name.replace("_", " ")
    yield start, label
    try:
        res = t.fn(ctx, dict(args))
    except ToolError as err:
        raise StepFailed(name, str(err)) from None
    if isinstance(res, dict) and set(res) == {"job"} and hasattr(ctx, "jobs"):
        jid = res["job"]
        if parent is not None and hasattr(ctx.jobs, "adopt"):
            ctx.jobs.adopt(parent.id, jid)
        while True:
            j = ctx.jobs.get(jid)
            if j is None:
                raise StepFailed(name, "its job vanished")
            if j.state != "running":
                break
            p = float(j.progress or 0.0)
            msg = j.message or ""
            yield start + (end - start) * p, f"{label}: {msg}" if msg else label
        if j.state == "cancelled":
            raise StepFailed(name, "cancelled")
        if j.state != "done":
            lines = (j.error or j.state or "failed").strip().splitlines()
            last = lines[-1] if lines else "failed"
            m = _EXC.match(last)
            raise StepFailed(name, (m.group(2) if m else last)[:400])
        return as_data(j.result)
    if t.changes:
        push_undo(name)
    yield end, label
    return as_data(res)
