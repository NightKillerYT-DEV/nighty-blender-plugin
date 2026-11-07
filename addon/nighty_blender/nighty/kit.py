# SPDX-License-Identifier: GPL-3.0-or-later
"""The detail kit: the secondary and tertiary detail that makes a model look finished. Bolt rows and rings, panel
seams, grilles, knurling, cables with clips, planks, corner brackets, nails, inset panels, stitching, emblem plates,
and stylized helpers (chunky bevels, tapers, cartoon outlines). All closed, quad-dominant, verify_mesh-clean.

    n.bolts_along((-0.1, -0.05, 0.12), (0.1, -0.05, 0.12), 5, radius=0.004, axis="-Y", name="FrontBolts")
    n.groove(hull, [(-0.2, -0.15, 0.1), (0.2, -0.15, 0.1)], width=0.002)
    boards = n.planks((0.6, 0.5), count=5, thickness=0.02, plane="XZ", at=(0, -0.3, 0.25))
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import core
from .core import get, to_list

__all__ = ["bolts_along", "bolts_around", "nails", "groove", "grille", "knurl", "cable", "planks",
           "corner_bracket", "inset", "stitches", "plate", "chamfer", "subd_crisp", "chunky", "taper", "outline"]


def _merge(parts, name):
    from .assemble import merge_parts
    return merge_parts(parts, name=name, weld=False) if len(parts) > 1 else parts[0]


def _finish(obj, material=None, parent=None):
    if material is not None:
        from .paint import paint
        paint(obj, material)
    if parent is not None:
        from .assemble import parent as set_parent
        set_parent(obj, parent)
    return obj


# ---------- fasteners ----------

def bolts_along(start, end, count, radius=0.004, kind="hex", axis="Z", washer=False, segments=None, name="Bolts",
                material=None, parent=None):
    """count bolt heads evenly from start to end (both included), standing on the surface and facing axis.

        n.bolts_along((-0.25, -0.2, 0.05), (0.25, -0.2, 0.05), 6, radius=0.005, axis="-Y")
    """
    from .details import bolt
    a, b = Vector(start), Vector(end)
    count = max(1, int(count))
    pts = [a.lerp(b, i / (count - 1)) if count > 1 else (a + b) / 2 for i in range(count)]
    parts = [bolt(radius, kind=kind, axis=axis, at=p, washer=washer, segments=segments, name=name) for p in pts]
    return _finish(_merge(parts, name), material, parent)


def bolts_around(center, ring_radius, count, radius=0.004, kind="hex", axis="Z", start_angle=0.0, washer=False,
                 segments=None, name="Bolts", material=None, parent=None):
    """count bolt heads on a circle (a flange, a hub) around center, in the plane facing axis.

        n.bolts_around((0, 0, 0.3), 0.09, 8, radius=0.006, axis="Z")
    """
    from .details import bolt
    d = core.axis_vector(axis)
    u = d.orthogonal().normalized()
    v = d.cross(u)
    c = Vector(center)
    parts = []
    for i in range(int(count)):
        t = math.radians(start_angle) + 2 * math.pi * i / count
        p = c + (u * math.cos(t) + v * math.sin(t)) * ring_radius
        parts.append(bolt(radius, kind=kind, axis=axis, at=p, washer=washer, segments=segments, name=name))
    return _finish(_merge(parts, name), material, parent)


def nails(points, radius=0.0035, axis="Z", segments=None, name="Nails", material=None, parent=None):
    """Flat round nail heads at surface points, facing axis (one object). Small heads (under 1 % of n.settings
    size) get 8 sides, about 30 triangles each: nobody counts a nail's sides in a game.

        n.nails([(x, -0.3, 0.1) for x in (-0.2, 0, 0.2)], axis="-Y")
    """
    from .shapes import dome
    if not segments and radius < 0.01 * float(core.settings()["size"]):
        segments = 8
    parts = [dome(radius, height=radius * 0.32, segments=segments, axis=axis, at=p, name=name) for p in points]
    return _finish(_merge(parts, name), material, parent)


# ---------- cuts: seams, grilles, knurling ----------

def groove(target, points, width=0.002, closed=False, apply=True):
    """A panel seam: a half-round groove along a path of points on target's surface (width meters).

        n.groove(body, [(-0.1, -0.02, 0.0), (0.1, -0.02, 0.0)], width=0.0015)
    """
    from .shapes import pipe
    from .modify import boolean_cut
    target = get(target)
    cutter = pipe(points, radius=width / 2.0, bend=width, caps="ngon", closed=closed, name=target.name + "_Seam")
    return boolean_cut(target, cutter, apply=apply)


def grille(target, side="-Y", center=None, size=(0.1, 0.06), count=6, bar=None, depth=None, radius=None,
           name="Grille", material=None):
    """A recessed opening with bars across it (vents, speaker grilles, intakes). Cuts target; returns the bars.

    side / center / size as n.panel_cut: (u, v) on that face (-Y / +Y: u = x, v = z). Bars run along u.

        bars = n.grille(body, "-Y", center=(0.05, 0.1), size=(0.12, 0.05), count=5)
    """
    from .modify import _side, _cutter_at, boolean_cut, bevel
    from .shapes import rounded_rect, box
    target = get(target)
    b, plane, ui, vi, idx, level, sign = _side(target, side)
    w, h = size
    cu, cv = center if center is not None else (b.center[ui], b.center[vi])
    depth = float(depth) if depth else max(0.004, min(w, h) * 0.18)
    r = min(w, h) * 0.18 if radius is None else float(radius)
    cutter = _cutter_at(rounded_rect(w, h, r, center=(cu, cv)), None, plane, idx, level, depth, target.name + "_Grille")
    boolean_cut(target, cutter)
    bar = float(bar) if bar else h / (count * 2.2)
    parts = []
    for k in range(int(count)):
        v = cv - h / 2.0 + (k + 0.5) * h / count
        pos = Vector((0, 0, 0))
        pos[ui], pos[vi] = cu, v
        pos[idx] = level - sign * (depth * 0.575 + 0.0002)   # standing on the floor of the recess
        dims = [0.0, 0.0, 0.0]
        dims[ui], dims[vi], dims[idx] = w - r * 0.6, bar, depth * 0.85
        slat = box(tuple(dims), at=tuple(pos), name=name)
        bevel(slat, width=min(bar, depth) * 0.2, segments=2)
        parts.append(slat)
    return _finish(_merge(parts, name), material)


def knurl(target, side="-Y", center=None, size=(0.04, 0.08), pitch=0.004, depth=0.0008, pattern="diamond",
          apply=True):
    """A grip texture cut into a flat side: pattern "diamond" (crossed grooves) or "lines". The part's edges are
    marked first, so a later n.bevel rounds them and leaves the knurling crisp.

        n.knurl(grip, "-Y", center=(-0.09, -0.07), size=(0.035, 0.07), pitch=0.0035)
    """
    from .modify import _side, boolean_cut, boolean_intersect, mark_bevel
    from .shapes import box, extrude, rounded_rect
    target = get(target)
    if not target.get("nighty_fine_cuts"):  # n.bevel will round the part's own edges only, not the knurling
        if not any(m.type == "BOOLEAN" for m in target.modifiers):
            mark_bevel(target)
        target["nighty_fine_cuts"] = True
    b, plane, ui, vi, idx, level, sign = _side(target, side)
    w, h = size
    cu, cv = center if center is not None else (b.center[ui], b.center[vi])
    span = math.hypot(w, h) * 1.2
    groove_w = pitch * 0.42
    angles = (45.0, -45.0) if pattern == "diamond" else (0.0,)
    for ang in angles:
        lines = []
        n_lines = int(span / pitch) + 1
        a = math.radians(ang)
        du = Vector((math.cos(a), math.sin(a)))      # along the line
        dn = Vector((-math.sin(a), math.cos(a)))     # across
        for k in range(n_lines):
            off = (k - (n_lines - 1) / 2.0) * pitch
            c2 = Vector((cu, cv)) + dn * off
            pts = []
            for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                p = c2 + du * (su * span / 2) + dn * (sv * groove_w / 2)
                pts.append((p.x, p.y))
            lines.append(extrude(pts, depth=depth * 2.0, plane=plane, name=target.name + "_Knurl"))
        cutter = _merge(lines, target.name + "_KnurlSet")
        loc = Vector((0, 0, 0))
        loc[idx] = level
        cutter.location = loc
        region = extrude(rounded_rect(w, h, min(w, h) * 0.12, center=(cu, cv)), depth=depth * 3.0, plane=plane,
                         name=target.name + "_KnurlArea")
        region.location = loc
        boolean_intersect(cutter, region)
        boolean_cut(target, cutter, apply=apply)
    return target


# ---------- cables, planks, brackets ----------

def cable(points, radius=0.006, sag=0.0, clips=0, clip_radius=None, segments=None, name="Cable", material=None,
          clip_material=None):
    """A cable / hose through points, hanging down by sag (a share of each span), with clips around it.

    Returns the cable (and makes "<name>Clips" when clips > 0).

        n.cable([(0, 0, 0.3), (0.3, 0, 0.32), (0.5, 0.1, 0.1)], radius=0.005, sag=0.12, clips=3)
    """
    from .shapes import pipe, spline, torus
    pts = [Vector(p) for p in points]
    path = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        if sag:
            mid = (a + b) / 2 - Vector((0, 0, (b - a).length * sag))
            path.append(mid)
        path.append(b)
    smooth = [Vector(p) for p in spline([tuple(p) for p in path], samples=8)] if len(path) > 2 else path
    obj = pipe([tuple(p) for p in smooth], radius=radius, bend=0.0, segments=segments, name=name, material=material)
    if clips:
        tube = radius * 0.5
        cr = clip_radius or radius + tube * 0.85   # the ring's inside presses on the cable
        total = sum((b - a).length for a, b in zip(smooth, smooth[1:]))
        parts = []
        for k in range(int(clips)):
            target_len = total * (k + 1) / (clips + 1)
            acc = 0.0
            for a, b in zip(smooth, smooth[1:]):
                seg = (b - a).length
                if acc + seg >= target_len:
                    t = (target_len - acc) / max(seg, 1e-9)
                    p = a.lerp(b, t)
                    parts.append(torus(cr, tube, axis=tuple((b - a).normalized()), at=tuple(p),
                                       name=name + "Clips"))
                    break
                acc += seg
        _finish(_merge(parts, name + "Clips"), clip_material or material)
    return obj


def planks(size=(0.6, 0.5), count=5, thickness=0.02, gap=0.005, plane="XZ", at=(0, 0, 0), bevel=None, jitter=0.0015,
           split=0, seed=0, name="Planks", material=None):
    """Boards side by side with gaps (along u, stacked along v of the plane, thickness along its normal), each a
    little different; split > 0 cuts some rows into two boards with a seam. One object, one island per board.

        front = n.planks((0.56, 0.56), count=4, thickness=0.018, plane="XZ", at=(0, -0.29, 0.3), split=1)
    """
    from .shapes import box
    from .modify import bevel as add_bevel
    rnd = random.Random(seed)
    w, h = size
    bh = (h - gap * (count - 1)) / count
    key = str(plane).upper()
    axes = {"XZ": (0, 2, 1), "XY": (0, 1, 2), "YZ": (1, 2, 0)}[key]
    ui, vi, ni = axes
    c = Vector(at)
    parts = []
    for k in range(int(count)):
        v = -h / 2 + bh / 2 + k * (bh + gap)
        cuts = [0.0]
        if split and rnd.random() < min(1.0, split * 0.6):
            cuts.append(rnd.uniform(-0.25, 0.25) * w)
        edges = [-w / 2] + sorted(cuts[1:]) + [w / 2]
        for e0, e1 in zip(edges, edges[1:]):
            g0 = gap / 2 if e0 > -w / 2 else 0.0
            g1 = gap / 2 if e1 < w / 2 else 0.0
            length = (e1 - e0) - g0 - g1 - rnd.uniform(0, jitter)
            dims = [0.0, 0.0, 0.0]
            dims[ui], dims[vi] = length, bh - rnd.uniform(0, jitter)
            dims[ni] = thickness * rnd.uniform(0.94, 1.0)
            pos = Vector((0, 0, 0))
            pos[ui] = (e0 + e1) / 2 + (g0 - g1) / 2
            pos[vi] = v + rnd.uniform(-jitter, jitter) * 0.3
            pos[ni] = (thickness - dims[ni]) / 2 * (1 if rnd.random() < 0.5 else -1)
            board = box(tuple(dims), at=tuple(c + pos), name=name)
            add_bevel(board, width=bevel or min(thickness, bh) * 0.12, segments=2)
            parts.append(board)
    return _finish(_merge(parts, name), material)


def corner_bracket(target, corner=(1, -1, 1), size=0.08, thickness=0.004, nails_per_face=1, nail_radius=None,
                   name="Bracket", material=None, nail_material=None):
    """A metal corner piece wrapping one corner of target's bounds (three faces), nailed on each face.

    corner: (+-1, +-1, +-1) which corner. Returns the bracket (nails become "<name>Nails").

        n.corner_bracket(crate, (1, -1, 1), size=0.09, material=iron)
    """
    from .shapes import box
    from .modify import boolean_cut, bevel
    target = get(target)
    b = core.bounds(target)
    sx, sy, sz = [1.0 if c > 0 else -1.0 for c in corner]
    p = Vector((b.max.x if sx > 0 else b.min.x, b.max.y if sy > 0 else b.min.y, b.max.z if sz > 0 else b.min.z))
    s, t = float(size), float(thickness)
    sign = Vector((sx, sy, sz))
    lo = p - Vector((sx * s, sy * s, sz * s))
    hi = p + sign * t
    center = (lo + hi) / 2
    outer = box(tuple(abs(c) for c in (hi - lo)), at=tuple(center), name=name)
    inner = box(tuple(b.size), at=tuple(b.center), name=name + "_cut")
    boolean_cut(outer, inner)
    bevel(outer, width=t * 0.45, segments=2)
    _finish(outer, material)
    if nails_per_face:
        r = nail_radius or s * 0.07
        pts = []
        for axis in range(3):
            n_dir = Vector((0, 0, 0))
            n_dir[axis] = sign[axis]
            others = [i for i in range(3) if i != axis]
            for k in range(int(nails_per_face)):
                q = p.copy()
                q[axis] = p[axis] + sign[axis] * t
                f = 0.5 if nails_per_face == 1 else 0.3 + 0.4 * k / max(1, nails_per_face - 1)
                q[others[0]] = p[others[0]] - sign[others[0]] * s * f
                q[others[1]] = p[others[1]] - sign[others[1]] * s * (0.5 if nails_per_face == 1 else 1 - f)
                pts.append((tuple(q), tuple(n_dir)))
        heads = [nails([q], radius=r, axis=d, name=name + "Nails") for q, d in pts]
        _finish(_merge(heads, name + "Nails"), nail_material or material)
    return outer


# ---------- surface detail ----------

def inset(obj, side="+Z", amount=0.01, depth=-0.003, min_dot=0.995):
    """Insets the faces facing side (a border of amount meters) and pushes the inner part out (depth > 0) or in
    (depth < 0): raised or sunk panels on boxes, lids, plates. Changes the mesh.

        n.inset(lid, "+Z", amount=0.015, depth=-0.004)
    """
    obj = get(obj)
    d = core.axis_vector(side)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    faces = [f for f in bm.faces if f.normal.dot(d) >= min_dot]
    if not faces:
        bm.free()
        raise ValueError(f"inset: no faces of {obj.name} face {side}")
    res = bmesh.ops.inset_region(bm, faces=faces, thickness=float(amount), depth=0.0, use_even_offset=True)
    verts = {v for f in faces for v in f.verts}
    bmesh.ops.translate(bm, vec=d * float(depth), verts=list(verts))
    bm.normal_update()
    rim = res.get("faces", [])
    if any(f.normal.dot(d) < 0.0 for f in rim) or any(f.normal.dot(d) < 0.5 for f in faces):
        bm.free()  # the border folded over a rounded corner smaller than amount: leave the mesh as it was
        raise ValueError(f"inset: amount {amount} is larger than a rounded corner of {obj.name}; use a smaller one")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    from .modify import _reshade
    _reshade(obj)
    return obj


def stitches(points, length=0.006, gap=0.004, radius=0.0011, name="Stitches", material=None, parent=None):
    """Thread stitches along a path on a surface (leather wraps, pouches, seats): little capsules, half sunk.

        n.stitches([(-0.04, -0.016, -0.03), (-0.06, -0.016, -0.11)], length=0.005)
    """
    from .shapes import capsule
    pts = [Vector(p) for p in points]
    parts = []
    for a, b in zip(pts, pts[1:]):
        seg = (b - a).length
        step = length + gap
        n_st = max(1, int(seg / step))
        d = (b - a).normalized()
        for k in range(n_st):
            c = a + d * (gap / 2 + length / 2 + k * step)
            parts.append(capsule(radius, length, segments=8, axis=tuple(d), at=tuple(c), name=name))
    return _finish(_merge(parts, name), material, parent)


def plate(size=(0.08, 0.04), thickness=0.003, text=None, rim=None, axis="-Y", at=(0, 0, 0), name="Plate",
          material=None, text_material=None):
    """An emblem / name plate: a rounded plate with a raised rim and optional raised text, facing axis.

        n.plate((0.09, 0.035), text="NIGHTY", axis="-Y", at=(0, -0.301, 0.4))
    """
    from .shapes import extrude, rounded_rect
    from .details import text3d
    from .modify import bevel
    w, h = size
    r = min(w, h) * 0.2
    rim = rim if rim is not None else min(w, h) * 0.08
    base = extrude(rounded_rect(w, h, r), depth=thickness, plane="XY", at=(0, 0, thickness / 2), name=name)
    ring = extrude(rounded_rect(w, h, r), holes=[rounded_rect(w - 2 * rim, h - 2 * rim, max(r - rim, 0.0))],
                   depth=thickness * 0.6, plane="XY", at=(0, 0, thickness * 1.3 - 1e-5), name=name)
    bevel(base, width=thickness * 0.25, segments=2)
    bevel(ring, width=thickness * 0.15, segments=2)
    parts = [base, ring]
    obj = _merge(parts, name)
    _finish(obj, material)
    turn = core.axis_matrix(axis)
    obj.data.transform(turn)
    obj.location = Vector(at)
    if text:
        size_t = (h - 2 * rim) * 0.55
        label = text3d(text, size=size_t, depth=thickness * 0.5, axis="Z", at=(0, 0, thickness + thickness * 0.2),
                       bevel=0, name=name + "Text")
        label.data.transform(turn)
        label.location = Vector(at)
        _finish(label, text_material or material)
    return obj


# ---------- shape helpers (crisp / stylized) ----------

def chamfer(obj, width=None):
    """A flat 45-degree chamfer on the sharp edges (one segment, weighted normals): hard industrial edges."""
    from .modify import bevel
    return bevel(obj, width=width, segments=1)


def subd_crisp(obj, width=None, levels=2):
    """Smooth subdivision with tight support loops on the sharp edges: soft shapes with crisp highlights."""
    from .modify import bevel, subdivide
    mod = bevel(obj, width=width, segments=2, profile=1.0)
    subdivide(obj, levels)
    return mod


def chunky(obj, amount=1.0, segments=4):
    """Stylized chunky edges: a big, soft bevel (about 7 % of the part's smallest side x amount). segments 2 for
    small parts in a tight triangle budget."""
    from .modify import bevel
    obj = get(obj)
    core.update()
    dims = [d for d in obj.dimensions if d > 1e-6] or [0.1]
    return bevel(obj, width=min(dims) * 0.07 * amount, segments=int(segments), profile=0.55)


def taper(obj, amount=0.3, axis="Z"):
    """Narrows the part toward the +axis end (amount 0..1; negative widens). Stylized shapes, legs, handles."""
    from .modify import deform
    return deform(obj, "taper", amount, axis, apply=True)


def outline(obj, thickness=None, color=(0.02, 0.02, 0.03)):
    """A cartoon outline: an inverted shell (its own object tagged "outline", parented to obj, a snapshot of the
    current shape). Renders in Cycles and EEVEE; verify_mesh skips it, look draws it with its object.

        n.outline(chest, 0.004)
    """
    from . import compat
    obj = get(obj)
    core.update()
    t = thickness or max(obj.dimensions) * 0.006
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bm.normal_update()
    for v in bm.verts:
        v.co = v.co + v.normal * t
    bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.name = obj.name + "Outline"
    shell = bpy.data.objects.new(obj.name + "Outline", me)
    for c in obj.users_collection:
        c.objects.link(shell)
    shell.matrix_world = obj.matrix_world.copy()
    mat = bpy.data.materials.get("Nighty Outline") or bpy.data.materials.new("Nighty Outline")
    tree = compat.ensure_nodes(mat)
    for n_ in list(tree.nodes):
        tree.nodes.remove(n_)
    out = tree.nodes.new("ShaderNodeOutputMaterial")
    geo = tree.nodes.new("ShaderNodeNewGeometry")
    mix = tree.nodes.new("ShaderNodeMixShader")
    ink = tree.nodes.new("ShaderNodeEmission")
    ink.inputs["Color"].default_value = tuple(color) + (1.0,)
    see = tree.nodes.new("ShaderNodeBsdfTransparent")
    tree.links.new(geo.outputs["Backfacing"], mix.inputs[0])
    tree.links.new(ink.outputs[0], mix.inputs[1])
    tree.links.new(see.outputs[0], mix.inputs[2])
    tree.links.new(mix.outputs[0], out.inputs["Surface"])
    compat.set_transparent(mat, blended=False)
    mat.use_backface_culling = True
    mat.diffuse_color = tuple(color) + (1.0,)
    me.materials.clear()
    me.materials.append(mat)
    compat.shade_smooth(me)
    for ray in ("visible_shadow", "visible_diffuse", "visible_glossy", "visible_transmission",
                "visible_volume_scatter"):
        if hasattr(shell, ray):
            setattr(shell, ray, False)  # only the camera sees the outline (no shadows or reflections)
    shell["nighty_role"] = "outline"
    mw = shell.matrix_world.copy()
    shell.parent = obj
    shell.matrix_world = mw
    core.update()
    return shell
