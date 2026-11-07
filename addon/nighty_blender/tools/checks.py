# SPDX-License-Identifier: GPL-3.0-or-later
# More checks for the public `check` tool (verify_mesh, verify_textures and finish_asset live in verify.py /
# texture.py):
#   compare_source  the finished model against its locked _SOURCE copy (import): size, triangles, and how far the
#                   surfaces drift apart (sampled both ways, in % of the model's size)
#   roundtrip       export, then read the file back in a background Blender and compare (triangles, size, UVs,
#                   materials): what the engine will get
#   roblox_ready    the last gate before Roblox: the mesh check, at most 20,000 triangles per MeshPart, UVs,
#                   texture sizes, applied scale, a Roblox export

import json
import os
import random
import subprocess
import sys
import tempfile
import time

import bpy

from . import ToolError, action
from .scene import NAMES, targets

ROBLOX_TRIS = 20000          # one MeshPart's limit
ROBLOX_TEXTURE = 1024        # Roblox shows at most 1024 px per map
ROBLOX_MAX_STUDS = 2048      # a MeshPart's biggest size per axis
STUD_M = 0.28


def _mesh_world(obj, depsgraph):
    """(world-space vertex list, triangle index list) of the evaluated mesh."""
    ev = obj.evaluated_get(depsgraph)
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        mw = obj.matrix_world
        verts = [(mw @ v.co)[:] for v in me.vertices]
        tris = [tuple(t.vertices) for t in me.loop_triangles]
    finally:
        ev.to_mesh_clear()
    return verts, tris


def _samples(verts, tris, n, rng):
    """n points spread over the surface by area."""
    from mathutils import Vector
    areas, acc = [], 0.0
    for a, b, c in tris:
        va, vb, vc = Vector(verts[a]), Vector(verts[b]), Vector(verts[c])
        acc += (vb - va).cross(vc - va).length / 2
        areas.append(acc)
    if not tris or acc <= 0:
        return []
    import bisect
    pts = []
    for _ in range(n):
        k = min(bisect.bisect_left(areas, rng.random() * acc), len(tris) - 1)
        a, b, c = (Vector(verts[i]) for i in tris[k])
        r1, r2 = rng.random(), rng.random()
        if r1 + r2 > 1:
            r1, r2 = 1 - r1, 1 - r2
        pts.append(a + (b - a) * r1 + (c - a) * r2)
    return pts


def _merge(groups):
    verts, tris = [], []
    for v, t in groups:
        off = len(verts)
        verts += v
        tris += [(a + off, b + off, c + off) for a, b, c in t]
    return verts, tris


def _drift(a, b, size, n=3000, seed=0):
    """Distances from a's surface to b's and back, in % of size: (mean, max) each way."""
    from mathutils.bvhtree import BVHTree
    rng = random.Random(seed)
    out = {}
    for label, (src, dst) in (("model_to_source", (a, b)), ("source_to_model", (b, a))):
        if not dst[1] or not src[1]:
            out[label] = None
            continue
        tree = BVHTree.FromPolygons(dst[0], dst[1])
        d = []
        for p in _samples(src[0], src[1], n, rng):
            hit = tree.find_nearest(p)
            if hit[0] is not None:
                d.append(hit[3])
        if not d:
            out[label] = None
            continue
        d.sort()
        out[label] = {"mean_pct": round(100 * sum(d) / len(d) / size, 3),
                      "p95_pct": round(100 * d[int(0.95 * (len(d) - 1))] / size, 3),
                      "max_pct": round(100 * d[-1] / size, 3)}
    return out


@action("compare_source",
        "The finished model against its locked _SOURCE copy: size, triangles and how far the surfaces drift apart.",
        {"type": "object", "properties": {"names": NAMES,
                                          "tolerance_pct": {"type": "number",
                                                            "description": "Most drift allowed (95% of points), in % "
                                                                           "of the size (default 1)."}}},
        changes=False)
def compare_source(ctx, args):
    from .importing import is_source
    objs = [o for o in targets(args) if o.type == "MESH" and not is_source(o)]
    groups = {}
    for o in objs:
        name = o.get("nighty_source")
        if name and bpy.data.objects.get(name) is not None:
            groups.setdefault(name, []).append(o)
    if not groups:
        raise ToolError("None of these objects has a _SOURCE copy (import a file, or make_game_ready keeps one).")
    tol = float(args.get("tolerance_pct") or 1.0)
    dg = bpy.context.evaluated_depsgraph_get()
    rows, ok = [], True
    for src_name, parts in groups.items():
        src = bpy.data.objects[src_name]
        model = _merge([_mesh_world(o, dg) for o in parts])
        # the source stays where the file came in; the model may have moved or got a new origin: line them up by
        # their bounding boxes' bottom centers (moves only; a rotated or rescaled model shows up as drift)
        sv, st = _mesh_world(src, dg)
        if not sv or not model[0]:
            raise ToolError(f"{src_name} or its model has no faces.")
        lo = [min(v[i] for v in sv) for i in range(3)]
        hi = [max(v[i] for v in sv) for i in range(3)]
        mlo = [min(v[i] for v in model[0]) for i in range(3)]
        mhi = [max(v[i] for v in model[0]) for i in range(3)]
        shift = [(mlo[0] + mhi[0] - lo[0] - hi[0]) / 2, (mlo[1] + mhi[1] - lo[1] - hi[1]) / 2, mlo[2] - lo[2]]
        sv = [(x + shift[0], y + shift[1], z + shift[2]) for x, y, z in sv]
        size = max(h - l for h, l in zip(hi, lo)) or 1.0
        drift = _drift(model, (sv, st), size)
        worst = max((d["p95_pct"] for d in drift.values() if d), default=0.0)
        good = worst <= tol
        ok = ok and good
        rows.append({"source": src_name, "model": [o.name for o in parts],
                     "triangles": {"source": len(st), "model": len(model[1])},
                     "size_m": {"source": [round(h - l, 4) for h, l in zip(hi, lo)],
                                "model": [round(h - l, 4) for h, l in zip(mhi, mlo)]},
                     "drift": drift, "pass": good})
    return {"pass": ok, "tolerance_pct": tol, "objects": rows,
            "next": "fine" if ok else "the model drifted from the source: more faces (retopo / decimate), or look "
                                     "at where (look with references)"}


def _no_window():
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def _export_temp(objs, fmt, folder):
    path = os.path.join(folder, "roundtrip." + ("glb" if fmt == "glb" else "fbx"))
    layer = bpy.context.view_layer
    before = [o for o in bpy.context.selected_objects]
    active = layer.objects.active
    try:
        for o in before:
            o.select_set(False)
        for o in objs:
            o.select_set(True)
        layer.objects.active = objs[0]
        if fmt == "glb":
            bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True)
        else:
            bpy.ops.export_scene.fbx(filepath=path, use_selection=True)
    finally:
        for o in objs:
            o.select_set(False)
        for o in before:
            try:
                o.select_set(True)
            except ReferenceError:
                pass
        layer.objects.active = active
    return path


@action("roundtrip",
        "Exports (or takes an exported file), reads it back in a background Blender and compares it with the "
        "objects: triangles, size, UVs, materials, textures. Slow: a job.",
        {"type": "object", "properties": {
            "names": NAMES,
            "file": {"type": "string", "description": "An exported file to read back (default: a temporary GLB)."},
            "format": {"type": "string", "enum": ["glb", "fbx"]}}},
        slow=True, changes=False)
def roundtrip(ctx, args):
    objs = [o for o in targets(args) if o.type == "MESH"]
    if not objs:
        raise ToolError("No mesh objects to check.")
    given = args.get("file")
    if given and not os.path.isfile(given):
        raise ToolError(f"There is no file at {given}.")
    fmt = args.get("format") or "glb"
    if fmt not in ("glb", "fbx"):
        raise ToolError("format: glb or fbx")
    dg = bpy.context.evaluated_depsgraph_get()
    have_tris = sum(len(_mesh_world(o, dg)[1]) for o in objs)
    have_size = [round(v, 3) for v in _bounds(objs)]
    have_uv = all(len(o.data.uv_layers) for o in objs)

    def step_fn(job):
        tmp = tempfile.mkdtemp(prefix="nighty-roundtrip-")
        path = given or _export_temp(objs, fmt, tmp)
        yield 0.2, "reading it back"
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nighty", "io",
                              "import_file.py")
        argv = [bpy.app.binary_path, "-b", "--factory-startup", "--python", script, "--", path,
                os.path.join(tmp, "back.blend"), json.dumps({"name": "roundtrip"})]
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                                encoding="utf-8", errors="replace", **_no_window())
        p = 0.2
        while proc.poll() is None:
            p = min(0.9, p + 0.003)
            time.sleep(0.01)
            yield p, "reading it back"
        out_text = proc.stdout.read() if proc.stdout else ""
        info = None
        for line in out_text.splitlines():
            if line.startswith("NIGHTY_RESULT "):
                info = json.loads(line[len("NIGHTY_RESULT "):])
        if info is None:
            raise ToolError("The exported file could not be read back:\n" + "\n".join(out_text.splitlines()[-10:]))
        problems = []
        if info["triangles"] != have_tris:
            problems.append(f"triangles: {have_tris:,} in Blender, {info['triangles']:,} in the file")
        back = info.get("original_dimensions") or info.get("dimensions") or [0, 0, 0]
        if any(abs(a - b) > max(0.002, 0.01 * max(have_size)) for a, b in zip(sorted(back), sorted(have_size))):
            problems.append(f"size: {have_size} m in Blender, {[round(v, 3) for v in back]} in the file (units or "
                            "axes)")
        if have_uv and not info.get("uv_layers"):
            problems.append("the UVs did not come through")
        notes = [] if info.get("materials") else ["no material in the file (fine for a mesh without one)"]
        return {"pass": not problems, "file": path, "problems": problems, "notes": notes,
                "file_facts": {k: info.get(k) for k in ("format", "triangles", "original_dimensions", "uv_layers",
                                                        "materials", "images", "loose_parts")},
                "blender": {"triangles": have_tris, "size_m": have_size, "uvs": have_uv}}
    return ctx.start_job(step_fn, "roundtrip")


def _bounds(objs):
    from mathutils import Vector
    lo = Vector((1e30, 1e30, 1e30))
    hi = -lo
    for o in objs:
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return list(hi - lo)


@action("roblox_ready",
        "The last gate before Roblox: the mesh check passes, at most 20,000 triangles per part, UVs, textures at "
        "most 1024 px, applied scale, size limits.",
        {"type": "object", "properties": {"names": NAMES}},
        changes=False)
def roblox_ready(ctx, args):
    from .verify import verify_mesh
    objs = [o for o in targets(args) if o.type == "MESH"]
    if not objs:
        raise ToolError("No mesh objects to check.")
    rep = verify_mesh(ctx, {"names": [o.name for o in objs], "allow_open": True})
    errors, warnings = list(rep.get("errors") or []), []
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        tris = len(_mesh_world(o, dg)[1])
        if tris > ROBLOX_TRIS:
            errors.append(f"{o.name}: {tris:,} triangles (a MeshPart takes 20,000 at most): mesh decimate / retopo")
        if not len(o.data.uv_layers):
            errors.append(f"{o.name}: no UVs")
        if any(abs(s - 1) > 1e-4 for s in o.scale):
            warnings.append(f"{o.name}: scale not applied ({[round(s, 3) for s in o.scale]})")
        studs = max(o.dimensions) / STUD_M
        if studs > ROBLOX_MAX_STUDS:
            errors.append(f"{o.name}: {studs:,.0f} studs long (2,048 at most)")
        for slot in o.material_slots:
            m = slot.material
            if m is None or not m.use_nodes:
                continue
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image is not None and max(n.image.size) > ROBLOX_TEXTURE:
                    warnings.append(f"{o.name}: {n.image.name} is {max(n.image.size)} px (Roblox shows 1024): the "
                                    "Roblox export scales it down")
    exported = any(o.get("nighty_export_roblox") is not None for o in objs)
    if not exported:
        warnings.append("no Roblox export yet: export { made_for: roblox }")
    return {"pass": not errors, "errors": errors, "warnings": warnings,
            "triangles": sum(len(_mesh_world(o, dg)[1]) for o in objs),
            "next": "check { what: final } to finish" if not errors else "fix the errors, then check again"}
