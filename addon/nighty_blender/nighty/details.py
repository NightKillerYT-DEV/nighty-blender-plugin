# SPDX-License-Identifier: GPL-3.0-or-later
"""Small ready-made details: bolts, rivets, a rail, handles, 3D text. They sit on a surface point (at) and face
along axis (the direction out of that surface: "X", "-Y"... or (x, y, z)). n.place_on puts one on any surface."""

import math

import bpy
from mathutils import Vector

from . import core
from .core import get

__all__ = ["bolt", "rivets", "rail", "handle", "text3d"]


def bolt(radius=0.005, height=None, kind="hex", axis="Z", at=(0, 0, 0), washer=False, segments=None, name="Bolt",
         material=None, collection=None, parent=None):
    """A bolt head standing on at, pointing along axis. kind: "hex" (six sides, chamfered), "round" (dome),
    "socket" (round with a hex recess). washer adds a thin ring under it.

        n.bolt(0.004, kind="hex", axis="-Y", at=(0.1, -0.2, 0.3))
    """
    from .shapes import cylinder, dome
    from .modify import bevel, boolean_cut
    d = core.axis_vector(axis)
    base = Vector(at)
    kw = {"material": material, "collection": collection, "parent": parent}
    if kind == "round":
        h = height or radius * 0.55
        obj = dome(radius, height=h, segments=segments, axis=axis, at=base, name=name, **kw)
    elif kind == "socket":
        h = height or radius * 0.7
        obj = cylinder(radius, h, segments=segments, axis=axis, at=base + d * (h / 2), name=name, **kw)
        recess = cylinder(radius * 0.45, h, segments=6, axis=axis, at=base + d * h, name=name + "_recess")
        boolean_cut(obj, recess)
        bevel(obj, width=radius * 0.12, segments=None if radius < 0.004 else 2)
    else:
        h = height or radius * 0.65
        obj = cylinder(radius, h, segments=6, axis=axis, at=base + d * (h / 2), name=name, **kw)
        bevel(obj, width=radius * 0.1, segments=None if radius < 0.004 else 2)
    if washer:
        from .assemble import merge_parts
        ring = cylinder(radius * 1.35, radius * 0.18, segments=segments, axis=axis, at=base + d * (radius * 0.09),
                        name=name + "_washer", **kw)
        bevel(ring, width=radius * 0.05, segments=2)
        lift = d * (radius * 0.18)
        obj.location = obj.location + lift
        obj = merge_parts([obj, ring], name=name, weld=False)
    return obj


def rivets(points, radius=0.003, axis="Z", height=None, segments=None, name="Rivets", material=None, collection=None,
           parent=None):
    """Round rivets (domes) at several surface points, as one object.

        n.rivets([(x, -0.2, 0.05) for x in (-0.2, 0, 0.2)], radius=0.004, axis="-Y")
    """
    from .shapes import dome
    from .assemble import merge_parts
    parts = [dome(radius, height=height or radius * 0.55, segments=segments, axis=axis, at=p, name=name,
                  material=material, collection=collection) for p in points]
    obj = merge_parts(parts, name=name, weld=False) if len(parts) > 1 else parts[0]
    if parent is not None:
        from .assemble import parent as set_parent
        set_parent(obj, parent)
    return obj


def rail(length=0.2, width=0.021, height=0.0094, slot=0.0052, pitch=0.01, axis="X", at=(0, 0, 0), name="Rail",
         material=None, collection=None, parent=None):
    """An accessory rail (dovetail profile with cross slots), lying along axis ("X" or "Y") on top of at.

        n.rail(0.18, at=(0.05, 0, 0.065))
    """
    from .shapes import extrude, box
    from .modify import boolean_cut, bevel
    from .assemble import merge_parts
    w, h = width / 2.0, height
    profile = [(-w * 0.72, 0.0), (w * 0.72, 0.0), (w * 0.72, h * 0.35), (w, h * 0.55), (w, h * 0.78),
               (w * 0.8, h), (-w * 0.8, h), (-w, h * 0.78), (-w, h * 0.55), (-w * 0.72, h * 0.35)]
    obj = extrude(profile, depth=length, plane="YZ", name=name, material=material, collection=collection)
    count = max(1, int((length - pitch) / pitch))
    cutters = []
    for k in range(count):
        x = (k - (count - 1) / 2.0) * pitch
        cutters.append(box((slot, width * 1.4, h * 0.5), at=(x, 0, h * 0.78 + h * 0.25), name=name + "_slot"))
    cutter = merge_parts(cutters, name=name + "_slots", weld=False) if len(cutters) > 1 else cutters[0]
    boolean_cut(obj, cutter)
    bevel(obj, width=min(width, height) * 0.03)
    if str(axis).upper().lstrip("+-") == "Y":
        obj.rotation_euler = (0, 0, math.radians(90))
        from .place import apply_transforms
        apply_transforms(obj)
    obj.location = Vector(at)
    if parent is not None:
        from .assemble import parent as set_parent
        set_parent(obj, parent)
    return obj


def handle(width=0.12, height=0.04, radius=0.006, axis="Z", at=(0, 0, 0), along=None, name="Handle",
           material=None, collection=None, parent=None):
    """A U-shaped bar handle: feet on the surface at at, arching height out along axis, width along along
    (default: X, or Y when axis is X). For crates, chests, doors, drawers.

        n.handle(0.14, 0.035, 0.007, axis="-Y", at=(0, -0.3, 0.25))
    """
    from .shapes import pipe
    out = core.axis_vector(axis)
    if along is None:
        along = "Y" if abs(out.x) > 0.5 else "X"
    side = core.axis_vector(along)
    hw = width / 2.0
    pts = [-side * hw, -side * hw + out * height, side * hw + out * height, side * hw]
    return pipe([tuple(p) for p in pts], radius=radius, bend=min(height * 0.6, hw * 0.6), at=at, name=name,
                material=material, collection=collection, parent=parent)


def text3d(body, size=0.05, depth=0.005, axis="-Y", at=(0, 0, 0), bevel=None, resolution=None, font=None,
           align="CENTER", name="Text", material=None, collection=None, parent=None):
    """Raised 3D letters as a mesh, facing along axis (-Y = readable from the front). Decals are better for
    printed text; use this for embossed or cut letters. bevel: meters (0 = none); resolution: curve steps per
    letter segment (default from the detail level; fewer = lighter).

        n.text3d("NIGHTY", size=0.04, depth=0.004, axis="-Y", at=(0, -0.201, 0.3))
    """
    import bmesh

    def build(spacing):
        curve = bpy.data.curves.new(name, "FONT")
        curve.body = str(body)
        curve.size = float(size)
        curve.extrude = float(depth) / 2.0
        curve.bevel_depth = min(depth * 0.1, size * 0.01) if bevel is None else float(bevel)
        curve.bevel_resolution = 1
        curve.resolution_u = int(resolution or {2: 2, 4: 3, 6: 5}.get(core.bevel_segments(), 3))
        curve.space_character = spacing
        curve.align_x = align
        curve.align_y = "CENTER"
        if font:
            curve.font = bpy.data.fonts.load(font, check_existing=True)
        tmp = bpy.data.objects.new(name + "_curve", curve)
        bpy.context.scene.collection.objects.link(tmp)
        core.update()
        dg = bpy.context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
        bpy.data.objects.remove(tmp, do_unlink=True)
        bpy.data.curves.remove(curve)
        bm = bmesh.new()
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)  # caps and sides come apart from the font
        return bm

    # letters that touch would fuse into edges with 3+ faces: open the spacing a little until none do
    for spacing in (1.0, 1.05, 1.1, 1.18):
        bm = build(spacing)
        if not any(len(e.link_faces) > 2 for e in bm.edges):
            break
        bm.free()
    # letters are made lying in XY facing +Z: stand them up to face the axis
    bmesh.ops.transform(bm, matrix=core.axis_matrix(axis), verts=bm.verts)
    from .modify import _fix_slivers  # font fills leave a few sliver triangles: close them up
    bmesh.ops.dissolve_degenerate(bm, dist=size * 1e-5, edges=bm.edges)
    _fix_slivers(bm, (size * 5e-5) ** 2)
    for layer in list(bm.loops.layers.uv.values()):
        bm.loops.layers.uv.remove(layer)  # the font's UVs overlap; unwrap later if needed
    return core.mesh_object(bm, name, at=at, material=material, collection=collection, parent=parent)
