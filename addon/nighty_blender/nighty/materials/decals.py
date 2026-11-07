# SPDX-License-Identifier: GPL-3.0-or-later
"""Decals and text as separate sharp projections (never painted by an AI).

A decal is an image (a logo, a warning label, or text drawn by Blender's own font engine) projected along a
projector: an Image empty that shows the decal in the viewport. Move, turn or scale the empty and the decal follows
on the surface live; the bake writes it into the maps at full resolution. The projection is a box: the image's
plane times a depth, so it never shows through on the far side of a part.

    decals.add_decal(obj, text="NIGHTY ARMS", side="left", size=0.12, color="#e8e2d0")
    decals.add_decal(obj, image_path="C:/logos/skull.png", at=(0.1, 0, 0.05), size=0.05)
    decals.remove_decal("NIGHTY ARMS")
"""

import json
import math
import os

import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import compat
from .compat import Graph, socket

KEY = "nighty_decals"
PREFIX = "NB Decal · "

# side -> (direction the projector looks along, the view's right, the view's up), Blender's own views
SIDES = {
    "front": (Vector((0, 1, 0)), Vector((1, 0, 0)), Vector((0, 0, 1))),
    "back": (Vector((0, -1, 0)), Vector((-1, 0, 0)), Vector((0, 0, 1))),
    "left": (Vector((1, 0, 0)), Vector((0, -1, 0)), Vector((0, 0, 1))),
    "right": (Vector((-1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))),
    "top": (Vector((0, 0, -1)), Vector((1, 0, 0)), Vector((0, 1, 0))),
    "bottom": (Vector((0, 0, 1)), Vector((1, 0, 0)), Vector((0, -1, 0))),
}


def _world_bbox(obj):
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def _ray(obj, origin_w, dir_w, dg):
    """World ray against the evaluated object -> (hit, location_w, normal_w, distance)."""
    inv = obj.matrix_world.inverted()
    o_l = inv @ origin_w
    d_l = (inv.to_3x3() @ dir_w).normalized()
    ok, loc, nrm, _ = obj.evaluated_get(dg).ray_cast(o_l, d_l, depsgraph=dg)
    if not ok:
        return False, None, None, None
    loc_w = obj.matrix_world @ loc
    n_w = (obj.matrix_world.inverted().transposed().to_3x3() @ nrm).normalized()
    return True, loc_w, n_w, (loc_w - origin_w).length


def place(obj, side="front", at=None, normal=None, offset=(0.0, 0.0)):
    """Where the decal sits: (location, normal, right, up, thickness) in world space."""
    dg = bpy.context.evaluated_depsgraph_get()
    side = (side or "front").lower()
    if side not in SIDES:
        raise ValueError(f"side must be one of {', '.join(SIDES)}")
    look, right, up = SIDES[side]
    lo, hi = _world_bbox(obj)
    diag = (hi - lo).length
    if at is not None:
        at = Vector(at)
        inv = obj.matrix_world.inverted()
        ok, loc, nrm, _ = obj.evaluated_get(dg).closest_point_on_mesh(inv @ at, depsgraph=dg)
        if not ok:
            raise ValueError("could not find the surface near 'at'")
        loc_w = obj.matrix_world @ loc
        n_w = Vector(normal).normalized() if normal else \
            (obj.matrix_world.inverted().transposed().to_3x3() @ nrm).normalized()
    else:
        center = (lo + hi) / 2 + right * float(offset[0]) + up * float(offset[1])
        origin = center - look * diag
        ok, loc_w, n_w, _ = _ray(obj, origin, look, dg)
        if not ok:
            raise ValueError(f"nothing of {obj.name} is there from the {side} (check offset)")
        if normal:
            n_w = Vector(normal).normalized()
    # thickness behind the surface (so the projection box never reaches the far side)
    ok, back, _, dist = _ray(obj, loc_w - n_w * 1e-4, -n_w, dg)
    thickness = dist if ok else diag
    if abs(n_w.dot(up)) > 0.95:     # looking straight along 'up': use the view's right to orient
        up = right.cross(n_w)
    x = (up.cross(n_w)).normalized()
    if x.length < 0.5:
        x = right
    y = n_w.cross(x).normalized()
    return loc_w, n_w, x, y, thickness


def _decal_group(name, img, projector, aspect, roughness, metallic, opacity):
    gname = PREFIX + name
    old = bpy.data.node_groups.get(gname)
    if old is not None:
        bpy.data.node_groups.remove(old)
    ng, gin, gout = compat.new_group(gname, [
        ("Color", "NodeSocketColor", (0.5, 0.5, 0.5, 1)), ("Roughness", "NodeSocketFloat", 0.5),
        ("Metallic", "NodeSocketFloat", 0.0),
    ], [("Color", "NodeSocketColor", None), ("Roughness", "NodeSocketFloat", None),
        ("Metallic", "NodeSocketFloat", None)])
    g = Graph(ng)
    P = g.coords("Object", obj=projector)
    sep = g.node("ShaderNodeSeparateXYZ")
    g.set(sep.inputs[0], P)
    u = g.math("ADD", g.math("DIVIDE", sep.outputs[0], aspect[0]), 0.5)
    v = g.math("ADD", g.math("DIVIDE", sep.outputs[1], aspect[1]), 0.5)
    inbox = g.math("LESS_THAN", g.math("ABSOLUTE", sep.outputs[2]), 0.5)
    comb = g.node("ShaderNodeCombineXYZ")
    g.set(comb.inputs[0], u)
    g.set(comb.inputs[1], v)
    tex = g.image(img, comb.outputs[0], extension="CLIP", interpolation="Linear")
    a = g.math("MULTIPLY", g.math("MULTIPLY", tex.outputs[1], inbox), opacity)
    ins = {s.name: s for s in gin.outputs}
    col = g.mix(a, ins["Color"], tex.outputs[0])
    rough = g.mix(a, ins["Roughness"], float(roughness), kind="FLOAT")
    metal = g.mix(g.math("GREATER_THAN", a, 0.5), ins["Metallic"], float(metallic), kind="FLOAT")
    g.links.new(col, socket(gout.inputs, "Color"))
    g.links.new(rough, socket(gout.inputs, "Roughness"))
    g.links.new(metal, socket(gout.inputs, "Metallic"))
    compat.layout(ng)
    return ng


def _single_user(obj, slot):
    m = slot.material
    if m is None:
        return None
    for o in bpy.data.objects:
        if o is not obj and any(s.material is m for s in o.material_slots):
            m = m.copy()
            slot.material = m
            break
    return m


def _insert(mat, ng):
    p = compat.principled_of(mat)
    if p is None:
        return False
    tree = mat.node_tree
    node = tree.nodes.new("ShaderNodeGroup")
    node.node_tree = ng
    node.name = ng.name
    node.label = ng.name
    node.location = (p.location.x - 260, p.location.y - 120)
    for name in ("Color", "Roughness", "Metallic"):
        tgt = socket(p.inputs, "Base Color" if name == "Color" else name)
        src_in = socket(node.inputs, name)
        if tgt.is_linked:
            tree.links.new(tgt.links[0].from_socket, src_in)
        else:
            v = tgt.default_value
            src_in.default_value = tuple(v) if name == "Color" else v
        tree.links.new(socket(node.outputs, name), tgt)
    return True


def add_decal(obj, image_path=None, text=None, name=None, side="front", at=None, normal=None, offset=(0.0, 0.0),
              size=None, rotation=0.0, color="#ffffff", outline=0.0, outline_color="#111111", font=None,
              roughness=0.45, metallic=0, depth=None, opacity=1.0, folder=None, text_height_px=256):
    """Projects an image or text onto `obj`. Returns {name, projector, image, size_m, depth_m}."""
    from ..bake import asset_folder, png
    from ..bake.apply import restore_sources
    if obj is None or obj.type != "MESH":
        raise ValueError("target must be a mesh object")
    if (image_path is None) == (text is None):
        raise ValueError("give an image path or a text (one of them)")
    if metallic not in (0, 1, 0.0, 1.0):
        raise ValueError("metallic must be 0 or 1")
    name = (name or text or os.path.splitext(os.path.basename(image_path))[0])[:40]
    remove_decal(name, quiet=True)
    if text is not None:
        rgba = textraster_rgba(text, color, outline, outline_color, font, text_height_px)
        d = os.path.join(folder or asset_folder(obj.name), "decals")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{_safe(name)}.png")
        png.write(path, png.to_uint(rgba))
        img = bpy.data.images.load(path, check_existing=True)
        img.reload()
    else:
        if image_path in bpy.data.images:
            img = bpy.data.images[image_path]
        else:
            path = bpy.path.abspath(image_path)
            if not os.path.exists(path):
                raise ValueError(f"no image at {image_path}")
            img = bpy.data.images.load(path, check_existing=True)
    img["nighty_decal"] = True
    w, h = img.size
    if w == 0 or h == 0:
        raise ValueError("the image is empty")
    aspect = (w / max(w, h), h / max(w, h))
    loc, n, x, y, thickness = place(obj, side, at, normal, offset)
    lo, hi = _world_bbox(obj)
    if size is None:   # a quarter of the part across, by default
        size = 0.25 * min(v for v in (hi - lo) if v > 1e-4)
    s_big = float(size) / aspect[0]       # the image's larger side in meters
    dep = float(depth) if depth else min(max(0.45 * thickness, 0.002), s_big)
    rot = Matrix.Rotation(math.radians(float(rotation)), 3, n)
    x, y = rot @ x, rot @ y
    proj = bpy.data.objects.new(PREFIX + name, None)
    proj.empty_display_type = "IMAGE"
    proj.data = img
    proj.empty_display_size = 1.0
    proj.empty_image_offset = (-0.5, -0.5)
    try:
        proj.use_empty_image_alpha = True
        proj.color[3] = 0.6
        proj.empty_image_side = "FRONT"
    except (AttributeError, TypeError):
        pass
    basis = Matrix((x, y, n)).transposed().to_4x4()
    proj.matrix_world = Matrix.Translation(loc + n * 0.0005) @ basis @ Matrix.Diagonal((s_big, s_big, 2 * dep, 1.0))
    for coll in obj.users_collection:
        coll.objects.link(proj)
    if not proj.users_collection:
        bpy.context.scene.collection.objects.link(proj)
    mw = proj.matrix_world.copy()
    proj.parent = obj
    proj.matrix_world = mw
    proj["nighty_decal_of"] = obj.name
    proj.hide_render = True
    ng = _decal_group(name, img, proj, aspect, roughness, metallic, opacity)
    restore_sources(obj)
    done = 0
    for slot in obj.material_slots:
        m = _single_user(obj, slot)
        if m is not None and _insert(m, ng):
            done += 1
    if done == 0:
        raise ValueError(f"{obj.name} has no Principled material to carry the decal (assign materials first)")
    rows = [r for r in _decals(obj) if r["name"] != name]
    rows.append({"name": name, "projector": proj.name, "image": img.filepath or img.name, "text": text})
    obj[KEY] = json.dumps(rows)
    return {"name": name, "projector": proj.name, "image": bpy.path.abspath(img.filepath) if img.filepath else img.name,
            "size_m": round(float(size), 4), "depth_m": round(dep, 4), "location": [round(v, 4) for v in loc],
            "normal": [round(v, 3) for v in n]}


def textraster_rgba(text, color, outline, outline_color, font, height_px):
    from .textraster import text_rgba
    return text_rgba(text, height_px=height_px, color=color, outline=outline, outline_color=outline_color,
                     font_path=font)


def _safe(name):
    import re
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", name).strip("_") or "decal"


def _decals(obj):
    try:
        return json.loads(obj.get(KEY, "[]"))
    except ValueError:
        return []


def list_decals(obj):
    return _decals(obj)


def remove_decal(name, quiet=False):
    """Takes a decal off every material that carries it and deletes its projector."""
    gname = PREFIX + name
    ng = bpy.data.node_groups.get(gname)
    found = False
    if ng is not None:
        for mat in bpy.data.materials:
            if not mat.node_tree:
                continue
            for node in [n for n in mat.node_tree.nodes if n.type == "GROUP" and n.node_tree is ng]:
                tree = mat.node_tree
                for nm in ("Color", "Roughness", "Metallic"):
                    out_links = list(socket(node.outputs, nm).links)
                    inp = socket(node.inputs, nm)
                    for link in out_links:
                        if inp.is_linked:
                            tree.links.new(inp.links[0].from_socket, link.to_socket)
                        else:
                            v = inp.default_value
                            link.to_socket.default_value = tuple(v) if nm == "Color" else v
                tree.nodes.remove(node)
                found = True
        bpy.data.node_groups.remove(ng)
    proj = bpy.data.objects.get(gname)
    if proj is not None:
        owner = bpy.data.objects.get(proj.get("nighty_decal_of", ""))
        bpy.data.objects.remove(proj)
        found = True
        if owner is not None:
            owner[KEY] = json.dumps([r for r in _decals(owner) if r["name"] != name])
    if not found and not quiet:
        raise ValueError(f"no decal named {name!r}")
    return found


__all__ = ["add_decal", "remove_decal", "list_decals", "place", "np"]
