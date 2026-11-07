# SPDX-License-Identifier: GPL-3.0-or-later
"""Placing parts relative to each other (no guessing coordinates): align, snap, stack, distribute, ground.

Directions: front = -Y, back = +Y, left = -X, right = +X, top = +Z, bottom = -Z (Blender's views).
"""

import math

import bpy
from mathutils import Matrix, Vector

from . import core
from .core import bounds, get, to_list

__all__ = ["align", "snap", "place_on", "stack", "distribute", "ground", "center", "move", "rotate",
           "apply_transforms", "scale_to", "set_origin"]

_REL = {
    # relation: (axis, side of a, side of b)  sides: -1 min, 0 center, +1 max
    "on_top": (2, -1, 1), "above": (2, -1, 1), "below": (2, 1, -1), "under": (2, 1, -1),
    "front": (1, 1, -1), "in_front": (1, 1, -1), "back": (1, -1, 1), "behind": (1, -1, 1),
    "left": (0, 1, -1), "right": (0, -1, 1),
    "flush_top": (2, 1, 1), "flush_bottom": (2, -1, -1), "flush_front": (1, -1, -1), "flush_back": (1, 1, 1),
    "flush_left": (0, -1, -1), "flush_right": (0, 1, 1),
    "inside_top": (2, 1, 1), "inside_bottom": (2, -1, -1),
    "center_x": (0, 0, 0), "center_y": (1, 0, 0), "center_z": (2, 0, 0),
}


def _side_value(b, axis, side):
    if side < 0:
        return b.min[axis]
    if side > 0:
        return b.max[axis]
    return b.center[axis]


def move(objs, delta):
    """Moves objects (top-level ones; children follow) by delta (x, y, z) meters."""
    objs = to_list(objs)
    delta = Vector(delta)
    core.update()
    for o in objs:
        if o.parent is None or o.parent not in objs:
            mw = o.matrix_world.copy()
            mw.translation = mw.translation + delta
            o.matrix_world = mw
    core.update()
    return objs


def align(obj, target, *relations, gap=0.0, offset=(0, 0, 0)):
    """Places obj against target. Axes no relation names are centered on target (use "keep_x" etc. to keep).

    relations: "on_top", "below", "front", "back", "left", "right" (outside, touching; gap in meters),
    "flush_top", "flush_bottom", "flush_front", "flush_back", "flush_left", "flush_right" (edges lined up),
    "center" (all axes), "center_x" / "center_y" / "center_z", "keep_x" / "keep_y" / "keep_z".
    obj and target may be lists (moved / measured together).

        n.align(scope, receiver, "on_top", "flush_back", gap=0.002)
        n.align(lid, body, "on_top")
    """
    objs = to_list(obj)
    tb = bounds(target)
    ob = bounds(objs)
    rels = [str(r).lower() for r in relations] or ["center"]
    delta = Vector((0, 0, 0))
    done = set()
    for r in rels:
        if r == "center":
            continue
        if r.startswith("keep_"):
            done.add("xyz".index(r[-1]))
            continue
        if r not in _REL:
            raise ValueError(f"unknown relation {r!r}; use one of {sorted(_REL) + ['center']}")
        axis, sa, sb = _REL[r]
        g = gap if r in ("on_top", "above", "below", "under", "front", "in_front", "back", "behind", "left",
                         "right") else 0.0
        g = g * (1 if sb > 0 else -1)
        delta[axis] = _side_value(tb, axis, sb) + g - _side_value(ob, axis, sa)
        done.add(axis)
    for axis in range(3):
        if axis not in done:
            delta[axis] = tb.center[axis] - ob.center[axis]
    move(objs, delta + Vector(offset))
    return obj


def rotate(objs, degrees, axis="Z", pivot=None):
    """Turns objects together around an axis ("X", "Y", "Z" or (x, y, z)) through pivot (default: their middle).

        n.rotate([blade, guard, grip], 25, "Z")
    """
    objs = to_list(objs)
    core.update()
    c = Vector(pivot) if pivot is not None else bounds(objs).center
    turn = Matrix.Translation(c) @ Matrix.Rotation(math.radians(degrees), 4, core.axis_vector(axis)) @ \
        Matrix.Translation(-c)
    for o in objs:
        if o.parent is None or o.parent not in objs:
            o.matrix_world = turn @ o.matrix_world
    core.update()
    return objs


def place_on(obj, target, direction="-Z", up="Z", offset=0.0, max_distance=10.0):
    """Moves obj's origin onto target's surface (a ray from obj along direction) and turns obj so its up axis
    follows the surface there. For spots on a mushroom cap, bolts on a curved hull, decals.

        spot = n.dome(0.01, height=0.003, at=(0.03, 0.02, 0.5)); n.place_on(spot, cap, "-Z")
    """
    from mathutils.bvhtree import BVHTree
    obj = get(obj)
    core.update()
    dg = bpy.context.evaluated_depsgraph_get()
    d = core.axis_vector(direction)
    origin = obj.matrix_world.translation.copy()
    best = None
    for t in to_list(target):
        tree = BVHTree.FromObject(t, dg)
        inv = t.matrix_world.inverted()
        o_local = inv @ (origin - d * 1e-4)
        d_local = (inv.to_3x3() @ d).normalized()
        hit, normal, _, _ = tree.ray_cast(o_local, d_local, max_distance)
        if hit is None:
            hit, normal, _, _ = tree.ray_cast(inv @ (origin - d * max_distance * 0.5), d_local, max_distance)
        if hit is not None:
            w = t.matrix_world @ hit
            nw = (inv.to_3x3().transposed() @ normal).normalized()
            dist = (w - origin).length
            if best is None or dist < best[0]:
                best = (dist, w, nw)
    if best is None:
        raise ValueError(f"place_on: no surface of {target} along {direction}")
    _, point, normal = best
    rot = core.axis_vector(up).rotation_difference(normal)
    obj.rotation_mode = "XYZ"
    obj.rotation_euler = (rot @ obj.rotation_euler.to_quaternion()).to_euler()
    obj.location = point + normal * float(offset)
    core.update()
    return obj


def snap(obj, onto, direction="-Z", gap=0.0, max_distance=10.0):
    """Moves obj along direction until it touches onto's surface (ray cast from obj's facing points).

        n.snap(bolt, hull, "-Y")       # push a bolt onto a curved side
    """
    from mathutils.bvhtree import BVHTree
    objs = to_list(obj)
    targets = to_list(onto)
    d = core.axis_vector(direction)
    core.update()
    dg = bpy.context.evaluated_depsgraph_get()
    trees = []
    for t in targets:
        tree = BVHTree.FromObject(t, dg)
        trees.append((t.matrix_world.copy(), t.matrix_world.inverted(), tree))
    import numpy as np
    pts = np.concatenate([core.world_points(o, True, dg) for o in objs])
    proj = pts @ np.array(d)
    lead = pts[proj >= proj.max() - max(1e-6, (proj.max() - proj.min()) * 0.02)]
    best = None
    for p in lead[:: max(1, len(lead) // 200)]:
        origin = Vector(p) - d * 1e-5
        for mw, inv, tree in trees:
            o_local = inv @ origin
            d_local = (inv.to_3x3() @ d).normalized()
            hit, normal, index, dist = tree.ray_cast(o_local, d_local, max_distance)
            if hit is not None:
                world = mw @ hit
                dd = (world - origin).dot(d)
                if best is None or dd < best:
                    best = dd
    if best is None:
        raise ValueError(f"snap: nothing of {[t.name for t in targets]} in direction {direction}")
    move(objs, d * (best - gap))
    return obj


def stack(objs, axis="Z", gap=0.0, align_to="center"):
    """Puts objects one after another along axis (the first stays), centered on the first across the other axes.

        n.stack([base, column, cap], "Z")
    """
    objs = to_list(objs)
    ax = "XYZ".index(str(axis).upper().lstrip("+-"))
    sign = -1 if str(axis).startswith("-") else 1
    for prev, cur in zip(objs, objs[1:]):
        pb, cb = bounds(prev), bounds(cur)
        delta = Vector((0, 0, 0))
        for i in range(3):
            if i == ax:
                delta[i] = (pb.max[i] + gap - cb.min[i]) if sign > 0 else (pb.min[i] - gap - cb.max[i])
            elif align_to == "center":
                delta[i] = pb.center[i] - cb.center[i]
        move(cur, delta)
    return objs


def distribute(objs, axis="X", spacing=None, start=None):
    """Spaces objects evenly along axis: spacing = gap between them (meters), or between the first and last."""
    objs = to_list(objs)
    ax = "XYZ".index(str(axis).upper())
    bs = [bounds(o) for o in objs]
    if spacing is None:
        if len(objs) < 3:
            return objs
        total = bs[-1].max[ax] - bs[0].min[ax]
        sizes = sum(b.size[ax] for b in bs)
        spacing = (total - sizes) / (len(objs) - 1)
    pos = bs[0].min[ax] if start is None else float(start)
    for o, b in zip(objs, bs):
        delta = Vector((0, 0, 0))
        delta[ax] = pos - b.min[ax]
        move(o, delta)
        pos += b.size[ax] + spacing
    return objs


def ground(objs, z=0.0):
    """Puts objects (together) on the ground: their lowest point at z (default 0)."""
    objs = to_list(objs)
    b = bounds(objs)
    move(objs, (0, 0, z - b.min.z))
    return objs


def center(objs, axes="XY", at=(0, 0, 0)):
    """Centers objects (together) on at along the given axes."""
    objs = to_list(objs)
    b = bounds(objs)
    delta = Vector((0, 0, 0))
    for a in str(axes).upper():
        i = "XYZ".index(a)
        delta[i] = at[i] - b.center[i]
    move(objs, delta)
    return objs


def apply_transforms(objs, location=False, rotation=True, scale=True):
    """Bakes rotation / scale (and location) into the mesh, like Ctrl+A, without operators. Children keep place."""
    for o in to_list(objs):
        if o.type != "MESH":
            continue
        loc, rot, sca = o.matrix_basis.decompose()
        m = Matrix.Identity(4)
        if scale:
            m = Matrix.Diagonal(sca.to_4d()) @ m
        if rotation:
            m = rot.to_matrix().to_4x4() @ m
        if location:
            m = Matrix.Translation(loc) @ m
        if m == Matrix.Identity(4):
            continue
        if o.data.users > 1:
            o.data = o.data.copy()
        o.data.transform(m)
        basis = Matrix.Translation(Vector((0, 0, 0)) if location else loc) @ \
            (rot.to_matrix().to_4x4() if not rotation else Matrix.Identity(4)) @ \
            (Matrix.Diagonal(sca.to_4d()) if not scale else Matrix.Identity(4))
        for child in o.children:
            child.matrix_parent_inverse = m @ child.matrix_parent_inverse
        o.matrix_basis = basis
        o.data.update()
    core.update()
    return objs


def scale_to(objs, size, axis="max", ground_it=False):
    """Scales objects (together, around their center) so their size along axis ("x", "y", "z", "max") is size m,
    then applies the scale. For imported or generated models.

        n.scale_to(gen_mesh, 1.8, "z", ground_it=True)    # 1.8 m tall
    """
    objs = to_list(objs)
    b = bounds(objs)
    cur = max(b.size) if str(axis).lower() == "max" else b.size["xyz".index(str(axis).lower())]
    if cur <= 0:
        raise ValueError("scale_to: the objects have no size")
    f = float(size) / cur
    c = b.center
    for o in objs:
        if o.parent is not None and o.parent in objs:
            continue
        mw = o.matrix_world
        o.matrix_world = Matrix.Translation(c) @ Matrix.Scale(f, 4) @ Matrix.Translation(-c) @ mw
    core.update()
    apply_transforms(objs, location=False, rotation=False, scale=True)
    if ground_it:
        ground(objs)
    return objs


def set_origin(obj, where="bottom"):
    """Moves the object's origin without moving its mesh: "bottom" (center of the base), "center", "top", or (x, y, z).

        n.set_origin(lamp, "bottom")
    """
    obj = get(obj)
    b = bounds(obj, evaluated=False)
    if isinstance(where, str):
        c = b.center
        point = {"bottom": Vector((c.x, c.y, b.min.z)), "top": Vector((c.x, c.y, b.max.z)), "center": c}[where]
    else:
        point = Vector(where)
    local = obj.matrix_world.inverted() @ point
    obj.data.transform(Matrix.Translation(-local))
    obj.matrix_world = obj.matrix_world @ Matrix.Translation(local)
    for child in obj.children:
        child.matrix_parent_inverse = Matrix.Translation(-local) @ child.matrix_parent_inverse
    core.update()
    return obj
