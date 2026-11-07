# SPDX-License-Identifier: GPL-3.0-or-later
# Two small fixes imported models often need:
#   fix_shading  normals pointing out, smooth shading with sharp edges by angle (no faceted look, no dark smears from
#                broken custom normals)
#   fix_seams    texture seams: every image on the parts' materials gets its colors grown outward past the UV
#                islands' edges, so mipmaps and filtering never pull in the empty background color (thin lines
#                along the seams in game)

import math

import bmesh
import bpy
import numpy as np

from . import ToolError, action
from .scene import NAMES, targets


@action("fix_shading",
        "Normals out, smooth shading with sharp edges by angle; clear: true also drops broken custom normals.",
        {"type": "object", "properties": {
            "objects": NAMES,
            "angle": {"type": "number", "description": "Edges sharper than this stay sharp (degrees, default 30)."},
            "clear": {"type": "boolean", "description": "Remove custom split normals first (default true)."},
            "flat": {"type": "boolean", "description": "Flat shading instead (low poly look)."}}},
        changes=True)
def fix_shading(ctx, args):
    objs = [o for o in targets(args, key="objects") if o.type == "MESH"]
    if not objs:
        raise ToolError("No mesh objects to fix.")
    angle = math.radians(float(args.get("angle") or 30.0))
    rows = []
    for o in objs:
        me = o.data
        cleared = False
        if args.get("clear", True) and getattr(me, "has_custom_normals", False):
            try:
                with bpy.context.temp_override(object=o, active_object=o, selected_objects=[o]):
                    bpy.ops.mesh.customdata_custom_splitnormals_clear()
                cleared = True
            except Exception:  # noqa: BLE001 - an older API: leave them
                pass
        bm = bmesh.new()
        bm.from_mesh(me)
        before = sum(1 for f in bm.faces if f.normal.length > 0)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
        flat = bool(args.get("flat"))
        smooth = np.full(len(me.polygons), not flat, dtype=bool)
        me.polygons.foreach_set("use_smooth", smooth)
        sharp = 0
        if not flat:
            if hasattr(me, "set_sharp_from_angle"):
                me.set_sharp_from_angle(angle=angle)
            else:  # Blender 4.0 and older
                me.use_auto_smooth = True
                me.auto_smooth_angle = angle
            attr = me.attributes.get("sharp_edge")
            if attr is not None:
                vals = np.zeros(len(me.edges), dtype=bool)
                attr.data.foreach_get("value", vals)
                sharp = int(vals.sum())
        me.update()
        rows.append({"object": o.name, "faces": before, "shading": "flat" if flat else "smooth",
                     "sharp_edges": sharp, "custom_normals_cleared": cleared})
    if hasattr(ctx, "undo_label"):
        ctx.undo_label = "fix shading"
    return {"objects": rows, "next": "look (matcap) to see the shading"}


def _images_of(objs):
    seen = {}
    for o in objs:
        for slot in o.material_slots:
            m = slot.material
            if m is None or not m.use_nodes:
                continue
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image is not None and n.image.has_data:
                    seen.setdefault(n.image.name, (n.image, set()))[1].add(o.name)
    return seen


@action("fix_seams",
        "Grows every texture's colors outward past the UV island edges (no thin lines along seams in game).",
        {"type": "object", "properties": {
            "parts": NAMES,
            "margin_px": {"type": "integer", "description": "How far to grow, in pixels (default 1/64 of the size)."}}},
        changes=True)
def fix_seams(ctx, args):
    from ..nighty.bake import maps, uvraster
    objs = [o for o in targets(args, key="parts") if o.type == "MESH"]
    if not objs:
        raise ToolError("No mesh objects.")
    if any(not o.data.uv_layers for o in objs):
        raise ToolError("Some parts have no UVs: mesh uv_unwrap first.")
    images = _images_of(objs)
    if not images:
        raise ToolError("These parts have no image textures (nothing to fix).")
    rows = []
    for name, (img, users) in images.items():
        w, h = img.size
        if w != h:
            rows.append({"image": name, "skipped": "not square"})
            continue
        tri_uv = []
        for o in objs:
            if o.name not in users:
                continue
            arrays = uvraster.mesh_arrays(o.data)
            if arrays is None:
                continue
            uv, tl, _tp, _lv = arrays
            tri_uv.append(uv[tl])
        if not tri_uv:
            continue
        covered, _overlap = uvraster.rasterize(np.concatenate(tri_uv), w)
        px = np.empty(w * h * img.channels, dtype=np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(h, w, img.channels)
        margin = int(args.get("margin_px") or max(4, w // 64))
        grown, filled = maps.dilate(px[..., :3], covered, margin)
        changed = int(filled.sum() - covered.sum())
        if changed:
            px[..., :3] = grown
            img.pixels.foreach_set(px.ravel())
            img.update()
            try:                 # kept inside the .blend: the person's own texture files are never written over
                img.pack()
            except RuntimeError:
                pass
        rows.append({"image": name, "size": w, "margin_px": margin, "pixels_filled": changed,
                     "covered_pct": round(100 * float(covered.mean()), 1)})
    if hasattr(ctx, "undo_label"):
        ctx.undo_label = "fix seams"
    return {"images": rows}
