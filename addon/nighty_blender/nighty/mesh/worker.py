# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs nighty.mesh work in a background Blender (`blender -b`), so the person's Blender never freezes and a crash
in a remesher cannot take their work with it.

Main side (inside the person's Blender):
    run = Run(objects, steps)           # writes the objects to a temp .blend and starts the background Blender
    run.argv                            # what to start (the addon's job system starts it: ctx.start_job(argv=...))
    report, objs = run.collect()        # after it exits: the result report and the result objects (not linked)
    run.close()                         # removes the temp folder

Worker side: blender -b --factory-startup --python worker.py -- job.json
    prints "NBJOB <0..1> <message>" progress lines (the addon's job system reads them), writes out.blend + result.json.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import traceback

import bpy

PREFIX = "nighty-topo-"


def lib_dir():
    """The folder that holds the `nighty` package (addon/nighty_blender)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def available():
    return bool(bpy.app.binary_path) and os.path.isfile(bpy.app.binary_path)


def _sweep_old(base, hours=12):
    """Removes temp folders older than `hours` (left by cancelled jobs)."""
    try:
        for name in os.listdir(base):
            if name.startswith(PREFIX):
                p = os.path.join(base, name)
                if time.time() - os.path.getmtime(p) > hours * 3600:
                    shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass


_POINTER_PROPS = ("nighty_bake_source", "nighty_high")


class Run:
    def __init__(self, objects, steps, addons=None, factory=True, env_extra=None):
        self.env_extra = dict(env_extra or {})
        base = tempfile.gettempdir()
        _sweep_old(base)
        self.dir = tempfile.mkdtemp(prefix=PREFIX)
        self.inp = os.path.join(self.dir, "in.blend")
        self.out = os.path.join(self.dir, "out.blend")
        self.res = os.path.join(self.dir, "result.json")
        self.names = [o.name for o in objects]
        # ID pointers (the hidden dense original) would drag that object into the file: leave them out
        saved = []
        for o in objects:
            for k in _POINTER_PROPS:
                if k in o:
                    saved.append((o, k, o[k]))
                    del o[k]
        try:
            bpy.data.libraries.write(self.inp, set(objects), fake_user=True, compress=False)
        finally:
            for o, k, v in saved:
                o[k] = v
        job = {"in": self.inp, "out": self.out, "result": self.res, "objects": self.names, "steps": steps,
               "lib": lib_dir()}
        self.job_path = os.path.join(self.dir, "job.json")
        with open(self.job_path, "w", encoding="utf-8") as f:
            json.dump(job, f)
        argv = [bpy.app.binary_path, "-b"]
        if factory and not addons:
            argv.append("--factory-startup")
        if addons:
            argv += ["--addons", ",".join(addons)]
        argv += ["--python-exit-code", "3", "--python", os.path.abspath(__file__), "--", self.job_path]
        self.argv = argv

    def env(self):
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env.pop("NIGHTY_QF_HERE", None)
        env.update(self.env_extra)
        return env

    def collect(self):
        """(report dict, {name: Object}) from the finished worker. Raises RuntimeError with the worker's message
        when it failed."""
        if not os.path.isfile(self.res):
            raise RuntimeError("the background Blender stopped without a result (it may have crashed)")
        with open(self.res, encoding="utf-8") as f:
            result = json.load(f)
        if result.get("error"):
            raise RuntimeError(result["error"])
        names = result.get("written", [])
        objs = {}
        if names:
            with bpy.data.libraries.load(self.out, link=False) as (src, dst):
                want = [n for n in names if n in src.objects]
                dst.objects = list(want)
            for name, ob in zip(want, dst.objects):
                if ob is not None:
                    # the temp file saved them with a fake user; here they must vanish when nothing uses them
                    ob.use_fake_user = False
                    if ob.data is not None:
                        ob.data.use_fake_user = False
                    objs[name] = ob
        return result, objs

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def start(self):
        """Starts the background Blender without waiting. Progress lands in self.progress / self.message (read by a
        small thread); poll with self.proc.poll(). Returns the process."""
        import subprocess
        import threading
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        self.progress, self.message, self.tail = 0.0, "starting", []
        self.proc = subprocess.Popen(self.argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self.env(),
                                     creationflags=flags, universal_newlines=True, encoding="utf-8",
                                     errors="replace")

        def read():
            for line in self.proc.stdout:
                line = line.rstrip(chr(10))
                self.tail = (self.tail + [line])[-80:]
                if line.startswith("NBJOB "):
                    parts = line[6:].split(" ", 1)
                    try:
                        self.progress = float(parts[0])
                    except ValueError:
                        continue
                    self.message = parts[1] if len(parts) > 1 else ""
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        return self.proc

    def stop(self):
        p = getattr(self, "proc", None)
        if p is not None and p.poll() is None:
            p.kill()
            p.wait()

    def tail_text(self):
        r = getattr(self, "reader", None)
        if r is not None:
            r.join(timeout=5)
        return chr(10).join(self.tail)

    def run_blocking(self, timeout=1800):
        """Runs the worker and waits (scripts, tests, QuadriFlow isolation). Kills it after `timeout` seconds.
        Returns the exit code (non-zero: crashed or killed)."""
        proc = self.start()
        t0 = time.monotonic()
        while proc.poll() is None:
            if time.monotonic() - t0 > timeout:
                self.stop()
                break
            time.sleep(0.05)
        code = proc.wait()
        self.tail_text()
        return code if code is not None else -1


# ---------------------------------------------------------------- worker side

def _progress(frac, message=""):
    print(f"NBJOB {max(0.0, min(1.0, frac)):.3f} {message}", flush=True)


def _strip_materials(objs):
    """Material slots are emptied before writing results back, so no duplicate materials come back; the main side
    puts the person's own materials into the same slots."""
    for o in objs:
        if o.type == 'MESH':
            for i in range(len(o.data.materials)):
                o.data.materials[i] = None


def _do(step, objs, prog):
    from nighty import mesh as nm  # noqa: imported inside the worker's Blender
    op, args = step["op"], dict(step.get("args") or {})
    reps, written, new = [], [], []
    n = max(len(objs), 1)
    if op == "uv_unwrap":
        reps.append(nm.uv_unwrap(objs, progress=prog, **args))
        written = list(objs)
    else:
        for i, o in enumerate(objs):
            sub = _sub(prog, i / n, (i + 1) / n)
            if op == "cleanup":
                reps.append(nm.cleanup(o, progress=sub, **args))
                written.append(o)
            elif op == "retopo":
                reps.append(nm.retopo(o, keep_source=False, progress=sub, **args))
                written.append(o)
            elif op == "decimate":
                reps.append(nm.decimate(o, progress=sub, **args))
                written.append(o)
            elif op == "split_parts":
                name = o.name
                parts, rep = nm.split_parts(o, progress=sub, **args)
                rep["object"] = name
                reps.append(rep)
                new += parts
            elif op == "quadriflow":
                from nighty.mesh import topo
                n_faces = topo._quadriflow_here(o, args["faces"], args.get("keep_sharp", True), args.get("symmetry"),
                                                args.get("seed", 0))
                reps.append({"faces": n_faces})
                written.append(o)
            elif op == "make_lods":
                lods, rep = nm.make_lods(o, progress=sub, hide=False, **args)
                rep["object"] = o.name
                reps.append(rep)
                new += lods
            else:
                raise ValueError(f"unknown step {op!r}")
    return reps, written, new


def _sub(prog, a, b):
    return lambda f, m="": prog(a + (b - a) * f, m)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    with open(argv[0], encoding="utf-8") as f:
        job = json.load(f)
    result = {"error": None, "reports": [], "written": [], "new": [], "seconds": 0.0}
    t0 = time.monotonic()
    try:
        if job["lib"] not in sys.path:
            sys.path.insert(0, job["lib"])
        _progress(0.01, "loading")
        with bpy.data.libraries.load(job["in"], link=False) as (src, dst):
            dst.objects = list(job["objects"])
        objs = [o for o in dst.objects if o is not None]
        for o in objs:
            if o.name not in bpy.context.scene.objects:
                bpy.context.scene.collection.objects.link(o)
        # keep the names the main side knows (a fresh file has no clashes, but be safe)
        steps = job["steps"]
        out_objs = []
        new_objs = []
        for k, step in enumerate(steps):
            a, b = k / len(steps), (k + 1) / len(steps)
            prog = _sub(lambda f, m="": _progress(0.02 + 0.93 * f, m), a, b)
            reps, written, new = _do(step, objs, prog)
            result["reports"] += reps
            out_objs = written
            new_objs += new
            if new:
                objs = new
        alive = []
        for o in out_objs + new_objs:
            try:
                o.name
                alive.append(o)
            except ReferenceError:
                pass
        _progress(0.96, "saving")
        _strip_materials(alive)
        for o in alive:
            for k in _POINTER_PROPS:
                if k in o:
                    del o[k]
        result["written"] = [o.name for o in alive]
        result["new"] = [o.name for o in new_objs if o in alive]
        if alive:
            bpy.data.libraries.write(job["out"], set(alive), fake_user=True, compress=False)
    except Exception as e:  # noqa: BLE001 - hand the message to the main side
        result["error"] = f"{type(e).__name__}: {e}"
        result["trace"] = traceback.format_exc()[-3000:]
        print(result["trace"], flush=True)
    result["seconds"] = round(time.monotonic() - t0, 2)
    with open(job["result"], "w", encoding="utf-8") as f:
        json.dump(result, f, default=str)
    _progress(1.0, "done")


if __name__ == "__main__":
    main()
