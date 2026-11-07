# SPDX-License-Identifier: GPL-3.0-or-later
"""xatlas (MIT): UV charts and packing that give fewer, bigger islands than Smart UV Project on generated and
low-poly triangle meshes. It ships as wheels inside the extension (Blender installs the one for this system) and
runs in Blender's own python.exe as a separate process (xa_worker.py): inside Blender 4.2 the module crashes (Blender
loads an older C++ runtime than the wheel was built with), and a separate process also keeps any crash away from
the person's Blender. It is never imported here."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np


def module_dir():
    """The folder holding the xatlas module, or None. NIGHTY_XATLAS_DIR overrides it (tests, development)."""
    env = os.environ.get("NIGHTY_XATLAS_DIR")
    if env and os.path.isdir(env):
        return env
    try:
        spec = importlib.util.find_spec("xatlas")  # finds the file without running it
    except (ImportError, ValueError):
        spec = None
    if spec is not None and spec.origin and os.path.isfile(spec.origin):
        return os.path.dirname(spec.origin)
    return None


def python_exe():
    """Blender's own Python program (it has numpy)."""
    exe = sys.executable
    return exe if exe and os.path.isfile(exe) and "python" in os.path.basename(exe).lower() else None


def available():
    return module_dir() is not None and python_exe() is not None


def run(meshes, resolution=2048, padding=12, chart=None, pack=None, timeout=900):
    """meshes: [(vertices (n, 3) world space, triangles (t, 3))] or [(vertices, triangles, uvs (n, 2))] to keep those
    UV islands and only pack them (chart option use_input_mesh_uvs). All go into ONE atlas (same texel density).
    Returns ([(vmapping, indices, uvs 0..1, chart count) per mesh], info)."""
    mod = module_dir()
    exe = python_exe()
    if mod is None or exe is None:
        raise RuntimeError("xatlas is not available here")
    d = tempfile.mkdtemp(prefix="nighty-xa-")
    try:
        inp, out, opt = os.path.join(d, "in.npz"), os.path.join(d, "out.npz"), os.path.join(d, "opts.json")
        arrays = {}
        for i, m in enumerate(meshes):
            arrays[f"v{i}"] = np.ascontiguousarray(m[0], dtype=np.float32)
            arrays[f"f{i}"] = np.ascontiguousarray(m[1], dtype=np.uint32)
            if len(m) > 2:
                arrays[f"u{i}"] = np.ascontiguousarray(m[2], dtype=np.float32)
                chart = dict(chart or {}, use_input_mesh_uvs=True)
        np.savez(inp, **arrays)
        pk = {"resolution": int(resolution), "padding": int(padding), "bilinear": True, "rotate_charts": True}
        pk.update(pack or {})
        with open(opt, "w", encoding="utf-8") as fh:
            json.dump({"count": len(meshes), "chart": chart or {}, "pack": pk}, fh)
        worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xa_worker.py")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        r = subprocess.run([exe, "-I", worker, inp, out, opt, mod], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout, creationflags=flags)
        if r.returncode != 0 or not os.path.isfile(out):
            msg = r.stdout.decode("utf-8", "replace").strip()[-500:]
            raise RuntimeError(f"xatlas failed (code {r.returncode}): {msg}")
        with np.load(out) as npz:  # read everything now: the temp folder goes away below
            res = {k: npz[k] for k in npz.files}
        with open(out + ".json", encoding="utf-8") as fh:
            info = json.load(fh)
        parts = []
        for i in range(len(meshes)):
            uv = res[f"uv{i}"].astype(np.float64)
            if uv.size and uv.max() > 1.5:  # texel units -> 0..1
                uv = uv / np.array([max(info["width"], 1), max(info["height"], 1)], dtype=np.float64)
            parts.append((res[f"vm{i}"].astype(np.int64), res[f"ix{i}"].astype(np.int64), uv,
                          int(res[f"charts{i}"][0])))
        return parts, info
    finally:
        shutil.rmtree(d, ignore_errors=True)
