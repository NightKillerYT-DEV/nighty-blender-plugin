# SPDX-License-Identifier: GPL-3.0-or-later
# Slow work (bakes, renders, generation) must never freeze Blender, so it runs as a "job": either a generator stepped
# in small time slices on the main thread, or a `blender -b` subprocess whose progress lines we read. A slow tool
# calls ctx.start_job(step_fn, label) and returns {"job": id} at once; the AI then waits with wait_job or stops it
# with cancel_job. Job state changes are sent to the program as `job` messages (PROTOCOL.md section 2).
#
# A generator step function is written like:
#     def bake(job):
#         for i in range(steps):
#             if job.cancelled: return   # checked between slices
#             ... do one slice of bpy work ...
#             yield (i + 1) / steps, "baked %d/%d" % (i + 1, steps)
#         return [text("done")]          # the final MCP content (or a dict)
# Each `yield` hands control back so Blender stays responsive; the returned value becomes the job result.

import subprocess
import threading
import time

RUNNING, DONE, FAILED, CANCELLED = "running", "done", "failed", "cancelled"


class Defer(Exception):
    """Raised by the wait_job tool to park a call until a job finishes (the dispatcher holds the answer, never the
    main thread). Carries the job id and how long to wait."""

    def __init__(self, job_id, max_seconds):
        super().__init__(job_id)
        self.job_id = job_id
        self.max_seconds = max_seconds


class Job:
    __slots__ = ("id", "tool", "client", "label", "state", "progress", "message", "result", "error",
                 "cancelled", "_gen", "_proc", "_reader", "_lines", "_finish", "_started", "_last_emit")

    def __init__(self, job_id, tool, client, label):
        self.id = job_id
        self.tool = tool
        self.client = client
        self.label = label or tool
        self.state = RUNNING
        self.progress = 0.0
        self.message = ""
        self.result = None       # MCP content list or dict, when done
        self.error = None
        self.cancelled = False
        self._gen = None
        self._proc = None
        self._reader = None
        self._lines = None
        self._finish = None      # for subprocess jobs: finish(job) -> result, called when the process ends
        self._started = time.monotonic()
        self._last_emit = 0.0

    def snapshot(self):
        row = {"id": self.id, "tool": self.tool, "state": self.state,
               "progress": round(float(self.progress), 4), "message": self.message[:400]}
        if self.state == DONE and self.result is not None:
            row["result"] = self.result
        if self.state == FAILED and self.error:
            row["message"] = self.error[:2000]
        return row


class JobManager:
    """Owns the running jobs. pump() is called from the main-thread timer; it advances generators and reads
    subprocess output within a small time budget. send(obj) delivers `job` messages to the program."""

    def __init__(self, send, log=None):
        self.send = send
        self.log = log or (lambda *_: None)
        self.jobs = {}
        self._seq = 0
        self.children = {}   # parent job id -> ids of jobs it started (a tool chain: make_asset -> retopo ...)

    def _new_id(self):
        self._seq += 1
        return "j%d" % self._seq

    def get(self, job_id):
        return self.jobs.get(job_id)

    def adopt(self, parent_id, child_id):
        """`child_id` was started by `parent_id`'s job: cancelling the parent cancels it too."""
        self.children.setdefault(parent_id, []).append(child_id)

    # ---------- starting ----------

    def start_gen(self, step_fn, label, tool, client):
        """Run a generator step function in time slices on the main thread. Returns the job id."""
        job = Job(self._new_id(), tool, client, label)
        try:
            job._gen = step_fn(job)
        except Exception as exc:  # noqa: BLE001
            job.state = FAILED
            job.error = _trace(exc)
            self.jobs[job.id] = job
            self._emit(job, force=True)
            return job.id
        self.jobs[job.id] = job
        self._emit(job, force=True)
        return job.id

    def start_proc(self, argv, label, tool, client, finish, cwd=None, env=None):
        """Run `argv` (e.g. a background Blender) as a subprocess. Progress comes from lines it prints as
        `NBJOB <0..1> <message>`; finish(job, returncode, tail) -> the result (content list or dict). Returns id."""
        job = Job(self._new_id(), tool, client, label)
        job._finish = finish
        job._lines = []
        try:
            job._proc = subprocess.Popen(
                argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=1, universal_newlines=True)
        except OSError as exc:
            job.state = FAILED
            job.error = "could not start: %s" % exc
            self.jobs[job.id] = job
            self._emit(job, force=True)
            return job.id
        job._reader = threading.Thread(target=self._pipe_reader, args=(job,), daemon=True)
        job._reader.start()
        self.jobs[job.id] = job
        self._emit(job, force=True)
        return job.id

    def _pipe_reader(self, job):
        try:
            for line in job._proc.stdout:
                job._lines.append(line.rstrip("\n"))
                if len(job._lines) > 5000:
                    del job._lines[:1000]
        except (OSError, ValueError):
            pass

    # ---------- the main-thread pump ----------

    def pump(self, budget=0.01):
        """Advance jobs for at most `budget` seconds. Call every tick."""
        if not self.jobs:
            return
        deadline = time.monotonic() + budget
        for job in list(self.jobs.values()):
            if job.state != RUNNING:
                continue
            if job._gen is not None:
                self._step_gen(job, deadline)
            elif job._proc is not None:
                self._poll_proc(job)
            if time.monotonic() >= deadline:
                break
        # forget jobs that finished a while ago, so the dict stays small
        self._reap()

    def _step_gen(self, job, deadline):
        while time.monotonic() < deadline:
            if job.cancelled:
                self._mark(job, CANCELLED)
                return
            try:
                step = next(job._gen)
            except StopIteration as stop:
                job.result = _as_result(stop.value)
                self._mark(job, DONE)
                return
            except Exception as exc:  # noqa: BLE001
                job.error = _trace(exc)
                self._mark(job, FAILED)
                return
            if isinstance(step, (int, float)):
                job.progress = max(0.0, min(1.0, float(step)))
            elif isinstance(step, (tuple, list)) and step:
                job.progress = max(0.0, min(1.0, float(step[0])))
                if len(step) > 1 and step[1] is not None:
                    job.message = str(step[1])
            self._emit(job)
            # one yield per slice is enough; let other jobs and the UI breathe
            return

    def _poll_proc(self, job):
        if job.cancelled:
            try:
                job._proc.terminate()
            except OSError:
                pass
            self._mark(job, CANCELLED)
            return
        # read any new progress lines
        for line in job._lines[_pos(job):]:
            if line.startswith("NBJOB "):
                parts = line[6:].split(" ", 1)
                try:
                    job.progress = max(0.0, min(1.0, float(parts[0])))
                except ValueError:
                    continue
                if len(parts) > 1:
                    job.message = parts[1][:400]
                self._emit(job)
        _set_pos(job, len(job._lines))
        code = job._proc.poll()
        if code is None:
            return
        tail = "\n".join(job._lines[-200:])
        try:
            job.result = _as_result(job._finish(job, code, tail))
            self._mark(job, DONE if code == 0 else FAILED)
            if code != 0 and not job.error:
                job.error = "subprocess exit %d\n%s" % (code, tail[-1500:])
        except Exception as exc:  # noqa: BLE001
            job.error = _trace(exc)
            self._mark(job, FAILED)

    # ---------- cancel ----------

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            return False
        for child in self.children.get(job_id, ()):
            self.cancel(child)
        if job.state != RUNNING:
            return False
        job.cancelled = True
        if job._proc is not None:
            try:
                job._proc.terminate()
            except OSError:
                pass
        return True

    def cancel_all(self):
        for job_id in list(self.jobs):
            self.cancel(job_id)

    # ---------- bookkeeping ----------

    def _mark(self, job, state):
        job.state = state
        if state == CANCELLED:
            for child in self.children.get(job.id, ()):
                self.cancel(child)
        if state == DONE and job.progress < 1.0:
            job.progress = 1.0
        self._emit(job, force=True)

    def _emit(self, job, force=False):
        now = time.monotonic()
        if not force and now - job._last_emit < 0.2:
            return
        job._last_emit = now
        try:
            self.send({"type": "job", "id": job.id, "job": job.snapshot()})
        except Exception as exc:  # noqa: BLE001
            self.log("job emit:", exc)

    def _reap(self):
        done = [j for j in self.jobs.values() if j.state != RUNNING]
        if len(done) <= 50:
            return
        done.sort(key=lambda j: j._last_emit)
        for job in done[:-50]:
            self.jobs.pop(job.id, None)
            self.children.pop(job.id, None)
            _PROC_POS.pop(job.id, None)


# positions for the subprocess line reader are kept off the slots to keep Job small
_PROC_POS = {}


def _pos(job):
    return _PROC_POS.get(job.id, 0)


def _set_pos(job, value):
    _PROC_POS[job.id] = value


def _as_result(value):
    # None is allowed (a bare "done"); dicts and content lists pass straight through.
    return value


def _trace(exc):
    import traceback
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
