# SPDX-License-Identifier: GPL-3.0-or-later
# Runs every examples/<name>/script.py in a fresh scene, checks it (verify.json) and renders it (render.png in
# material mode, wire.png in matcap with the wireframe). Each script states its game triangle budget in its
# docstring ("budget: 12000"); over budget fails like a verify error. Inside Blender:
#   blender -b --factory-startup --python scripts/build_examples.py [-- name ...] [-- --no-render]

import json
import os
import sys
import time
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "addon"))
EXAMPLES = os.path.join(ROOT, "examples")
RENDER_SIZE = 1024   # the studio render (material mode: lights, ground shadow, AgX), on the GPU when there is one
WIRE_SIZE = 768      # matcap with the wireframe on top

import nighty_blender.nighty as n  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import example_thumbs  # noqa: E402  (render.jpg, the 512 px picture the extension ships)

sys.modules["nighty"] = n


def run_example(name):
    """Fresh scene, run the script; returns the model objects."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    n.core._S.update({"detail": "medium", "size": 1.0, "collection": None})
    path = os.path.join(EXAMPLES, name, "script.py")
    with open(path, encoding="utf-8") as f:
        code = f.read()
    exec(compile(code, path, "exec"), {"__name__": "__main__"})
    return n.objects()


def _doc_lines(name):
    with open(os.path.join(EXAMPLES, name, "script.py"), encoding="utf-8") as f:
        head = f.read(3000)
    return head.split('"""')[1].splitlines() if head.startswith('"""') else []


def options(name):
    """verify options from the script's docstring line 'verify: allow_open'."""
    opts = {}
    for line in _doc_lines(name):
        if line.strip().lower().startswith("verify:"):
            for word in line.split(":", 1)[1].replace(",", " ").split():
                opts[word.strip()] = True
    return {"allow_open": bool(opts.get("allow_open"))}


def budget(name):
    """The game triangle budget from the docstring line 'budget: 12000 (why)', or None."""
    for line in _doc_lines(name):
        if line.strip().lower().startswith("budget:"):
            word = line.split(":", 1)[1].split()[0].replace(",", "").replace("_", "")
            return int(word)
    return None


def compact(rep):
    rows = {}
    for name, r in rep["objects"].items():
        rows[name] = {k: r[k] for k in ("faces", "triangles_total", "quads", "tris", "ngons", "shells") if k in r}
        sym = r.get("symmetry")
        if sym:
            rows[name]["symmetry"] = sym["score"]
    return rows


def build(name, render=True):
    t = time.time()
    objs = run_example(name)
    seconds = time.time() - t
    rep = n.verify(objs, **options(name))
    limit = budget(name)
    if limit is not None and rep["triangles"] > limit:
        rep["errors"].append(f"{rep['triangles']} triangles: over the budget of {limit}")
        rep["pass"] = False
    b = n.bounds(objs)
    out = {"name": name, "pass": rep["pass"], "errors": rep["errors"], "warnings": rep["warnings"],
           "triangles": rep["triangles"], "budget": limit, "build_seconds": round(seconds, 1),
           "objects": compact(rep), "size_m": [round(float(c), 3) for c in b.size],
           "blender": bpy.app.version_string.split()[0]}
    d = os.path.join(EXAMPLES, name)
    with open(os.path.join(d, "verify.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, indent=1) + "\n")
    if render:
        az, _ = n.view.hero_angles(b.size)
        wide = az in (27.0, 63.0)  # long things: a wide picture
        pngs, _ = n.view.look(objs, views=["hero"], mode="material", size=RENDER_SIZE,
                              height=640 if wide else None, labels=False, gpu="cuda")
        with open(os.path.join(d, "render.png"), "wb") as f:
            f.write(pngs[0])
        example_thumbs.thumb(os.path.join(d, "render.png"), os.path.join(d, "render.jpg"))
        pngs, _ = n.view.look(objs, views=["hero"], mode="matcap", wire=True, size=WIRE_SIZE if not wide else 1024,
                              height=None if not wide else 640, labels=False)
        with open(os.path.join(d, "wire.png"), "wb") as f:
            f.write(pngs[0])
    print(f"{'ok  ' if rep['pass'] else 'FAIL'} {name}: {rep['triangles']} tris, {len(objs)} parts, "
          f"{time.time() - t:.1f}s {'; '.join(rep['errors'][:2])}")
    return rep["pass"]


def main(args):
    render = "--no-render" not in args
    names = [a for a in args if not a.startswith("--")]
    all_names = sorted(x for x in os.listdir(EXAMPLES) if os.path.isfile(os.path.join(EXAMPLES, x, "script.py")))
    todo = [x for x in all_names if not names or x in names]
    failed = 0
    for name in todo:
        try:
            if not build(name, render):
                failed += 1
        except Exception:
            failed += 1
            print(f"FAIL {name}:\n{traceback.format_exc()}")
    print(f"{len(todo) - failed} of {len(todo)} examples pass")
    return 1 if failed else 0


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    code = main(a)
    sys.stdout.flush()
    sys.exit(code)
