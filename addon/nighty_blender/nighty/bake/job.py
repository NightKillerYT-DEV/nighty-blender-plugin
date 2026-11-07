# SPDX-License-Identifier: GPL-3.0-or-later
"""Slow texture work in a separate `blender -b` process, so the person's Blender never freezes.

    job = WorkerJob("bake", spec, datablocks)   # main thread: writes the asset to a temp .blend (fast)
    job.start()
    job.poll() -> ("running", 0.4, "Baking normal") | ("done", 1.0, "") | ("failed", p, why)
    job.result()                                 # the worker's JSON answer

The worker runs at a lower priority with its own copy of the data; the person can keep working. Steps for the
tools are generators (see `steps`): each `next()` is one short main-thread slice, yielding (progress, message), and
the generator's return value is the tool's result.
(A small helper for the jobs framework of the addon; b-addon's own subprocess helper can replace WorkerJob.)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.dirname(os.path.dirname(HERE))      # .../nighty_blender
WORKER = os.path.join(HERE, "worker.py")


class WorkerJob:
    def __init__(self, task, spec, datablocks, keep=False):
        self.task = task
        self.spec = dict(spec)
        self.datablocks = set(d for d in datablocks if d is not None)
        self.keep = keep
        self.dir = None
        self.proc = None
        self.log_file = None
        self.started = None
        self.cancelled = False

    def start(self):
        self.dir = tempfile.mkdtemp(prefix=f"nighty_{self.task}_")
        blend = os.path.join(self.dir, "asset.blend")
        bpy.data.libraries.write(blend, self.datablocks, path_remap="ABSOLUTE", compress=False)
        self.spec.update(task=self.task, blend=blend, addon_dir=ADDON_DIR, job_dir=self.dir,
                         objects_written=sorted(d.name for d in self.datablocks if isinstance(d, bpy.types.Object)))
        spec_path = os.path.join(self.dir, "spec.json")
        with open(spec_path, "w", encoding="utf-8") as f:
            json.dump(self.spec, f)
        exe = bpy.app.binary_path
        args = [exe, "-b", "--factory-startup", "--python-exit-code", "1", "--python", WORKER, "--", spec_path]
        self.log_file = open(os.path.join(self.dir, "log.txt"), "w", encoding="utf-8", errors="replace")
        kw = {}
        if sys.platform == "win32":
            kw["creationflags"] = 0x08000000 | 0x00004000   # no console window, below-normal priority
        else:
            kw["preexec_fn"] = lambda: os.nice(5)
        self.proc = subprocess.Popen(args, stdout=self.log_file, stderr=subprocess.STDOUT, cwd=self.dir, **kw)
        self.started = time.time()
        return self

    def _read(self, name, tries=1):
        p = os.path.join(self.dir, name)
        for i in range(tries):
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                if i + 1 < tries:
                    time.sleep(0.02)
        return None

    def poll(self):
        if self.proc is None:
            return "failed", 0.0, "not started"
        prog = self._read("progress.json") or {}
        code = self.proc.poll()
        if code is None:
            return "running", float(prog.get("p", 0.0)), prog.get("m", "Working")
        if self.cancelled:
            return "cancelled", float(prog.get("p", 0.0)), "Cancelled"
        res = self._read("result.json", tries=4)
        if code == 0 and res is not None and not res.get("error"):
            return "done", 1.0, ""
        why = (res or {}).get("error") or f"the worker stopped (code {code})"
        return "failed", float(prog.get("p", 0.0)), why + self.log_tail()

    def log_tail(self, n=12):
        try:
            self.log_file.flush()
            with open(os.path.join(self.dir, "log.txt"), encoding="utf-8", errors="replace") as f:
                lines = [ln.rstrip() for ln in f if ln.strip()]
            return "\nlog: " + " | ".join(lines[-n:])
        except OSError:
            return ""

    def result(self):
        return self._read("result.json", tries=4)

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def wait(self, timeout=None, tick=0.25):
        """Blocks until the worker ends (tests and background scripts only)."""
        t0 = time.time()
        while True:
            state, p, m = self.poll()
            if state != "running":
                return state, p, m
            if timeout and time.time() - t0 > timeout:
                self.cancel()
                return "failed", p, "timed out"
            time.sleep(tick)

    def cleanup(self):
        if self.log_file:
            try:
                self.log_file.close()
            except OSError:
                pass
        if self.dir and not self.keep:
            shutil.rmtree(self.dir, ignore_errors=True)


def steps(job, finish):
    """A job as main-thread steps: start, poll while it runs, then finish(result) on the main thread."""
    yield 0.01, "Starting"
    job.start()
    try:
        while True:
            state, p, msg = job.poll()
            if state == "running":
                yield min(0.97, 0.02 + 0.95 * p), msg
                continue
            if state != "done":
                raise RuntimeError(msg if state == "failed" else "cancelled")
            break
        yield 0.98, "Finishing"
        return finish(job.result())
    finally:
        if job.proc and job.proc.poll() is None:
            job.cancel()
        job.cleanup()


def run_steps(gen, tick=0.2, timeout=None):
    """Drives a steps generator to the end (no jobs framework: tests, background scripts)."""
    t0 = time.time()
    try:
        while True:
            next(gen)
            if timeout and time.time() - t0 > timeout:
                gen.close()
                raise RuntimeError("timed out")
            time.sleep(tick)
    except StopIteration as stop:
        return stop.value
