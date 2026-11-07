# SPDX-License-Identifier: GPL-3.0-or-later
# The main thread's side of the tool calls. The listener (server.py) only parses frames; session.py checks the
# pairing and hands every call from the paired Nighty Vault plugin to on_call(), on Blender's main thread (ONE
# persistent bpy.app.timers callback). This runs the call through the registry with the level gate, wraps a scene
# change in ONE undo step named "AI: <tool>", turns a ToolError into an error the AI can read and a crash into a
# traceback the AI can fix, and sends the answer back. Slow tools become jobs (jobs.py); job { action: wait } parks
# the answer here (never blocking the main thread) until the job finishes.

import time

try:
    import bpy
except Exception:  # noqa: BLE001 - importable outside Blender for a few pure unit tests
    bpy = None

from . import jobs as jobs_mod
from .tools import LEVELS, TOOLS, ToolError, content, text


class Ctx:
    """What a tool is handed. Read-only facts about the session, plus the job helpers and an undo-label hook."""

    def __init__(self, dispatcher, client, client_id):
        self._d = dispatcher
        self.client = client
        self.client_id = client_id
        self.level = dispatcher.session.level
        self.addon_version = dispatcher.session.addon_version
        self.blender_version = dispatcher.session.blender_version
        self.python_version = dispatcher.session.python_version
        self.jobs = dispatcher.jobs
        self.undo_label = None                     # a tool may set this to refine the "AI: ..." step name

    def start_job(self, step_fn, label, *, argv=None, finish=None, cwd=None, env=None):
        """Start a slow job and return {"job": id} to hand straight back to the AI. Either a generator step_fn
        (stepped on the main thread) or, with argv + finish, a `blender -b` subprocess."""
        if argv is not None:
            job_id = self.jobs.start_proc(argv, label, self.undo_label or label, self.client, finish, cwd=cwd, env=env)
        else:
            job_id = self.jobs.start_gen(step_fn, label, self.undo_label or label, self.client)
        return {"job": job_id}

    def wait_job(self, job_id, max_seconds=40):
        """Park this call until the job finishes (or max_seconds pass). Raises inside the dispatcher, never blocks."""
        raise jobs_mod.Defer(job_id, max_seconds)

    def cancel_job(self, job_id):
        return self.jobs.cancel(job_id)

    def job_snapshot(self, job_id):
        job = self.jobs.get(job_id)
        return job.snapshot() if job else None


class Dispatcher:
    def __init__(self, session):
        self.session = session
        self.jobs = jobs_mod.JobManager(self._send, log=session.log)
        self._waiting = []     # parked wait_job calls: {call_id, client_id, job_id, deadline}

    # ---------- the timer tick (main thread) ----------

    def tick(self):
        # 1) advance jobs (job steps are the AI's code too: the panel's settings are locked meanwhile)
        if self.jobs.jobs:
            self.session.ai_running = True
            try:
                self.jobs.pump(budget=0.01)
            finally:
                self.session.ai_running = False
        # 2) deliver any parked job-wait answers whose job is done or whose time is up
        self._pump_waits()

    # ---------- a call from the paired plugin ----------

    def on_call(self, message):
        call_id = message.get("id")
        name = message.get("tool")
        if call_id is None or not isinstance(name, str):
            return
        args = message.get("args")
        args = args if isinstance(args, dict) else {}
        client = str(message.get("client") or "AI")[:60]
        client_id = message.get("sessionId") if isinstance(message.get("sessionId"), str) else None
        self._run_call(call_id, name, args, client, client_id)

    def _run_call(self, call_id, name, args, client, client_id):
        tool = TOOLS.get(name)
        if tool is None:
            return self._send_result(call_id, [text("There is no tool called %r." % name)], True)
        if LEVELS.index(tool.level) > LEVELS.index(self.session.level):
            return self._send_result(call_id, [text(
                "That tool needs the %r safety level. The person has set %r in the Nighty panel in Blender."
                % (tool.level, self.session.level))], True)
        ctx = Ctx(self, client, client_id)
        self.session.ai_running = True   # the AI's code runs: the panel's settings (level, idle) are locked
        try:
            result = tool.fn(ctx, args)
        except jobs_mod.Defer as defer:
            self._waiting.append({"call_id": call_id, "job_id": defer.job_id,
                                  "deadline": time.monotonic() + max(1, defer.max_seconds)})
            return None
        except ToolError as err:
            return self._send_result(call_id, [text(str(err))], True)
        except Exception as exc:  # noqa: BLE001 - hand the AI the traceback so it can fix its code
            return self._send_result(call_id, [text(_trace(exc))], True)
        finally:
            self.session.ai_running = False
        # a changing tool that actually changed the scene now (not a job) is ONE undo step
        if tool.changes and not _is_job(result):
            push_ai_undo(ctx.undo_label or name)
        return self._send_result(call_id, content(result), False)

    # ---------- parked wait_job calls ----------

    def _pump_waits(self):
        if not self._waiting:
            return
        now = time.monotonic()
        still = []
        for wait in self._waiting:
            job = self.jobs.get(wait["job_id"])
            if job is None:
                self._send_result(wait["call_id"], [text(
                    "There is no job %r (it may have finished and been cleared)." % wait["job_id"])], True)
                continue
            if job.state != jobs_mod.RUNNING:
                if job.state == jobs_mod.DONE:
                    self._send_result(wait["call_id"], content(job.result), False)
                else:  # failed or cancelled: the snapshot carries the message / error
                    self._send_result(wait["call_id"], [text(job.snapshot())], True)
                continue
            if now >= wait["deadline"]:
                self._send_result(wait["call_id"], [text(job.snapshot())], False)  # still running: AI can wait again
                continue
            still.append(wait)
        self._waiting = still

    # ---------- sending ----------

    def _send(self, obj):
        return self.session.send(obj)

    def _send_result(self, call_id, blocks, is_error):
        self._send({"type": "result", "id": call_id, "content": blocks, "isError": bool(is_error)})


# ---------- undo helpers (reading the stack by name, so we never undo the person's work) ----------

def push_ai_undo(label):
    """One undo step named 'AI: <label>' for the change just made."""
    if bpy is None:
        return
    try:
        bpy.ops.ed.undo_push(message="AI: " + str(label)[:80])
    except Exception:  # noqa: BLE001
        pass


def active_undo_name():
    """The name of the step that `undo` would take back next (the active one), or None if it can't be read."""
    if bpy is None:
        return None
    try:
        wm = bpy.context.window_manager
    except Exception:  # noqa: BLE001
        return None
    text_out = _capture(lambda: wm.print_undo_steps())
    if not text_out:
        return None
    active = None
    for line in text_out.splitlines()[1:]:
        head, _, rest = line.partition("]")
        if not rest:
            continue
        is_active = "*" in head
        if "name='" in line:
            nm = line.split("name='", 1)[1].rsplit("'", 1)[0]
            if is_active:
                active = nm
    return active


def _capture(fn):
    # print_undo_steps writes to the C stdout; capture it by swapping fd 1 for a temp file.
    import ctypes
    import os
    import tempfile
    libc = None
    for name in ("ucrtbase", "msvcrt", "c", "libc.so.6"):
        try:
            libc = ctypes.CDLL(name)
            break
        except OSError:
            continue
    try:
        if libc:
            libc.fflush(None)
        fd, path = tempfile.mkstemp()
        saved = os.dup(1)
        os.dup2(fd, 1)
        try:
            fn()
            if libc:
                libc.fflush(None)
        finally:
            os.dup2(saved, 1)
            os.close(saved)
            os.close(fd)
        with open(path, encoding="utf-8", errors="replace") as handle:
            out = handle.read()
        os.remove(path)
        return out
    except Exception:  # noqa: BLE001
        return None


def _is_job(result):
    return isinstance(result, dict) and set(result.keys()) == {"job"}


def _trace(exc):
    import traceback
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def _warm_up_soon():
    """Right after pairing: one tiny render (in a second, on Blender's timer), so the first render of the session
    (1-2 s of engine and shader setup) happens now, not in the middle of the AI's first look."""
    def run():
        try:
            from .nighty import view
            view.warm_up()
        except Exception:  # noqa: BLE001
            pass
        return None
    try:
        if not bpy.app.background:
            bpy.app.timers.register(run, first_interval=1.0)
    except Exception:  # noqa: BLE001 - bpy missing (pure unit tests)
        pass
