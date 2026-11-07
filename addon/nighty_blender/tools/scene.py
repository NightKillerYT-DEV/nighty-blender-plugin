# SPDX-License-Identifier: GPL-3.0-or-later
# Scene tools: scene_info (a compact tree), look (pictures of the model from fixed views), measure (sizes in meters).

import bpy

from . import ToolError, image, text, action
from ..nighty import check, core, view

NAMES = {"type": "array", "items": {"type": "string"},
         "description": "Object names (default: the selected objects, else every visible mesh)."}


def targets(args, key="names", kinds=("MESH", "CURVE", "SURFACE", "FONT", "META")):
    """Objects named in args[key]; else the selected ones; else every visible model object."""
    names = args.get(key)
    if names:
        if isinstance(names, str):
            names = [names]
        missing = [n for n in names if n not in bpy.data.objects]
        if missing:
            have = sorted(o.name for o in bpy.context.scene.objects)[:40]
            raise ToolError(f"No object named {', '.join(missing)}. Objects: {', '.join(have) or 'none'}.")
        return [bpy.data.objects[n] for n in names]
    try:
        sel = [o for o in bpy.context.selected_objects if o.type in kinds and not o.get("nighty_role")]
    except AttributeError:
        sel = []
    if sel:
        return sel
    objs = [o for o in core.objects("ALL") if o.type in kinds]
    if not objs:
        raise ToolError("The scene has no model objects yet.")
    return objs


def _r(v, d=3):
    return [round(float(c), d) for c in v]


# ---------- scene_info ----------

def _row(o, depth, limit, counter):
    counter[0] += 1
    row = {"name": o.name, "type": o.type}
    if o.get("nighty_role"):
        row["role"] = o["nighty_role"]
    row["loc"] = _r(o.matrix_world.translation)
    if any(abs(a) > 1e-6 for a in o.rotation_euler):
        row["rot_deg"] = [round(a * 57.29578, 1) for a in o.rotation_euler]
    if any(abs(s - 1) > 1e-6 for s in o.scale):
        row["scale"] = _r(o.scale)
    if o.type in ("MESH", "CURVE", "SURFACE", "FONT", "META"):
        row["size"] = _r(o.dimensions)
    if o.type == "MESH":
        row["faces"] = len(o.data.polygons)
    if getattr(o, "modifiers", None) and len(o.modifiers):
        row["mods"] = [m.type.lower() for m in o.modifiers]
    mats = [s.material.name for s in o.material_slots if s.material] if hasattr(o, "material_slots") else []
    if mats:
        row["mats"] = mats
    if not o.visible_get():
        row["hidden"] = True
    kids = [c for c in o.children if c.name in bpy.context.scene.objects]
    if kids and depth < 6:
        row["children"] = [_row(c, depth + 1, limit, counter) for c in kids if counter[0] < limit]
    return row


@action("scene_info",
      "The scene as a compact tree: collections, objects (type, location, size, faces, modifiers, materials, "
      "children), selection, units and Blender version. Call it first.",
      {"type": "object", "properties": {
          "collection": {"type": "string", "description": "Only this collection."},
          "limit": {"type": "integer", "description": "Most objects to list (default 150)."}}},
      changes=False)
def scene_info(ctx, args):
    sc = bpy.context.scene
    limit = max(1, min(2000, int(args.get("limit") or 150)))
    counter = [0]
    seen = set()

    def coll_row(coll):
        objs = [o for o in coll.objects if o.parent is None or o.parent.name not in coll.objects]
        row = {"collection": coll.name, "objects": []}
        for o in objs:
            if counter[0] >= limit:
                break
            if o.name in seen:
                continue
            seen.add(o.name)
            row["objects"].append(_row(o, 0, limit, counter))
        kids = [coll_row(c) for c in coll.children]
        kids = [k for k in kids if k["objects"] or k.get("children")]
        if kids:
            row["children"] = kids
        return row
    root = sc.collection
    if args.get("collection"):
        root = bpy.data.collections.get(args["collection"])
        if root is None:
            raise ToolError(f"No collection named {args['collection']}.")
    tree = coll_row(root)
    total = len(sc.objects)
    out = {"blender": bpy.app.version_string, "file": bpy.path.basename(bpy.data.filepath) or "(not saved)",
           "units": f"{sc.unit_settings.system.lower()} x{round(sc.unit_settings.scale_length, 4)}",
           "frame": sc.frame_current, "engine": sc.render.engine, "objects": total, "tree": tree}
    try:
        out["selected"] = [o.name for o in bpy.context.selected_objects][:30]
        act = bpy.context.view_layer.objects.active
        out["active"] = act.name if act else None
    except AttributeError:
        pass
    if counter[0] < total and counter[0] >= limit:
        out["more"] = f"{total - counter[0]} more objects not listed (raise limit or pick a collection)"
    nighty = {"detail": core.settings()["detail"], "size_m": core.settings()["size"]}
    out["nighty"] = nighty
    return out


# ---------- look ----------

VIEW_NAMES = sorted(view.VIEWS)


@action("look",
      "Pictures of the model from fixed views (default front, right, top and a 3/4 view) in one image, plus each "
      "camera's pose. mode: solid (material colors), matcap (form and shading errors), material (studio render: "
      "real materials, soft lights, ground shadow, rendered by a background Blender), silhouette. View \"hero\" "
      "picks the best 3/4 angle. wireframe: true draws the edges on top. Off-screen: the view and settings stay as "
      "they are, and Blender keeps running while it renders. A render that takes longer than 40 s answers with a "
      "job id: then job { action: wait }. Use it after every change.",
      {"type": "object", "properties": {
          "names": NAMES,
          "views": {"type": "array", "items": {"type": "string", "enum": VIEW_NAMES},
                    "description": "Default [front, right, top, three_quarter]. Front looks from -Y."},
          "mode": {"type": "string", "enum": list(view.MODES), "description": "Default solid."},
          "wireframe": {"type": "boolean", "description": "Edges on top (topology check)."},
          "size": {"type": "integer", "description": "Pixels per view, 64-1024 (default 320)."},
          "perspective": {"type": "boolean", "description": "Front / side / top in perspective (default ortho)."},
          "separate": {"type": "boolean", "description": "One picture per view instead of a grid."},
          "references": {"type": "boolean", "description": "Draw loaded reference pictures behind (ortho views)."}}},
      changes=False)
def look(ctx, args):
    objs = targets(args)
    views = args.get("views") or ["front", "right", "top", "three_quarter"]
    bad = [v for v in views if v not in view.VIEWS]
    if bad:
        raise ToolError(f"Unknown view {', '.join(bad)}; use {', '.join(VIEW_NAMES)}.")
    mode = args.get("mode") or "solid"
    if mode not in view.MODES:
        raise ToolError(f"mode must be one of {', '.join(view.MODES)}.")
    size = int(args.get("size") or (320 if mode != "material" else 384))
    persp = True if args.get("perspective") else None
    refs = []
    if args.get("references"):
        from .reference import reference_objects
        refs = reference_objects()
    b = core.bounds(objs)
    info = {"objects": [o.name for o in objs][:40], "mode": mode,
            "bounds": {"size": _r(b.size, 4), "center": _r(b.center, 4)}}
    if not args.get("separate") and len(views) > 1:
        cols = 1 if len(views) == 1 else 2 if len(views) <= 4 else 3
        info["layout"] = f"{cols} per row, in the order of views, left to right then down"

    def blocks(pngs, poses):
        info["views"] = poses
        return [text(info)] + [image(p) for p in pngs]
    if mode == "material":   # Cycles in a background Blender: a job, so Blender never freezes
        gen = view.material_look_steps(objs, views=views, size=size, wire=bool(args.get("wireframe")),
                                       persp=persp, combine=not args.get("separate"))
        return _job(ctx, gen, "Studio render", lambda res: blocks(res["pngs"], res["poses"]))
    gen = view.look_steps(objs, views=views, mode=mode, wire=bool(args.get("wireframe")), size=size,
                          combine=not args.get("separate"), persp=persp, references=refs)
    return _job(ctx, gen, "Look", lambda res: blocks(*res))   # one view per step: Blender never freezes


def _job(ctx, gen, label, done):
    """Runs a steps generator as an addon job, one step per tick, so Blender keeps running. The call waits for it
    (parked, up to 40 s) and answers with the result; a longer one answers with the job id (then wait_job). With no
    jobs framework it runs to the end here. done(result) turns the generator's result into the answer."""
    start = getattr(ctx, "start_job", None)
    if not callable(start):
        while True:
            try:
                next(gen)
            except StopIteration as stop:
                return done(stop.value)

    def step_fn(job):
        while True:
            if getattr(job, "cancelled", False):
                gen.close()
                return {"cancelled": True}
            try:
                p = next(gen)
            except StopIteration as stop:
                return done(stop.value)
            except RuntimeError as error:
                raise ToolError(f"Render failed: {error}")
            yield p
    job = start(step_fn, label)
    wait = getattr(ctx, "wait_job", None)
    return wait(job["job"], 40) if callable(wait) and isinstance(job, dict) and "job" in job else job


# ---------- measure ----------

@action("measure",
      "Sizes in meters: each object's bounds (size, min, max, center), the group's, optional distances between "
      "pairs (surface gap, touching) and a comparison with a reference or ghost object (size ratio, overlap, "
      "average surface distance).",
      {"type": "object", "properties": {
          "names": NAMES,
          "pairs": {"type": "array", "items": {"type": "array", "items": {"type": "string"}},
                    "description": "[[a, b], ...] object pairs to measure the distance between."},
          "reference": {"type": "string", "description": "A reference / ghost object to compare the objects with."}}},
      changes=False)
def measure(ctx, args):
    objs = targets(args)
    out = {"objects": check.measure(objs)}
    if len(objs) > 1:
        out["all"] = out["objects"].pop("all")
    pairs = args.get("pairs") or []
    if pairs:
        out["pairs"] = []
        for p in pairs[:40]:
            if not isinstance(p, (list, tuple)) or len(p) != 2:
                raise ToolError("pairs: each pair is [name_a, name_b].")
            for name in p:
                if name not in bpy.data.objects:
                    raise ToolError(f"No object named {name}.")
            row = {"a": p[0], "b": p[1]}
            row.update(check.distance(p[0], p[1]))
            out["pairs"].append(row)
    if args.get("reference"):
        ref = args["reference"]
        if ref not in bpy.data.objects:
            raise ToolError(f"No reference object named {ref}.")
        out["reference"] = {"name": ref}
        out["reference"].update(check.compare([o for o in objs if o.name != ref], ref))
    out["units"] = "meters"
    return out
