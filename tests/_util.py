# SPDX-License-Identifier: GPL-3.0-or-later
# Small helpers for the Blender-side tests (not a test file itself).

import importlib
import json
import sys

import nighty_blender.nighty as n  # noqa: F401  (tests import n from here)

sys.modules.setdefault("nighty", n)


class Ctx:
    """What a tool sees from the addon's dispatcher (enough for the tests): start_job runs the job's generator to
    the end at once and keeps its result in last_job_result."""

    def __init__(self, level="full"):
        self.undo_label = None
        self.level = level
        self.jobs = []
        self.last_job_result = None

    def start_job(self, step_fn, label="", **kw):
        class Job:
            cancelled = False
        self.jobs.append(label)
        gen = step_fn(Job())
        try:
            while True:
                next(gen)
        except StopIteration as stop:
            self.last_job_result = stop.value
        return {"job": "job-%d" % len(self.jobs)}

    def wait_job(self, job_id, max_seconds=40):
        """The dispatcher parks the call and answers with the finished job's result: here it already ran."""
        return self.last_job_result


def registry():
    import nighty_blender
    nighty_blender.load_tools()
    return importlib.import_module("nighty_blender.tools")


def call(name, args=None, level="full"):
    """Runs a tool like the addon does; returns its MCP content blocks (a job's result when it made a job)."""
    tools = registry()
    ctx = Ctx(level)
    step = tools.ACTIONS.get(name) or tools.TOOLS[name]   # a working step, else a public tool
    result = step.fn(ctx, args or {})
    if isinstance(result, dict) and set(result) == {"job"}:
        result = ctx.last_job_result
    return tools.content(result)


def call_json(name, args=None):
    blocks = call(name, args)
    return json.loads(blocks[0]["text"])


def raises(fn, *args, contains=None, **kwargs):
    """Asserts that fn raises; returns the error."""
    try:
        fn(*args, **kwargs)
    except Exception as error:  # noqa: BLE001
        if contains and contains not in str(error):
            raise AssertionError(f"error {error!r} does not mention {contains!r}")
        return error
    raise AssertionError(f"{getattr(fn, '__name__', fn)} did not raise")
