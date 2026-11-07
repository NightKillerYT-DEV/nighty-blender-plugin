# SPDX-License-Identifier: GPL-3.0-or-later
# Topology tools: cleanup_mesh, retopo, decimate, split_parts, uv_unwrap, make_lods. They are slow on dense meshes,
# so each one returns a job id at once and does the work in a background Blender (nighty/mesh/worker.py); the result
# is put into the scene on the main thread as ONE undo step "AI: <tool>". The same functions are in nighty.mesh for
# run_python (blocking).

import time

import bpy

from . import ToolError, action
from ..nighty.mesh import _util as U
from ..nighty.mesh import external as X
from ..nighty.mesh import topo as T
from ..nighty.mesh import worker as W

_OBJECTS = {"type": "array", "items": {"type": "string"},
            "description": "Mesh object names. Default: the selected meshes, else the active object."}


def _targets(args):
    names = args.get("objects")
    if names:
        objs = []
        for n in names:
            o = bpy.data.objects.get(n)
            if o is None:
                raise ToolError(f"No object named {n!r}.")
            objs.append(o)
    else:
        objs = [o for o in bpy.context.selected_objects if o.type == 'MESH']
        if not objs and bpy.context.view_layer.objects.active is not None:
            objs = [bpy.context.view_layer.objects.active]
    if not objs:
        raise ToolError("No mesh to work on: pass objects, or select one.")
    for o in objs:
        if o.type != 'MESH':
            raise ToolError(f"{o.name!r} is not a mesh.")
        if o.data.shape_keys is not None:
            raise ToolError(f"{o.name!r} has shape keys; remove them first.")
        if o.mode != 'OBJECT':
            U.object_mode(o)
    return objs


def _undo(label):
    try:
        from ..dispatch import push_ai_undo
    except ImportError:
        push_ai_undo = None
    if push_ai_undo is not None:
        push_ai_undo(label)
        return
    try:
        bpy.ops.ed.undo_push(message="AI: " + label)
    except Exception:  # noqa: BLE001 - no undo stack (background tests)
        pass


def _alive(obj):
    try:
        obj.name
        return True
    except ReferenceError:
        return False


def _launch(ctx, label, objs, steps, apply, addons=None, send=None):
    """Writes `send` (default objs) to a temp file and returns a job that runs `steps` in a background Blender; when
    it ends, apply(result, loaded_objects) runs on the main thread (its return value is the job's result) and ONE
    undo step "AI: <label>" is pushed (ctx.undo_label renames it). The job is a generator, so any job runner that
    steps generators can run it; without one (scripts) it runs to the end here."""
    if not W.available():
        raise ToolError("Blender's own program path is unknown, so the background worker cannot start.")
    run = W.Run(send or objs, steps, addons=addons)

    def finish(code, tail):
        loaded = {}
        try:
            if code != 0:
                raise RuntimeError(f"the background Blender stopped (code {code}): {tail[-600:]}")
            result, loaded = run.collect()
            for o in objs:
                if not _alive(o):
                    raise RuntimeError("an object was deleted while the job ran; nothing was changed")
            rep = apply(result, loaded)
            _undo(getattr(ctx, "undo_label", None) or label)
            return rep
        finally:
            for ob in loaded.values():  # loaded shells nobody kept
                if _alive(ob) and ob.users == 0:
                    bpy.data.objects.remove(ob)
            run.close()

    def step_fn(job):
        proc = run.start()
        try:
            while proc.poll() is None:
                if getattr(job, "cancelled", False):
                    return None
                yield 0.02 + 0.93 * run.progress, run.message
            yield 0.97, "putting the result in the scene"
            return finish(proc.wait(), run.tail_text())
        finally:
            run.stop()  # cancelled or failed: never leave the background Blender running
            run.close()

    start = getattr(ctx, "start_job", None)
    if start is not None:
        return start(step_fn, label)
    gen = step_fn(None)
    while True:  # no job system (scripts): run it to the end here
        try:
            next(gen)
        except StopIteration as stop:
            return stop.value
        time.sleep(0.05)


def _take_mesh(obj, loaded, keep_transform=False):
    """Puts the background result's mesh into the person's object (their materials kept)."""
    if keep_transform:
        obj.matrix_basis = loaded.matrix_basis.copy()
    U.replace_mesh(obj, loaded.data)


def _clean_reports(reps):
    for r in reps:
        r.pop("seconds", None)
    return reps


# ---------------------------------------------------------------- cleanup_mesh

@action("cleanup_mesh",
      "Clean an imported mesh: weld, remove floaters, fill holes, make it manifold (voxel rebuild only if needed), "
      "fix normals, apply transforms, set real size, put it on the ground with the origin at the bottom center. "
      "Slow: returns a job id (job { action: wait }).",
      {"type": "object", "properties": {
          "objects": _OBJECTS,
          "size": {"type": "number", "description": "Real size in meters along size_axis (e.g. 0.9 for a rifle)."},
          "size_axis": {"type": "string", "enum": ["longest", "height", "x", "y", "z"], "default": "longest"},
          "floaters": {"type": "number", "default": 0.03,
                       "description": "Remove loose pieces smaller than this share of the whole size (0 = keep)."},
          "keep_largest": {"type": "boolean", "default": False, "description": "Keep only the biggest piece."},
          "holes": {"type": "boolean", "default": True},
          "manifold": {"type": "string", "enum": ["auto", "voxel", "fix", "off"], "default": "auto",
                       "description": "auto: targeted fixes, voxel rebuild only if still broken."},
          "voxel_size": {"type": "number", "description": "Meters (default: picked from the size and detail)."},
          "join": {"type": "boolean", "default": True,
                   "description": "Join parts left floating a few mm apart (common in generated models) into one solid."},
          "flatten": {"type": "string", "enum": ["auto", "on", "off"], "default": "auto",
                      "description": "Make flat sides truly flat with crisp edges (auto: hard-surface shapes only)."},
          "ground": {"type": "boolean", "default": True},
          "origin": {"type": "string", "enum": ["bottom", "center", "keep"], "default": "bottom"}}},
      slow=True)
def cleanup_mesh(ctx, args):
    objs = _targets(args)
    a = {"floaters": float(args.get("floaters", 0.03)), "keep_largest": bool(args.get("keep_largest", False)),
         "holes": bool(args.get("holes", True)), "manifold": args.get("manifold", "auto"),
         "voxel_size": args.get("voxel_size"), "size": args.get("size"),
         "size_axis": args.get("size_axis", "longest"), "to_ground": bool(args.get("ground", True)),
         "origin": args.get("origin", "bottom"),
         "flatten": {"auto": "auto", "on": True, "off": False}.get(args.get("flatten", "auto"), "auto"),
         "join": bool(args.get("join", True))}
    if a["floaters"] <= 0:
        a["floaters"] = None

    def apply(result, loaded):
        for o in objs:
            if o.name in loaded:
                _take_mesh(o, loaded[o.name], keep_transform=True)
        return {"objects": _clean_reports(result["reports"]), "seconds": result.get("seconds")}
    return _launch(ctx, "cleanup_mesh", objs, [{"op": "cleanup", "args": a}], apply)


# ---------------------------------------------------------------- retopo

@action("retopo",
      "Retopology. mode: quads (clean quad flow, sharp edges kept), triangles (low poly to an exact count) or auto "
      "(picks per shape and says why). detail low / medium / high or an exact faces count. The dense original stays "
      "hidden as the bake source. Running it again starts from that original. Slow: returns a job id.",
      {"type": "object", "properties": {
          "objects": _OBJECTS,
          "mode": {"type": "string", "enum": ["auto", "quads", "triangles"], "default": "auto"},
          "detail": {"type": "string", "enum": ["low", "medium", "high"], "default": "medium",
                     "description": "low ~3k, medium ~12k, high ~40k triangles (quads: half as many faces)."},
          "faces": {"type": "integer", "minimum": 8, "description": "Exact face count (overrides detail)."},
          "keep_sharp": {"type": "boolean", "default": True},
          "sharp_angle": {"type": "number", "default": 35, "description": "Degrees; sharper edges stay crisp."},
          "engine": {"type": "string", "enum": ["auto", "quadriflow", "instant_meshes", "quadwild", "qremeshify"],
                     "default": "auto", "description": "Quad remesher (auto: the best one installed)."},
          "symmetry": {"type": "string", "enum": ["auto", "x", "y", "z", "off"], "default": "auto"},
          "triangulate": {"type": "string", "enum": ["keep", "now", "on_export"], "default": "keep"},
          "keep_source": {"type": "boolean", "default": True,
                          "description": "Keep the dense original hidden for baking."}}},
      slow=True)
def retopo(ctx, args):
    objs = _targets(args)
    mode = args.get("mode", "auto")
    eng = args.get("engine", "auto")
    try:
        engine = X.pick_quad_engine(eng) if mode != "triangles" else "quadriflow"
    except ValueError as e:
        raise ToolError(str(e)) from None
    addons = None
    if engine == "qremeshify":
        addons = [X.find_qremeshify()]
    tri_opt = args.get("triangulate", "keep")
    sym = args.get("symmetry", "auto")
    a = {"mode": mode, "detail": args.get("detail", "medium"), "faces": args.get("faces"),
         "keep_sharp": bool(args.get("keep_sharp", True)), "sharp_angle": float(args.get("sharp_angle", 35)),
         "engine": engine, "symmetry": None if sym == "off" else sym,
         "triangulate": "now" if tri_opt == "now" else "keep"}
    keep_source = bool(args.get("keep_source", True))
    # retopo again: send the dense original (under the object's name) instead of the last result
    send, temps = [], []
    for o in objs:
        src = T.bake_source(o)
        if src is not None:
            tmp = bpy.data.objects.new(o.name + "__nighty_in", src.data)
            tmp.matrix_world = o.matrix_world.copy()
            temps.append(tmp)
            send.append(tmp)
        else:
            send.append(o)

    send_names = [s.name for s in send]

    def apply(result, loaded):
        out = []
        for o, sname in zip(objs, send_names):
            ob = loaded.get(sname)
            if ob is None:
                continue
            if T.bake_source(o) is None and keep_source:
                old = o.data
                name = old.name
                T.keep_bake_source(o, mesh=old)  # the dense mesh moves to the hidden source object
                U.restore_materials(ob.data, old)
                o.data = ob.data
                ob.data.name = name
            else:
                U.replace_mesh(o, ob.data)
            if tri_opt == "on_export":
                T.triangulate_option(o, "on_export")
        for r, o in zip(result["reports"], objs):
            r["object"] = o.name
            src = T.bake_source(o)
            if src is not None:
                r["bake_source"] = src.name
            out.append(r)
        return {"objects": _clean_reports(out), "seconds": result.get("seconds")}

    try:
        return _launch(ctx, "retopo", objs, [{"op": "retopo", "args": a}], apply, addons=addons, send=send)
    finally:
        for t in temps:
            bpy.data.objects.remove(t)


# ---------------------------------------------------------------- decimate

@action("decimate",
      "Low poly: reduce to an exact triangle count (faces) or by ratio, keeping sharp edges, UV seams and symmetry; "
      "flat areas merge first on hard-surface shapes. Slow: returns a job id.",
      {"type": "object", "properties": {
          "objects": _OBJECTS,
          "faces": {"type": "integer", "minimum": 4, "description": "Target triangles."},
          "ratio": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
          "symmetry": {"type": "string", "enum": ["auto", "x", "y", "z", "off"], "default": "auto"},
          "planar": {"type": "string", "enum": ["auto", "on", "off"], "default": "auto"},
          "keep_sharp": {"type": "boolean", "default": True},
          "sharp_angle": {"type": "number", "default": 35},
          "keep_source": {"type": "boolean", "default": True,
                          "description": "Keep the dense original hidden for baking."}}},
      slow=True)
def decimate(ctx, args):
    objs = _targets(args)
    if not args.get("faces") and not args.get("ratio"):
        raise ToolError("Give faces (a triangle count) or ratio.")
    sym = args.get("symmetry", "auto")
    planar = {"auto": "auto", "on": 2.0, "off": None}.get(args.get("planar", "auto"), "auto")
    a = {"faces": args.get("faces"), "ratio": args.get("ratio"), "symmetry": None if sym == "off" else sym,
         "planar": planar, "keep_sharp": float(args.get("sharp_angle", 35)) if args.get("keep_sharp", True) else None}
    keep_source = bool(args.get("keep_source", True))

    def apply(result, loaded):
        for o in objs:
            ob = loaded.get(o.name)
            if ob is None:
                continue
            if keep_source and T.bake_source(o) is None:
                old = o.data
                name = old.name
                T.keep_bake_source(o, mesh=old)
                U.restore_materials(ob.data, old)
                o.data = ob.data
                ob.data.name = name
            else:
                U.replace_mesh(o, ob.data)
        return {"objects": _clean_reports(result["reports"]), "seconds": result.get("seconds")}
    return _launch(ctx, "decimate", objs, [{"op": "decimate", "args": a}], apply)


# ---------------------------------------------------------------- split_parts

@action("split_parts",
      "Split a mesh into part objects (barrel, scope, grip...): auto, loose pieces, concave creases where parts "
      "meet, sharp-edge regions, materials, cutting planes, or labels from AI part segmentation. Returns each "
      "part's size and place so you can name them (names: biggest first). Slow: returns a job id.",
      {"type": "object", "properties": {
          "objects": _OBJECTS,
          "method": {"type": "string", "enum": ["auto", "loose", "concave", "sharp", "material", "plane", "attribute",
                                                "ai"], "default": "auto"},
          "angle": {"type": "number", "default": 30, "description": "Degrees for concave / sharp."},
          "planes": {"type": "array", "items": {"type": "object", "properties": {
              "point": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
              "normal": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}}},
              "description": "For method plane: cut planes in object space."},
          "min_size": {"type": "number", "default": 0.01,
                       "description": "Regions under this share of the surface join a neighbour."},
          "names": {"type": "array", "items": {"type": "string"},
                    "description": "Part names, biggest part first (e.g. [\"receiver\", \"barrel\"])."},
          "cap": {"type": "boolean", "description": "Close the cut openings (default: only for plane)."},
          "keep_original": {"type": "boolean", "default": False, "description": "Hide the original, don't delete."}}},
      slow=True)
def split_parts(ctx, args):
    objs = _targets(args)
    a = {"method": args.get("method", "auto"), "angle": float(args.get("angle", 30)), "planes": args.get("planes"),
         "min_size": float(args.get("min_size", 0.01)), "names": args.get("names"), "cap": args.get("cap"),
         "keep_original": True}
    if a["method"] == "ai":
        from ..nighty.mesh import parts as P
        if not P.segmenters():
            raise ToolError("AI part segmentation comes with the engine (not installed yet); use auto, loose, "
                            "concave, sharp, material or plane.")
    keep_original = bool(args.get("keep_original", False))

    def apply(result, loaded):
        reps = result["reports"]
        by_obj = {}
        for r in reps:
            by_obj[r.get("object")] = r
        out = []
        for o in objs:
            rep = by_obj.get(o.name, {})
            src = T.bake_source(o)
            rows = []
            for row in rep.get("parts", []):
                ob = loaded.get(row["name"])
                if ob is None:
                    continue
                for col in o.users_collection or [bpy.context.scene.collection]:
                    col.objects.link(ob)
                ob.parent = o.parent
                ob.matrix_world = o.matrix_world.copy()
                U.restore_materials(ob.data, o.data)
                if src is not None:
                    ob["nighty_bake_source"] = src
                    ob["nighty_high"] = src.name
                row["name"] = ob.name
                rows.append(row)
            rep["parts"] = rows
            rep["count"] = len(rows)
            if keep_original:
                o.hide_set(True)
                o.hide_render = True
            else:
                me = o.data
                bpy.data.objects.remove(o)
                if me.users == 0:
                    bpy.data.meshes.remove(me)
            out.append(rep)
        return {"objects": out}
    return _launch(ctx, "split_parts", objs, [{"op": "split_parts", "args": a}], apply)


# ---------------------------------------------------------------- uv_unwrap

@action("uv_unwrap",
      "UV unwrap one or more objects into one shared atlas: seams from sharp edges (hard-surface) or smart project "
      "(organic), islands packed with a margin for the texture size, the same texel density on every part, no "
      "overlaps. Slow: returns a job id.",
      {"type": "object", "properties": {
          "objects": _OBJECTS,
          "texture_size": {"type": "string", "enum": ["512", "1K", "2K", "4K", "8K"], "default": "2K"},
          "method": {"type": "string", "enum": ["auto", "seams", "smart", "xatlas"], "default": "auto"},
          "seam_angle": {"type": "number", "default": 60, "description": "Degrees; sharper crease lines become seams."},
          "margin_px": {"type": "integer", "minimum": 0, "description": "Space between islands in pixels."},
          "shared": {"type": "boolean", "default": True, "description": "One atlas for all objects (one texture set)."}}},
      slow=True)
def uv_unwrap(ctx, args):
    objs = _targets(args)
    method = args.get("method", "auto")
    if method == "xatlas" and not X.has_xatlas():
        raise ToolError("xatlas is not available in this Blender's Python; use auto, seams or smart.")
    a = {"texture_size": str(args.get("texture_size", "2K")), "method": method,
         "seam_angle": args.get("seam_angle"), "margin_px": args.get("margin_px"),
         "shared": bool(args.get("shared", True))}

    def apply(result, loaded):
        for o in objs:
            ob = loaded.get(o.name)
            if ob is not None:
                U.replace_mesh(o, ob.data)
        rep = result["reports"][0] if result["reports"] else {}
        rep.pop("seconds", None)
        return rep
    return _launch(ctx, "uv_unwrap", objs, [{"op": "uv_unwrap", "args": a}], apply)


# ---------------------------------------------------------------- make_lods

@action("make_lods",
      "Make LOD copies (<name>_LOD1, _LOD2...) by decimating: ratios of the triangles (default 0.5, 0.25, 0.1) or "
      "exact triangle counts. UVs and sharp edges kept; LODs are hidden in the viewport. Slow: returns a job id.",
      {"type": "object", "properties": {
          "objects": _OBJECTS,
          "ratios": {"type": "array", "items": {"type": "number", "exclusiveMinimum": 0, "maximum": 1}},
          "faces": {"type": "array", "items": {"type": "integer", "minimum": 4}}}},
      slow=True)
def make_lods(ctx, args):
    objs = _targets(args)
    a = {"ratios": args.get("ratios"), "faces": args.get("faces")}

    def apply(result, loaded):
        out = []
        fresh = set(ob.as_pointer() for ob in loaded.values())
        for o, rep in zip(objs, result["reports"]):
            for i in range(1, 12):  # replace older LODs of this object (not the ones that just came back)
                old = bpy.data.objects.get(f"{o.name}_LOD{i}")
                if old is not None and old.as_pointer() not in fresh and old.get("nighty_lod_of") == o.name:
                    me = old.data
                    bpy.data.objects.remove(old)
                    if me.users == 0:
                        bpy.data.meshes.remove(me)
            o["nighty_lod"] = 0
            rows = []
            for row in rep.get("lods", []):
                if row["lod"] == 0:
                    rows.append(row)
                    continue
                ob = loaded.get(row["name"])
                if ob is None:
                    continue
                for col in o.users_collection or [bpy.context.scene.collection]:
                    col.objects.link(ob)
                ob.parent = o.parent
                ob.matrix_world = o.matrix_world.copy()
                U.restore_materials(ob.data, o.data)
                ob.name = f"{o.name}_LOD{row['lod']}"
                ob["nighty_lod"] = row["lod"]
                ob["nighty_lod_of"] = o.name
                ob.hide_set(True)
                row["name"] = ob.name
                rows.append(row)
            out.append({"object": o.name, "lods": rows})
        return {"objects": out, "note": "LOD1+ are hidden in the viewport; exports find them by the _LODn names"}
    return _launch(ctx, "make_lods", objs, [{"op": "make_lods", "args": a}], apply)
