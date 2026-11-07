# SPDX-License-Identifier: GPL-3.0-or-later
"""Finishing and editing: bevels with weighted normals, smoothing, mirror, arrays, booleans, panel cuts, vents.

Modifiers are kept in a working order: shape makers (mirror, array, boolean, solidify, deform) first, then
Bevel, then Subdivision, then Weighted Normal last. apply=True bakes a step into the mesh.
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import compat, core
from .core import get, to_list

__all__ = ["bevel", "mark_bevel", "weighted_normals", "smooth_by_angle", "shade_flat", "mirror", "array", "radial",
           "subdivide", "solidify", "displace", "deform", "boolean_cut", "boolean_union", "boolean_intersect",
           "hole", "panel_cut", "vents", "apply_modifiers", "cleanup", "is_manifold"]

_ORDER = {"BEVEL": 1, "WELD": 1.5, "SUBSURF": 2, "MULTIRES": 2, "WEIGHTED_NORMAL": 3, "NODES": 3}


def _rank(mod):
    if mod.type == "NODES":
        group = getattr(mod, "node_group", None)
        return 3 if group and "smooth" in group.name.lower() else 0
    return _ORDER.get(mod.type, 0)


def _order(obj):
    mods = list(obj.modifiers)
    want = sorted(range(len(mods)), key=lambda i: (_rank(mods[i]), i))
    for target, src in enumerate(want):
        name = mods[src].name
        cur = list(obj.modifiers).index(obj.modifiers[name])
        if cur != target:
            obj.modifiers.move(cur, target)


def _reshade(obj):
    """Smooth shading policy: with a bevel modifier everything is smooth (normals do the rest), else sharp by angle."""
    if obj.type != "MESH":
        return
    angle = float(obj.get("nighty_smooth", 30.0))
    if any(m.type == "BEVEL" for m in obj.modifiers):
        compat.shade_smooth(obj.data, angle=180.0)
    elif angle > 0:
        compat.shade_smooth(obj.data, angle=angle)


def _default_width(obj):
    core.update()  # dimensions are stale right after making or editing an object
    dims = [d for d in obj.dimensions if d > 1e-6] or [0.1]
    size = core.settings()["size"]
    return max(0.0002, min(0.04 * min(dims), 0.008 * size))


# ---------- shading ----------

def _bevel_problems(obj):
    """Overlapping faces, faces with no area and doubled points the current modifiers make (inside each piece)."""
    from . import check
    import numpy as np
    m = check._Mesh(obj, True)
    if not len(m.tris):
        return 0
    labels = check._components(m.nv, m.edges)
    _, inv = np.unique(labels, return_inverse=True)
    inv = inv.ravel()
    diag = check._diag(m.co)
    q = np.round(m.local / max(diag * 1e-6, 1e-9)).astype(np.int64)
    dups = m.nv - len(np.unique(np.column_stack([inv, q]), axis=0))
    t = m.tris
    tri_area = 0.5 * np.linalg.norm(np.cross(m.co[t[:, 1]] - m.co[t[:, 0]], m.co[t[:, 2]] - m.co[t[:, 0]]), axis=1)
    poly_area = np.bincount(m.tri_poly, weights=tri_area, minlength=len(m.loop_start))
    flat = int((poly_area < (diag * 1e-6) ** 2).sum())
    crossing = check._self_intersections(m, inv) if len(m.tris) <= check.SKIP_INTERSECT_FACES else 0
    return dups + flat + crossing


def bevel(obj, width=None, segments=None, angle=30.0, profile=0.5, harden=True, weighted=True, limit="auto",
          clamp=True, safe=True):
    """Rounded edges the hard-surface way: Bevel (angle limit, harden normals) + Weighted Normal, smooth shading.

    width: meters (default from the part's size). segments: default from the detail level (even = quad corners);
    a bevel too narrow to show (under 1/1000 of n.settings size) gets 1, under 2.5/1000 at most 2 (game triangles
    go where they read).
    limit: "angle" (edges sharper than angle), "weight" (edges marked with n.mark_bevel), "auto" (weight when the
    part had fine cuts like knurling made after marking, else angle).
    safe: when the bevel would make faces overlap (wider than a groove or a small rounded corner), the width is
    lowered until it doesn't (the modifier's width tells what was used). Calling it again updates the same bevel;
    booleans and mirrors added later still go before it.

        n.bevel(receiver, width=0.0015)
    """
    obj = get(obj)
    if width is None:
        width = _default_width(obj)
    mod = obj.modifiers.get("Bevel") or obj.modifiers.new("Bevel", "BEVEL")
    mod.width = float(width)
    segs = int(segments or core.bevel_segments())
    if not segments:
        px = float(width) / max(1e-6, float(core.settings()["size"])) * 1000.0  # its width in a 1000 px view
        segs = 1 if px < 1.0 else min(segs, 2) if px < 2.5 else segs
    mod.segments = segs
    if str(limit).lower() == "auto":
        limit = "weight" if obj.get("nighty_fine_cuts") else "angle"
    mod.limit_method = {"angle": "ANGLE", "weight": "WEIGHT", "none": "NONE"}.get(str(limit).lower(), "ANGLE")
    mod.angle_limit = math.radians(angle)
    mod.profile = profile
    mod.harden_normals = bool(harden)
    mod.use_clamp_overlap = bool(clamp)
    mod.miter_outer = "MITER_ARC"
    weld = obj.modifiers.get("BevelWeld") or obj.modifiers.new("BevelWeld", "WELD")  # merges points bevels that
    weld.mode = "CONNECTED"                                                       # meet leave doubled (when it
    weld.merge_threshold = 1e-6                                                   # helps: see safe below)
    if weighted:
        weighted_normals(obj)
    _order(obj)
    _reshade(obj)
    if safe and obj.type == "MESH":
        mod.show_viewport = weld.show_viewport = False
        core.update()
        base = _bevel_problems(obj)
        mod.show_viewport = True

        def problems(welded):
            weld.show_viewport = weld.show_render = welded
            core.update()
            return _bevel_problems(obj)
        best = None
        for _ in range(6):  # without the weld, with it, then a narrower bevel
            found = False
            for welded in (False, True):
                p = problems(welded)
                if best is None or p < best[0]:
                    best = (p, mod.width, welded)
                if p <= base:
                    found = True
                    break
            if found:
                break
            mod.width = mod.width * 0.6
        if best[0] > base:  # nothing was clean: keep the least bad one and say so
            mod.width = best[1]
            weld.show_viewport = weld.show_render = best[2]
            obj["nighty_bevel_note"] = ("this bevel leaves bad faces; mark the big edges with n.mark_bevel before "
                                        "small cuts, then n.bevel(..., limit='weight')")
        obj["nighty_bevel_width"] = float(mod.width)
    else:
        weld.show_viewport = weld.show_render = False
    return mod


def mark_bevel(obj, angle=30.0, weight=1.0, clear=True):
    """Gives the edges sharper than angle a bevel weight, so n.bevel(obj, limit="weight") bevels only them.
    Mark the big edges first, cut small details after: the details stay crisp. Returns how many were marked.

        n.mark_bevel(blade); n.boolean_cut(blade, fuller); n.bevel(blade, width=0.002, limit="weight")
    """
    obj = get(obj)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    layer = bm.edges.layers.float.get("bevel_weight_edge") or bm.edges.layers.float.new("bevel_weight_edge")
    limit = math.radians(angle)
    count = 0
    for e in bm.edges:
        if e.is_manifold and e.calc_face_angle(0.0) >= limit:
            e[layer] = float(weight)
            count += 1
        elif clear:
            e[layer] = 0.0
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return count


def weighted_normals(obj, weight=50, keep_sharp=True):
    """Weighted Normal modifier (last in the stack): flat faces shade flat, bevels shade round."""
    obj = get(obj)
    mod = obj.modifiers.get("WeightedNormal") or obj.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
    mod.weight = int(weight)
    mod.keep_sharp = bool(keep_sharp)
    mod.mode = "FACE_AREA"
    _order(obj)
    return mod


def smooth_by_angle(obj, angle=30.0):
    """Smooth shading with edges sharper than angle (degrees) kept sharp (Blender 4.1+ replacement of auto smooth)."""
    for o in to_list(obj):
        o["nighty_smooth"] = float(angle)
        if o.type == "MESH":
            compat.shade_smooth(o.data, angle=angle)
    return obj


def shade_flat(obj):
    """Flat shading (faceted look for stylized low poly)."""
    for o in to_list(obj):
        o["nighty_smooth"] = 0.0
        if o.type == "MESH":
            compat.shade_flat(o.data)
    return obj


# ---------- shape modifiers ----------

def _axis_index(axis):
    return "XYZ".index(str(axis).upper().lstrip("+-"))


def mirror(obj, axis="X", bisect=False, merge=True, clip=True, about=None, apply=False):
    """Mirror across the object's own axis (or another object's): model one half, get both.

        n.mirror(half_body, "X", bisect=True)
    """
    obj = get(obj)
    mod = obj.modifiers.new("Mirror", "MIRROR")
    idx = _axis_index(axis)
    mod.use_axis = [i == idx for i in range(3)]
    mod.use_bisect_axis = [bisect and i == idx for i in range(3)]
    mod.use_clip = bool(clip)
    mod.use_mirror_merge = bool(merge)
    mod.merge_threshold = 1e-5
    if about is not None:
        mod.mirror_object = get(about)
    _order(obj)
    if apply:
        apply_modifiers(obj, upto=mod.name)
    return mod


def array(obj, count, offset=(0.1, 0, 0), merge=False, apply=False):
    """Copies in a row: offset is the step in meters (x, y, z). merge welds touching copies.

        n.array(slat, 6, offset=(0, 0.08, 0))
    """
    obj = get(obj)
    mod = obj.modifiers.new("Array", "ARRAY")
    mod.count = int(count)
    mod.use_relative_offset = False
    mod.use_constant_offset = True
    mod.constant_offset_displace = Vector(offset)
    mod.use_merge_vertices = bool(merge)
    mod.merge_threshold = 1e-5
    _order(obj)
    if apply:
        apply_modifiers(obj, upto=mod.name)
    return mod


def radial(obj, count, axis="Z", center=None, angle=360.0, weld=False):
    """Copies around an axis, joined into the same mesh (bolts on a flange, gear teeth, barrel staves).

    center: world point the axis goes through (default the world origin). The object's mesh is changed.

        n.radial(bolt, 8, axis="Y", center=flange.location)
    """
    obj = get(obj)
    core.update()
    inv = obj.matrix_world.inverted()
    c_local = inv @ Vector(center if center is not None else (0, 0, 0))
    ax_local = (inv.to_3x3() @ core.axis_vector(axis)).normalized()
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    base = list(bm.verts) + list(bm.edges) + list(bm.faces)
    full = angle >= 359.999
    steps = int(count)
    for k in range(1, steps):
        a = math.radians(angle) * k / (steps if full else max(1, steps - 1))
        dup = bmesh.ops.duplicate(bm, geom=base)
        verts = [g for g in dup["geom"] if isinstance(g, bmesh.types.BMVert)]
        bmesh.ops.rotate(bm, cent=c_local, matrix=Matrix.Rotation(a, 3, ax_local), verts=verts)
    if weld:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    _reshade(obj)
    return obj


def subdivide(obj, levels=2, render_levels=None):
    """Subdivision Surface (Catmull-Clark). Use with quads and bevels as support loops."""
    obj = get(obj)
    mod = obj.modifiers.get("Subdivision") or obj.modifiers.new("Subdivision", "SUBSURF")
    mod.levels = int(levels)
    mod.render_levels = int(render_levels if render_levels is not None else levels)
    _order(obj)
    compat.shade_smooth(obj.data, angle=180.0)
    return mod


def solidify(obj, thickness=0.01, offset=-1.0, apply=False):
    """Gives a surface thickness (meters). offset -1 grows inward, 1 outward."""
    obj = get(obj)
    mod = obj.modifiers.new("Solidify", "SOLIDIFY")
    mod.thickness = float(thickness)
    mod.offset = float(offset)
    mod.use_even_offset = True
    _order(obj)
    if apply:
        apply_modifiers(obj, upto=mod.name)
    return mod


def displace(obj, strength=0.05, scale=1.0, octaves=4, seed=0, roughness=0.5):
    """Bumps the surface along its normals with fractal noise (rocks, ground, bark). Changes the mesh.

    strength: meters at most; scale: size of the bumps in meters.

        n.displace(rock, strength=0.06, scale=0.35, seed=3)
    """
    from mathutils import noise
    obj = get(obj)
    me = obj.data
    me.update()
    offset = Vector((seed * 17.31, seed * 5.77, seed * 11.13))
    freq = 1.0 / max(1e-6, float(scale))
    for v in me.vertices:
        p = v.co * freq + offset
        h = noise.fractal(p, roughness, 2.0, int(octaves), noise_basis="PERLIN_ORIGINAL")
        v.co = v.co + v.normal * (h * strength)
    me.update()
    _reshade(obj)
    return obj


def deform(obj, kind="taper", amount=0.3, axis="Z", apply=False):
    """Simple Deform: kind "taper" | "bend" | "twist" | "stretch". amount: factor, or degrees for bend / twist."""
    obj = get(obj)
    mod = obj.modifiers.new("Deform", "SIMPLE_DEFORM")
    mod.deform_method = str(kind).upper()
    if mod.deform_method in ("BEND", "TWIST"):
        mod.angle = math.radians(amount)
    else:
        mod.factor = float(amount)
    mod.deform_axis = str(axis).upper().lstrip("+-")
    _order(obj)
    if apply:
        apply_modifiers(obj, upto=mod.name)
    return mod


# ---------- apply and clean ----------

def apply_modifiers(obj, upto=None):
    """Bakes modifiers into the mesh: all of them, or those up to and including the one named upto."""
    obj = get(obj)
    mods = list(obj.modifiers)
    if not mods:
        return obj
    idx = len(mods) - 1 if upto is None else [m.name for m in mods].index(upto)
    later = mods[idx + 1:]
    shown = [m.show_viewport for m in later]
    for m in later:
        m.show_viewport = False
    try:
        core.update()
        dg = bpy.context.evaluated_depsgraph_get()
        new = bpy.data.meshes.new_from_object(obj.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    finally:
        for m, s in zip(later, shown):
            m.show_viewport = s
    old = obj.data
    new.name = old.name
    if len(new.materials) and all(m is None for m in new.materials):
        new.materials.clear()  # no empty slot left behind (a later materials.append would land in slot 2)
    obj.data = new
    for m in mods[:idx + 1]:
        obj.modifiers.remove(m)
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return obj


def _fix_slivers(bm, area_eps, rounds=4):
    """Faces with no area (three points on a line, left where booleans cross): removed, and the point in the middle
    is joined into the long edge next to it, so the surface stays closed. Returns how many were fixed."""
    fixed = 0
    for _ in range(rounds):
        bad = [f for f in bm.faces if f.calc_area() <= area_eps]
        if not bad:
            break
        quads = [f for f in bad if len(f.verts) > 3]
        if quads:
            bmesh.ops.triangulate(bm, faces=quads)
            continue
        for f in bad:
            if not f.is_valid or len(f.verts) != 3:
                continue
            vs = list(f.verts)
            a, b_, m = max(((vs[0], vs[1], vs[2]), (vs[1], vs[2], vs[0]), (vs[2], vs[0], vs[1])),
                           key=lambda t: (t[0].co - t[1].co).length)
            long_edge = bm.edges.get((a, b_))
            length = (b_.co - a.co).length
            if long_edge is None or length < 1e-12:
                continue
            fac = min(max((m.co - a.co).length / length, 1e-4), 1 - 1e-4)
            bmesh.ops.delete(bm, geom=[f], context="FACES_ONLY")
            _, new_v = bmesh.utils.edge_split(long_edge, a, fac)
            bmesh.ops.pointmerge(bm, verts=[new_v, m], merge_co=m.co)
            fixed += 1
    return fixed


def cleanup(obj, merge=None, loose=True, normals=True):
    """Welds doubles, removes degenerate faces and loose bits, fixes normals. Returns what changed.

        n.cleanup(part)   # after imports or hand edits
    """
    obj = get(obj)
    me = obj.data
    core.update()
    dims = max(obj.dimensions) if max(obj.dimensions) > 0 else 1.0
    dist = float(merge) if merge is not None else max(1e-7, dims * 1e-5)
    bm = bmesh.new()
    bm.from_mesh(me)
    v0, f0 = len(bm.verts), len(bm.faces)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
    bmesh.ops.dissolve_degenerate(bm, dist=dist, edges=bm.edges)
    slivers = _fix_slivers(bm, (dims * 3e-6) ** 2)
    removed = 0
    if loose:
        lv = [v for v in bm.verts if not v.link_faces]
        le = [e for e in bm.edges if not e.link_faces]
        removed = len(lv) + len(le)
        if le:
            bmesh.ops.delete(bm, geom=le, context="EDGES")
        lv = [v for v in bm.verts if not v.link_faces]
        if lv:
            bmesh.ops.delete(bm, geom=lv, context="VERTS")
    if normals:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    out = {"verts_removed": v0 - len(bm.verts), "faces_removed": f0 - len(bm.faces), "loose_removed": removed,
           "slivers_fixed": slivers}
    bm.to_mesh(me)
    bm.free()
    me.update()
    return out


def is_manifold(obj, evaluated=True):
    """True when every edge has exactly two faces (a closed, watertight surface)."""
    from . import check
    rep = check.mesh_stats(get(obj), evaluated=evaluated)
    return rep["non_manifold_edges"] == 0 and rep["boundary_edges"] == 0


# ---------- booleans ----------

def _hide_cutter(cutter, target):
    cutter["nighty_role"] = "cutter"
    cutter.display_type = "WIRE"
    cutter.hide_render = True
    try:
        cutter.visible_shadow = False
        cutter.visible_camera = False
    except AttributeError:
        pass
    if cutter.parent is None and target is not None:
        mw = cutter.matrix_world.copy()
        cutter.parent = target
        cutter.matrix_world = mw


def _delete(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0 and isinstance(data, bpy.types.Mesh):
        bpy.data.meshes.remove(data)


def _solver(name, target, cutters):
    key = str(name).lower()
    if key != "auto":
        return compat.boolean_solver(key)
    big = len(target.data.polygons) > 20000
    if big and "MANIFOLD" in compat.boolean_solvers():
        if all(is_manifold(o, evaluated=False) for o in [target] + cutters):
            return "MANIFOLD"
    return "EXACT"


def boolean_cut(target, cutter, op="difference", solver="auto", apply=True, keep_cutter=False, cleanup_after=True):
    """Boolean with cleanup. op "difference" (cut), "union", "intersect". solver "auto" | "exact" | "fast" | "manifold".

    apply=True bakes it (the cutter is deleted unless keep_cutter); apply=False keeps a live modifier and turns the
    cutter into a hidden wire helper. Check the result with n.is_manifold().

        slot = n.box((0.05, 0.1, 0.01), at=(0.1, 0, 0.04))
        n.boolean_cut(receiver, slot)
    """
    target = get(target)
    cutters = to_list(cutter)
    solver_id = _solver(solver, target, cutters)
    for c in cutters:
        mod = target.modifiers.new("Boolean", "BOOLEAN")
        mod.operation = {"difference": "DIFFERENCE", "cut": "DIFFERENCE", "union": "UNION",
                         "intersect": "INTERSECT"}.get(str(op).lower(), str(op).upper())
        mod.object = c
        mod.solver = solver_id
        _order(target)
        if apply:
            apply_modifiers(target, upto=mod.name)
            if keep_cutter:
                _hide_cutter(c, None)
            else:
                _delete(c)
        else:
            _hide_cutter(c, target)
    if apply:
        if cleanup_after:
            cleanup(target)
        _reshade(target)
    return target


def boolean_union(target, other, solver="auto", apply=True):
    """Fuses other into target (one watertight shell)."""
    return boolean_cut(target, other, op="union", solver=solver, apply=apply)


def boolean_intersect(target, other, solver="auto", apply=True):
    """Keeps only where target and other overlap."""
    return boolean_cut(target, other, op="intersect", solver=solver, apply=apply)


def hole(target, radius, at=None, axis="Z", depth=None, segments=None, apply=True):
    """Drills a round hole through (or depth meters into) target, along axis, centered at the world point at.

        n.hole(plate, 0.004, at=(0.05, 0, 0.1), axis="Y")
    """
    from .shapes import cylinder
    target = get(target)
    b = core.bounds(target)
    at = Vector(at) if at is not None else b.center
    idx = _axis_index(axis)
    span = b.size[idx]
    if depth is None:
        length = span * 1.5 + radius
        center = at.copy()
        center[idx] = b.center[idx]
    else:
        length = float(depth) * 2.0
        center = at.copy()
    cutter = cylinder(radius, length, segments=segments or core.segments(radius) , axis=axis, at=center,
                      name=target.name + "_Hole")
    return boolean_cut(target, cutter, apply=apply)


_SIDES = {"X": ("YZ", 1, 2), "Y": ("XZ", 0, 2), "Z": ("XY", 0, 1)}


def _side(target, side):
    s = str(side).upper()
    sign = -1.0 if s.startswith("-") else 1.0
    axis = s.lstrip("+-")
    if axis not in _SIDES:
        raise ValueError('side must be one of "+X", "-X", "+Y", "-Y", "+Z", "-Z"')
    b = core.bounds(target)
    plane, ui, vi = _SIDES[axis]
    idx = "XYZ".index(axis)
    level = b.max[idx] if sign > 0 else b.min[idx]
    return b, plane, ui, vi, idx, level, sign


def _cutter_at(outline, holes, plane, idx, level, depth, name):
    from .shapes import extrude
    cutter = extrude(outline, depth=depth * 2.0, plane=plane, holes=holes, name=name)
    loc = Vector((0, 0, 0))
    loc[idx] = level
    cutter.location = loc
    return cutter


def panel_cut(target, side="-Y", center=None, size=(0.1, 0.1), groove=None, depth=None, radius=None,
              shape="rect", apply=True):
    """Cuts a panel line (a thin groove around a rectangle or circle) into a flat side of target.

    side: "+X" ... "-Z" (the face of the bounds it goes on). center: (u, v) world position on that face
    (-Y / +Y: (x, z); -X / +X: (y, z); -Z / +Z: (x, y)); default the face's middle. size: (width, height) or a
    diameter for shape="circle". groove / depth: meters (default from the asset size).

        n.panel_cut(hull, "-Y", center=(0.05, 0.12), size=(0.12, 0.06), radius=0.008)
    """
    from .shapes import rounded_rect, circle_points
    target = get(target)
    b, plane, ui, vi, idx, level, sign = _side(target, side)
    size_m = core.settings()["size"]
    groove = float(groove) if groove else max(0.0006, 0.003 * size_m)
    depth = float(depth) if depth else groove
    cu, cv = center if center is not None else (b.center[ui], b.center[vi])
    if str(shape).lower() == "circle":
        d = size if isinstance(size, (int, float)) else size[0]
        outer = circle_points(d / 2.0, center=(cu, cv))
        inner = circle_points(d / 2.0 - groove, count=len(outer), center=(cu, cv))
    else:
        w, h = size
        r = min(w, h) * 0.12 if radius is None else float(radius)
        outer = rounded_rect(w, h, r, center=(cu, cv))
        inner = rounded_rect(w - 2 * groove, h - 2 * groove, max(r - groove, 0.0), center=(cu, cv))
    cutter = _cutter_at(outer, [inner], plane, idx, level, depth, target.name + "_Panel")
    return boolean_cut(target, cutter, apply=apply)


def vents(target, side="-Y", center=None, count=5, slot=(0.06, 0.008), gap=None, depth=None, direction="v",
          apply=True):
    """Cuts a row of rounded slots into a flat side (vents, serrations, M-LOK slots).

    slot: (size along u, size along v) of one slot in meters (u / v as in panel_cut: -Y / +Y face: u = x, v = z).
    direction: "v" stacks the slots along v, "u" lines them up along u. gap: space between slots.

        n.vents(cover, "+Z", center=(0, 0.02), count=6, slot=(0.08, 0.008))            # stacked vent slots
        n.vents(slide, "-Y", center=(-0.08, 0.026), count=6, slot=(0.004, 0.03), direction="u")   # serrations
    """
    from .shapes import rounded_rect
    from .assemble import merge_parts
    target = get(target)
    b, plane, ui, vi, idx, level, sign = _side(target, side)
    su, sv = float(slot[0]), float(slot[1])
    along_v = str(direction).lower() == "v"
    thin = sv if along_v else su
    gap = float(gap) if gap else thin * 1.2
    depth = float(depth) if depth else max(min(su, sv) * 0.6, 0.002)
    cu, cv = center if center is not None else (b.center[ui], b.center[vi])
    step = thin + gap
    parts = []
    for k in range(int(count)):
        off = (k - (count - 1) / 2.0) * step
        c = (cu, cv + off) if along_v else (cu + off, cv)
        outline = rounded_rect(su, sv, min(su, sv) * 0.499, center=c)
        parts.append(_cutter_at(outline, None, plane, idx, level, depth, target.name + "_Vent"))
    cutter = merge_parts(parts, name=target.name + "_Vents", weld=False) if len(parts) > 1 else parts[0]
    return boolean_cut(target, cutter, apply=apply)
