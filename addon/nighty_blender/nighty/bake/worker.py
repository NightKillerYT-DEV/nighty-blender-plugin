# SPDX-License-Identifier: GPL-3.0-or-later
"""The `blender -b` side of a texture job. Started by job.py as:
    blender -b --factory-startup --python-exit-code 1 --python worker.py -- <job>/spec.json
It loads the asset copy, runs the task (bake / export / verify), writes progress.json while it works and
result.json at the end. It imports only the texture packages (not the addon, not the nighty library's __init__).
"""

import json
import os
import sys
import time
import traceback
import types


def _write(path, data, tries=40):
    """Atomic write. On Windows the main Blender may be reading the file at that moment (a sharing violation):
    try again for a moment; a progress line that still can't be written is skipped (the next one comes soon)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    for i in range(tries):
        try:
            os.replace(tmp, path)
            return True
        except PermissionError:
            time.sleep(0.02 + 0.01 * i)
    return False


def _import_packages(addon_dir):
    pkg = types.ModuleType("nighty_blender")
    pkg.__path__ = [addon_dir]
    sys.modules.setdefault("nighty_blender", pkg)
    sub = types.ModuleType("nighty_blender.nighty")
    sub.__path__ = [os.path.join(addon_dir, "nighty")]
    sys.modules.setdefault("nighty_blender.nighty", sub)


def load_asset(blend):
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    with bpy.data.libraries.load(blend, link=False) as (src, dst):
        dst.objects = list(src.objects)
        dst.materials = list(src.materials)
    sc = bpy.context.scene
    for o in dst.objects:
        if o is not None and o.name not in sc.collection.objects:
            sc.collection.objects.link(o)
    for o in dst.objects:   # a throw-away scene: hidden helpers (a topology bake source) must be selectable here
        if o is not None:
            o.hide_select = False
            o.hide_viewport = False
            try:
                o.hide_set(False)
            except RuntimeError:
                pass
    bpy.context.view_layer.update()   # bounding boxes and evaluated meshes are valid from here on
    return dst.objects


def main():
    spec_path = sys.argv[sys.argv.index("--") + 1]
    job_dir = os.path.dirname(spec_path)
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    prog_path = os.path.join(job_dir, "progress.json")
    res_path = os.path.join(job_dir, "result.json")

    def progress(p, msg):
        _write(prog_path, {"p": round(float(p), 3), "m": msg, "t": time.time()}, tries=5)

    try:
        _import_packages(spec["addon_dir"])
        progress(0.0, "Loading")
        load_asset(spec["blend"])
        task = spec["task"]
        if task == "bake":
            from nighty_blender.nighty.bake import core
            res = {"manifest": core.bake_asset(spec, progress)}
        elif task == "export":
            from nighty_blender.nighty.export import core as ecore
            res = ecore.run(spec, progress)
        elif task == "verify":
            from nighty_blender.nighty.bake import verify
            res = verify.run(spec, progress)
        elif task == "look":                       # b-lib: studio renders for the look tool
            from nighty_blender.nighty import view
            res = view.worker_look(spec, progress)
        else:
            raise ValueError(f"unknown task {task!r}")
        _write(res_path, res)
    except Exception as e:  # the main side shows this to the AI
        _write(res_path, {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-3000:]})
        print(traceback.format_exc(), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
