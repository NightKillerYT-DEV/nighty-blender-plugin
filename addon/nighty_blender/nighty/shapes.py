# SPDX-License-Identifier: GPL-3.0-or-later
"""Shapes with clean topology: enough sides for their size, quads where it matters, transforms applied.

Every shape is centered on `at` (meters), keeps rotation in the object (`rot`, degrees) and scale 1, is smooth
shaded with edges sharper than 30 degrees kept sharp, and takes name=, material=, collection=, parent=.
`axis` ("X", "Y", "Z", "-X"... or a direction (x, y, z)) turns a round shape's length into that axis (baked into
the mesh).
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import core
from .core import segments as _auto_segments

__all__ = ["box", "rounded_box", "cylinder", "tube", "cone", "sphere", "dome", "capsule", "torus", "plane",
           "lathe", "pipe", "extrude", "extrude_image", "outline_from_image", "outline_from_curve", "spline",
           "fillet", "rounded_rect", "circle_points"]


def _size3(size):
    if isinstance(size, (int, float)):
        return float(size), float(size), float(size)
    s = tuple(float(c) for c in size)
    if len(s) != 3:
        raise ValueError("size must be a number or (x, y, z)")
    return s


def _seg(segments, radius, arc=360.0):
    if segments is None:
        return _auto_segments(radius, arc=arc)
    n = int(segments)
    if n < 3:
        raise ValueError("segments must be at least 3")
    return n


def _orient(bm, axis):
    if axis is not None and (not isinstance(axis, str) or axis.upper().lstrip("+") != "Z"):
        bmesh.ops.transform(bm, matrix=core.axis_matrix(axis), verts=bm.verts)


def _finish(bm, name, at, rot, axis, kw, smooth=30.0, bevel=None):
    _orient(bm, axis)
    obj = core.mesh_object(bm, name, at=at, rot=rot, smooth=smooth, **kw)
    if bevel:
        from .modify import bevel as add_bevel
        add_bevel(obj, width=bevel)
    return obj


def _kw(material, collection, parent):
    return {"material": material, "collection": collection, "parent": parent}


# ---------- rings and caps ----------

def _ring(bm, radius, z, n, phase=0.0, rx=None):
    rx = radius if rx is None else rx
    return [bm.verts.new((rx * math.cos(phase + 2 * math.pi * i / n), radius * math.sin(phase + 2 * math.pi * i / n), z))
            for i in range(n)]


def _bridge(bm, a, b, closed=True):
    faces = []
    n = len(a)
    for i in range(n if closed else n - 1):
        j = (i + 1) % n
        faces.append(bm.faces.new((a[i], a[j], b[j], b[i])))
    return faces


def _quad_cap(bm, ring):
    """All-quad disc: an inset ring plus a (n/4 x n/4) grid mapped onto a circle. ring: 4k verts in order."""
    n = len(ring)
    k = n // 4
    center = sum((v.co for v in ring), Vector()) / n
    e1 = ring[0].co - center
    radius = e1.length
    e1.normalize()
    normal = Vector()
    for i in range(n):
        normal += (ring[i].co - center).cross(ring[(i + 1) % n].co - center)
    normal.normalize()
    e2 = normal.cross(e1)
    inner = radius * max(0.35, 1.0 - 2.0 * math.pi / n)
    rot = -math.pi / 4.0  # grid corner (x=1, y=-1) sits at -45 degrees; turn it onto ring[0]
    cos_r, sin_r = math.cos(-rot), math.sin(-rot)
    grid = {}
    for ix in range(k + 1):
        for iy in range(k + 1):
            x = -1.0 + 2.0 * ix / k
            y = -1.0 + 2.0 * iy / k
            dx = x * math.sqrt(max(0.0, 1.0 - y * y / 2.0))
            dy = y * math.sqrt(max(0.0, 1.0 - x * x / 2.0))
            px, py = dx * cos_r - dy * sin_r, dx * sin_r + dy * cos_r
            grid[ix, iy] = bm.verts.new(center + e1 * (px * inner) + e2 * (py * inner))
    walk = [(k, iy) for iy in range(k)] + [(ix, k) for ix in range(k, 0, -1)] +            [(0, iy) for iy in range(k, 0, -1)] + [(ix, 0) for ix in range(k)]
    border = [grid[p] for p in walk]
    faces = _bridge(bm, ring, border)
    for ix in range(k):
        for iy in range(k):
            faces.append(bm.faces.new((grid[ix, iy], grid[ix + 1, iy], grid[ix + 1, iy + 1], grid[ix, iy + 1])))
    return faces


def _cap(bm, ring, caps):
    if caps in (None, False, "none"):
        return []
    center = sum((v.co for v in ring), Vector()) / len(ring)
    if caps == "quad" and len(ring) % 4 == 0 and len(ring) >= 8:
        return _quad_cap(bm, ring)
    if caps == "fan":
        c = bm.verts.new(center)
        return [bm.faces.new((ring[i], ring[(i + 1) % len(ring)], c)) for i in range(len(ring))]
    return [bm.faces.new(ring)]


# ---------- boxes ----------

def box(size=1.0, at=(0, 0, 0), rot=None, bevel=None, name="Box", material=None, collection=None, parent=None):
    """A box of size (x, y, z) meters (or one number), centered on at. bevel: a width in meters adds n.bevel().

        lid = n.box((0.6, 0.4, 0.04), at=(0, 0, 0.42), bevel=0.004, name="Lid")
    """
    sx, sy, sz = _size3(size)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts)
    return _finish(bm, name, at, rot, None, _kw(material, collection, parent), bevel=bevel)


def rounded_box(size=1.0, radius=None, segments=None, at=(0, 0, 0), rot=None, name="RoundedBox", material=None,
                collection=None, parent=None):
    """A box with truly rounded edges and corners (real geometry, all quads), plus weighted normals.

    radius: edge radius in meters (default 12% of the smallest side). segments: even numbers keep corners quads.

        cushion = n.rounded_box((0.45, 0.45, 0.08), radius=0.03, name="Cushion")
    """
    sx, sy, sz = _size3(size)
    smallest = min(sx, sy, sz)
    radius = 0.12 * smallest if radius is None else min(float(radius), smallest * 0.499)
    segs = int(segments or max(2, core.bevel_segments()))
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts)
    if radius > 0:
        bmesh.ops.bevel(bm, geom=list(bm.edges) + list(bm.verts), offset=radius, offset_type="OFFSET",
                        segments=segs, profile=0.5, affect="EDGES", clamp_overlap=True)
    obj = core.mesh_object(bm, name, at=at, rot=rot, smooth=True, **_kw(material, collection, parent))
    from .modify import weighted_normals
    weighted_normals(obj)
    return obj


# ---------- round shapes ----------

def cylinder(radius=0.5, depth=1.0, segments=None, axis="Z", caps="ngon", at=(0, 0, 0), rot=None, bevel=None,
             name="Cylinder", material=None, collection=None, parent=None):
    """A cylinder with enough sides for its size. caps: "ngon" (flat), "quad" (grid of quads), "fan", "none".

        barrel = n.cylinder(0.011, 0.42, axis="X", name="Barrel", bevel=0.001)
    """
    n = _seg(segments, radius)
    bm = bmesh.new()
    bottom = _ring(bm, radius, -depth / 2.0, n)
    top = _ring(bm, radius, depth / 2.0, n)
    _bridge(bm, bottom, top)
    _cap(bm, top, caps)
    _cap(bm, bottom, caps)
    return _finish(bm, name, at, rot, axis, _kw(material, collection, parent), bevel=bevel)


def tube(radius=0.5, depth=1.0, thickness=None, inner=None, segments=None, axis="Z", at=(0, 0, 0), rot=None,
         bevel=None, name="Tube", material=None, collection=None, parent=None):
    """A hollow pipe (outer wall, inner wall, ring ends; all quads). thickness or inner radius.

        sleeve = n.tube(0.02, 0.1, thickness=0.004, axis="X", name="Sleeve")
    """
    if inner is None:
        inner = radius - (thickness if thickness is not None else radius * 0.15)
    if not 0 < inner < radius:
        raise ValueError("tube: inner radius must be between 0 and radius")
    n = _seg(segments, radius)
    bm = bmesh.new()
    ob = _ring(bm, radius, -depth / 2.0, n)
    ot = _ring(bm, radius, depth / 2.0, n)
    it = _ring(bm, inner, depth / 2.0, n)
    ib = _ring(bm, inner, -depth / 2.0, n)
    _bridge(bm, ob, ot)
    _bridge(bm, ot, it)
    _bridge(bm, it, ib)
    _bridge(bm, ib, ob)
    return _finish(bm, name, at, rot, axis, _kw(material, collection, parent), bevel=bevel)


def cone(radius=0.5, depth=1.0, top=0.0, segments=None, axis="Z", caps="ngon", at=(0, 0, 0), rot=None,
         bevel=None, name="Cone", material=None, collection=None, parent=None):
    """A cone (top=0, a pointed tip) or a truncated cone (top = top radius). caps as cylinder.

        tip = n.cone(0.02, 0.05, top=0.008, axis="X", name="MuzzleTip")
    """
    n = _seg(segments, max(radius, top))
    bm = bmesh.new()
    bottom = _ring(bm, radius, -depth / 2.0, n)
    if top > 1e-9:
        upper = _ring(bm, top, depth / 2.0, n)
        _bridge(bm, bottom, upper)
        _cap(bm, upper, caps)
    else:
        tip = bm.verts.new((0, 0, depth / 2.0))
        for i in range(n):
            bm.faces.new((bottom[i], bottom[(i + 1) % n], tip))
    _cap(bm, bottom, caps)
    return _finish(bm, name, at, rot, axis, _kw(material, collection, parent), bevel=bevel)


def _spherify(v):
    x, y, z = v.x, v.y, v.z
    x2, y2, z2 = x * x, y * y, z * z
    return Vector((x * math.sqrt(max(0.0, 1 - y2 / 2 - z2 / 2 + y2 * z2 / 3)),
                   y * math.sqrt(max(0.0, 1 - z2 / 2 - x2 / 2 + z2 * x2 / 3)),
                   z * math.sqrt(max(0.0, 1 - x2 / 2 - y2 / 2 + x2 * y2 / 3))))


def _quad_sphere_bm(radius, n):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    if n > 1:
        bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=n - 1, use_grid_fill=True)
    for v in bm.verts:
        v.co = _spherify(v.co) * radius
    return bm


def sphere(radius=0.5, segments=None, kind="quad", at=(0, 0, 0), rot=None, name="Sphere", material=None,
           collection=None, parent=None):
    """A sphere. kind "quad": all quads, no poles (best for subdivision and deforming); "uv": rings with poles.

    segments: sides around the middle (default from size).

        knob = n.sphere(0.015, name="Knob")
    """
    seg = _seg(segments, radius)
    if kind == "uv":
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=max(4, seg // 2), radius=radius)
    else:
        bm = _quad_sphere_bm(radius, max(2, seg // 4))
    return _finish(bm, name, at, rot, None, _kw(material, collection, parent), smooth=True)


def dome(radius=0.5, height=None, segments=None, axis="Z", caps="ngon", at=(0, 0, 0), rot=None, name="Dome",
         material=None, collection=None, parent=None):
    """Half a quad sphere standing on its flat side (origin at the base center); height squashes it.

        rivet = n.dome(0.004, height=0.002, name="Rivet")
    """
    seg = _seg(segments, radius)
    n = max(2, seg // 4)
    n += n % 2  # an even grid has a ring exactly at the middle
    bm = _quad_sphere_bm(radius, n)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -1e-7 * max(radius, 1e-6)], context="VERTS")
    for v in bm.verts:
        if abs(v.co.z) < 1e-6 * max(radius, 1e-6):
            v.co.z = 0.0
    if height is not None:
        for v in bm.verts:
            v.co.z *= float(height) / radius
    ring = _boundary_loop(bm)
    if ring:
        _cap(bm, ring, caps)
    return _finish(bm, name, at, rot, axis, _kw(material, collection, parent), smooth=True)


def _boundary_loop(bm):
    edges = [e for e in bm.edges if e.is_boundary]
    if not edges:
        return []
    nxt = {}
    for e in edges:
        a, b = e.verts
        nxt.setdefault(a, []).append(b)
        nxt.setdefault(b, []).append(a)
    start = edges[0].verts[0]
    loop, prev, cur = [start], None, start
    while True:
        options = [v for v in nxt[cur] if v is not prev]
        if not options:
            break
        prev, cur = cur, options[0]
        if cur is start:
            break
        loop.append(cur)
    return loop


def capsule(radius=0.25, depth=1.0, segments=None, axis="Z", at=(0, 0, 0), rot=None, name="Capsule",
            material=None, collection=None, parent=None):
    """A pill: total length depth (>= 2 radius), all quads, no poles. The straight middle gets square quads at
    high detail only (they matter for deforming, not for the shape): light at low and medium.

        grip = n.capsule(0.016, 0.12, axis="Z", name="Grip")
    """
    seg = _seg(segments, radius)
    n = max(2, seg // 4)
    n += n % 2
    bm = _quad_sphere_bm(radius, n)
    half = max(0.0, depth / 2.0 - radius)
    eps = 1e-6 * max(radius, 1e-6)
    if half > 0:
        for v in bm.verts:
            if v.co.z > eps:
                v.co.z += half
            elif v.co.z < -eps:
                v.co.z -= half
        band = [e for e in bm.edges if (abs(e.verts[0].co.z) < eps) != (abs(e.verts[1].co.z) < eps)
                and abs(e.verts[0].co.z - e.verts[1].co.z) > half * 0.5]
        edge_len = 2 * math.pi * radius / (4 * n)
        cuts = max(0, int(round(half / max(edge_len, 1e-9))) - 1)
        cuts = min(cuts, {"low": 0, "medium": 1}.get(core.settings()["detail"], cuts))
        if cuts and band:
            bmesh.ops.subdivide_edges(bm, edges=band, cuts=cuts, use_grid_fill=True)
    return _finish(bm, name, at, rot, axis, _kw(material, collection, parent), smooth=True)


def torus(radius=0.5, thickness=0.1, segments=None, ring_segments=None, axis="Z", arc=360.0, at=(0, 0, 0),
          rot=None, name="Torus", material=None, collection=None, parent=None):
    """A ring (donut): radius to the tube's center, thickness = tube radius. arc < 360 makes an open bend with flat ends.

        hoop = n.torus(0.29, 0.006, name="Hoop")
    """
    full = arc >= 359.999
    big = _seg(segments, radius, arc=arc)
    small = _seg(ring_segments, thickness)
    bm = bmesh.new()
    rings = []
    count = big if full else big + 1
    for i in range(count):
        a = math.radians(arc) * i / big
        center = Vector((radius * math.cos(a), radius * math.sin(a), 0.0))
        out = Vector((math.cos(a), math.sin(a), 0.0))
        ring = []
        for j in range(small):
            b = 2 * math.pi * j / small
            ring.append(bm.verts.new(center + out * (thickness * math.cos(b)) + Vector((0, 0, thickness * math.sin(b)))))
        rings.append(ring)
    for i in range(len(rings) if full else len(rings) - 1):
        _bridge(bm, rings[i], rings[(i + 1) % len(rings)])
    if not full:
        bm.faces.new(rings[0])
        bm.faces.new(rings[-1])
    return _finish(bm, name, at, rot, axis, _kw(material, collection, parent))


def plane(size=1.0, at=(0, 0, 0), rot=None, cuts=0, axis="Z", name="Plane", material=None, collection=None,
          parent=None):
    """A flat grid of quads (open: for decals, leaves, cards). size (x, y) or one number; cuts per side.

        sign = n.plane((0.4, 0.25), axis="-Y", name="Sign")
    """
    sx, sy = (float(size), float(size)) if isinstance(size, (int, float)) else (float(size[0]), float(size[1]))
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=int(cuts) + 1, y_segments=int(cuts) + 1, size=0.5)
    bmesh.ops.scale(bm, vec=(sx, sy, 1.0), verts=bm.verts)
    return _finish(bm, name, at, rot, axis, _kw(material, collection, parent))


# ---------- 2D helpers ----------

def circle_points(radius, count=None, center=(0.0, 0.0), start=0.0, arc=360.0):
    """Points of a circle or arc in 2D: [(x, y), ...]. count defaults to the detail level."""
    count = count or _auto_segments(radius, arc=arc)
    closed = arc >= 359.999
    steps = count if closed else count
    pts = []
    for i in range(steps if closed else steps + 1):
        a = math.radians(start) + math.radians(arc) * i / steps
        pts.append((center[0] + radius * math.cos(a), center[1] + radius * math.sin(a)))
    return pts


def rounded_rect(width, height, radius=None, center=(0.0, 0.0)):
    """A rounded rectangle outline in 2D (for extrude / panel shapes)."""
    radius = min(width, height) * 0.15 if radius is None else float(radius)
    cx, cy = center
    w, h = width / 2.0, height / 2.0
    return fillet([(cx - w, cy - h, radius), (cx + w, cy - h, radius), (cx + w, cy + h, radius),
                   (cx - w, cy + h, radius)], closed=True)


def fillet(points, radius=None, closed=True, count=None):
    """Rounds corners of a 2D outline. Points (x, y) or (x, y, r): r is that corner's radius (0 = sharp).

        outline = n.fillet([(0, 0, 0), (0.3, 0, 0.02), (0.3, 0.1, 0.02), (0, 0.1, 0)])
    """
    pts = [(float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else float(radius or 0.0)) for p in points]
    out = []
    n = len(pts)
    for i, (x, y, r) in enumerate(pts):
        if r <= 0 or (not closed and (i == 0 or i == n - 1)):
            out.append((x, y))
            continue
        p = Vector((x, y))
        a = Vector(pts[i - 1][:2]) - p
        b = Vector(pts[(i + 1) % n][:2]) - p
        if a.length < 1e-12 or b.length < 1e-12:
            out.append((x, y))
            continue
        a.normalize()
        b.normalize()
        cosang = max(-1.0, min(1.0, a.dot(b)))
        angle = math.acos(cosang)
        if angle < 1e-4 or angle > math.pi - 1e-4:
            out.append((x, y))
            continue
        d = r / math.tan(angle / 2.0)
        d = min(d, (Vector(pts[i - 1][:2]) - p).length * 0.5, (Vector(pts[(i + 1) % n][:2]) - p).length * 0.5)
        r_eff = d * math.tan(angle / 2.0)
        t1, t2 = p + a * d, p + b * d
        bis = (a + b).normalized()
        center = p + bis * (r_eff / math.sin(angle / 2.0))
        turn = math.pi - angle
        steps = count or max(2, _auto_segments(r_eff, arc=math.degrees(turn)))
        a1 = math.atan2(t1.y - center.y, t1.x - center.x)
        a2 = math.atan2(t2.y - center.y, t2.x - center.x)
        delta = a2 - a1
        while delta > math.pi:
            delta -= 2 * math.pi
        while delta < -math.pi:
            delta += 2 * math.pi
        for k in range(steps + 1):
            t = a1 + delta * k / steps
            out.append((center.x + r_eff * math.cos(t), center.y + r_eff * math.sin(t)))
    return out


def spline(points, samples=None, closed=False):
    """A smooth curve through 2D or 3D points (Catmull-Rom). samples: points per span (default from detail).

        profile = n.spline([(0.0, 0), (0.05, 0.01), (0.045, 0.12), (0.015, 0.16)])   # for n.lathe
    """
    pts = [Vector(p) for p in points]
    dim = len(points[0])
    if len(pts) < 3:
        return [tuple(p) for p in points]
    samples = samples or max(3, core.bevel_segments() * 2)
    if closed:
        ext = [pts[-1]] + pts + [pts[0], pts[1]]
        spans = len(pts)
    else:
        ext = [pts[0] * 2 - pts[1]] + pts + [pts[-1] * 2 - pts[-2]]
        spans = len(pts) - 1
    out = []
    for s in range(spans):
        p0, p1, p2, p3 = ext[s], ext[s + 1], ext[s + 2], ext[s + 3]
        for k in range(samples):
            t = k / samples
            t2, t3 = t * t, t * t * t
            q = 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
            out.append(tuple(q)[:dim])
    if not closed:
        out.append(tuple(pts[-1])[:dim])
    return out


# ---------- lathe, pipe ----------

def lathe(profile, segments=None, axis="Z", caps="ngon", at=(0, 0, 0), rot=None, name="Lathe", material=None,
          collection=None, parent=None):
    """Spins a side profile around the axis: profile = [(radius, height), ...] from bottom to top.

    A point with radius 0 closes that end in a point; open ends get caps ("ngon", "quad", "fan" or "none").
    A profile that ends where it starts makes a closed ring (a hollow wall: up the outside, down the inside).
    Use n.spline() for smooth curves; corners sharper than 30 degrees stay sharp.

        body = n.lathe(n.spline([(0, 0), (0.06, 0.005), (0.07, 0.08), (0.03, 0.15), (0.02, 0.2)]), name="Vase")
    """
    prof = [(max(0.0, float(p[0])), float(p[1])) for p in profile]
    if len(prof) < 2:
        raise ValueError("lathe needs at least 2 profile points")
    n = _seg(segments, max(p[0] for p in prof))
    eps = 1e-7
    bm = bmesh.new()
    rings = []
    for r, z in prof:
        rings.append(bm.verts.new((0, 0, z)) if r < eps else _ring(bm, r, z, n))
    for a, b in zip(rings, rings[1:]):
        if isinstance(a, list) and isinstance(b, list):
            _bridge(bm, a, b)
        elif isinstance(a, list):
            for i in range(n):
                bm.faces.new((a[i], a[(i + 1) % n], b))
        elif isinstance(b, list):
            for i in range(n):
                bm.faces.new((b[(i + 1) % n], b[i], a))
    closed = (Vector(prof[0]) - Vector(prof[-1])).length < 1e-6 and len(prof) > 2   # a ring: its ends meet
    for end in (rings[0], rings[-1]):
        if isinstance(end, list) and not closed:
            _cap(bm, end, caps)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
    return _finish(bm, name, at, rot, axis, _kw(material, collection, parent))


def _fillet3d(points, bend, count=None):
    pts = [Vector(p) for p in points]
    if bend <= 0 or len(pts) < 3:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        p, a, b = pts[i], pts[i - 1], pts[i + 1]
        da, db = (a - p), (b - p)
        if da.length < 1e-12 or db.length < 1e-12:
            continue
        da.normalize()
        db.normalize()
        angle = math.acos(max(-1.0, min(1.0, da.dot(db))))
        if angle > math.pi - 1e-3 or angle < 1e-3:
            out.append(p)
            continue
        d = min(bend / math.tan(angle / 2.0), (a - p).length * 0.5, (b - p).length * 0.5)
        r = d * math.tan(angle / 2.0)
        t1, t2 = p + da * d, p + db * d
        center = p + (da + db).normalized() * (r / math.sin(angle / 2.0))
        u, v = (t1 - center).normalized(), (t2 - center).normalized()
        turn = math.acos(max(-1.0, min(1.0, u.dot(v))))
        steps = count or max(2, _auto_segments(r, arc=math.degrees(turn)) // 1)
        axis = u.cross(v)
        if axis.length < 1e-12:
            out.append(p)
            continue
        axis.normalize()
        for k in range(steps + 1):
            q = Matrix.Rotation(turn * k / steps, 3, axis) @ u
            out.append(center + q * r)
    out.append(pts[-1])
    return out


def pipe(points, radius=0.02, segments=None, bend=None, caps="ngon", closed=False, at=(0, 0, 0), rot=None,
         name="Pipe", material=None, collection=None, parent=None):
    """A round tube along a 3D path (points relative to at). bend: corner radius (default 2 x radius).

    Quads all along, even width through bends. closed=True joins the ends into a loop.

        handle = n.pipe([(-0.1, 0, 0), (-0.1, 0, 0.06), (0.1, 0, 0.06), (0.1, 0, 0)], radius=0.008, name="Handle")
    """
    bend = radius * 2.0 if bend is None else float(bend)
    path = [Vector(p) for p in points]
    if closed and (path[0] - path[-1]).length < 1e-9:
        path = path[:-1]
    if closed and bend > 0:
        path = _fillet3d([path[-1]] + path + [path[0]], bend)[1:-1]
    else:
        path = _fillet3d(path, bend)
    clean = [path[0]]
    for p in path[1:]:
        if (p - clean[-1]).length > 1e-9:
            clean.append(p)
    path = clean
    if len(path) < 2:
        raise ValueError("pipe needs at least 2 distinct points")
    n = _seg(segments, radius)
    m = len(path)
    tangents = []
    for i in range(m):
        if closed:
            t1 = (path[i] - path[i - 1]).normalized()
            t2 = (path[(i + 1) % m] - path[i]).normalized()
        else:
            t1 = (path[i] - path[i - 1]).normalized() if i > 0 else (path[1] - path[0]).normalized()
            t2 = (path[i + 1] - path[i]).normalized() if i < m - 1 else t1
        tangents.append((t1, t2))
    frames = []
    for t1, t2 in tangents:
        t = t1 + t2
        frames.append(t.normalized() if t.length > 1e-9 else t1)
    t0 = frames[0]
    ref = Vector((0, 0, 1)) if abs(t0.z) < 0.9 else Vector((1, 0, 0))
    normal = (ref - t0 * ref.dot(t0)).normalized()
    normals = []
    prev_t = t0
    for t in frames:
        normal = prev_t.rotation_difference(t).to_matrix() @ normal
        normal = (normal - t * normal.dot(t)).normalized()
        normals.append(normal)
        prev_t = t
    twist = 0.0
    if closed:  # spread the transport twist over the loop so the ends meet
        back = (frames[-1].rotation_difference(t0).to_matrix() @ normals[-1])
        back = (back - t0 * back.dot(t0)).normalized()
        twist = math.atan2(normals[0].cross(back).dot(t0), normals[0].dot(back))
    bm = bmesh.new()
    rings = []
    for i in range(m):
        t1, t2 = tangents[i]
        t, normal = frames[i], normals[i]
        binormal = t.cross(normal)
        stretch = 1.0 / max(0.2, t1.dot(t))
        k = t2 - t1
        k = k - t * k.dot(t)
        kn = k.normalized() if k.length > 1e-9 else None
        phase = -twist * i / m
        ring = []
        for j in range(n):
            a = 2 * math.pi * j / n + phase
            o = (normal * math.cos(a) + binormal * math.sin(a)) * radius
            if kn is not None:
                o = o + kn * (o.dot(kn) * (stretch - 1.0))
            ring.append(bm.verts.new(path[i] + o))
        rings.append(ring)
    for i in range(m - 1):
        _bridge(bm, rings[i], rings[i + 1])
    if closed:
        _bridge(bm, rings[-1], rings[0])
    else:
        _cap(bm, rings[0], caps)
        _cap(bm, rings[-1], caps)
    return _finish(bm, name, at, rot, None, _kw(material, collection, parent))


# ---------- extrude outlines ----------

_PLANES = {
    "XZ": (lambda u, v, w: (u, w, v), Vector((0, 1, 0))),
    "XY": (lambda u, v, w: (u, v, w), Vector((0, 0, 1))),
    "YZ": (lambda u, v, w: (w, u, v), Vector((1, 0, 0))),
}


def _area2(pts):
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts)))


def _dedupe2(pts):
    out = []
    for p in pts:
        if not out or (abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9):
            out.append((p[0], p[1]))
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) < 1e-9 and abs(out[0][1] - out[-1][1]) < 1e-9:
        out.pop()
    return out


def extrude(outline, depth=0.1, plane="XZ", holes=None, at=(0, 0, 0), rot=None, bevel=None, name="Extrude",
            material=None, collection=None, parent=None):
    """A flat 2D outline made solid: outline [(u, v) or (u, v, corner_radius)], depth along the plane's normal.

    plane: "XZ" (u = x, v = z, thickness along Y: side profiles), "XY" (top shapes, thickness along Z),
    "YZ" (u = y, v = z, thickness along X). holes: more outlines cut through. Flat caps, quad sides.

        blade = n.extrude([(0, 0), (0.04, 0), (0.035, 0.7), (0.0, 0.78), (-0.035, 0.7), (-0.04, 0)],
                          depth=0.006, plane="XZ", bevel=0.002, name="Blade")
    """
    key = str(plane).upper()
    if key not in _PLANES:
        raise ValueError("plane must be XZ, XY or YZ")
    to3d, normal = _PLANES[key]
    outer = _dedupe2(fillet(outline, closed=True) if any(len(p) > 2 for p in outline) else outline)
    if len(outer) < 3:
        raise ValueError("an outline needs at least 3 points")
    hole_loops = [_dedupe2(fillet(h, closed=True) if any(len(p) > 2 for p in h) else h) for h in (holes or [])]
    bm = bmesh.new()
    if _area2(outer) < 0:
        outer = outer[::-1]
    verts = [bm.verts.new(to3d(u, v, -depth / 2.0)) for u, v in outer]
    if hole_loops:
        edges = [bm.edges.new((verts[i], verts[(i + 1) % len(verts)])) for i in range(len(verts))]
        for h in hole_loops:
            hv = [bm.verts.new(to3d(u, v, -depth / 2.0)) for u, v in h]
            edges += [bm.edges.new((hv[i], hv[(i + 1) % len(hv)])) for i in range(len(hv))]
        res = bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=True, edges=edges)
        faces = [g for g in res["geom"] if isinstance(g, bmesh.types.BMFace)]
    else:
        faces = [bm.faces.new(verts)]
    ext = bmesh.ops.extrude_face_region(bm, geom=faces)
    moved = [g for g in ext["geom"] if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=normal * depth, verts=moved)
    return _finish(bm, name, at, rot, None, _kw(material, collection, parent), bevel=bevel)


# ---------- outlines from pictures and curves ----------

def subject_mask(px, threshold=0.5):
    """Which pixels belong to the subject of a picture (float RGBA, rows bottom to top): by transparency when the
    picture has it, else by difference from the border color."""
    import numpy as np
    alpha = px[..., 3]
    if alpha.min() < 0.5 and (alpha < 0.5).mean() > 0.01:
        return alpha > threshold
    border = np.concatenate([px[0, :, :3], px[-1, :, :3], px[:, 0, :3], px[:, -1, :3]])
    bg = np.median(border, axis=0)
    dist = np.sqrt(((px[..., :3] - bg) ** 2).sum(axis=-1))
    return dist > max(0.04, threshold * 0.3)


def _mask_from_image(path, threshold, invert, max_res):
    import numpy as np
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = img.size
        if not w or not h:
            raise ValueError(f"could not read the picture {path!r}")
        px = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(img)
    mask = subject_mask(px.reshape(h, w, 4), threshold)
    if invert:
        mask = ~mask
    scale = max(w, h) / float(max_res)
    if scale > 1.0:
        nh, nw = max(2, int(round(h / scale))), max(2, int(round(w / scale)))
        ys = np.linspace(0, h - 1, nh).astype(int)
        xs = np.linspace(0, w - 1, nw).astype(int)
        mask = mask[ys][:, xs]
    return mask


def _trace(mask):
    """Boundary loops of a boolean grid: outer loops counter-clockwise, holes clockwise (pixel corners)."""
    import numpy as np
    m = np.pad(mask, 1, constant_values=False)
    edges = {}
    ys, xs = np.nonzero(m)
    for i, j in zip(ys.tolist(), xs.tolist()):
        if not m[i - 1, j]:
            edges.setdefault((j, i), []).append((j + 1, i))
        if not m[i, j + 1]:
            edges.setdefault((j + 1, i), []).append((j + 1, i + 1))
        if not m[i + 1, j]:
            edges.setdefault((j + 1, i + 1), []).append((j, i + 1))
        if not m[i, j - 1]:
            edges.setdefault((j, i + 1), []).append((j, i))
    loops = []
    while edges:
        start = next(iter(edges))
        loop = [start]
        cur, came = start, None
        while True:
            options = edges.get(cur)
            if not options:
                break
            if len(options) > 1 and came is not None:
                def turn(o):
                    d = (o[0] - cur[0], o[1] - cur[1])
                    cross = came[0] * d[1] - came[1] * d[0]
                    return -cross  # left turn first
                options.sort(key=turn)
            nxt = options.pop(0)
            if not options:
                del edges[cur]
            came = (nxt[0] - cur[0], nxt[1] - cur[1])
            cur = nxt
            if cur == start:
                break
            loop.append(cur)
        if len(loop) >= 4:
            loops.append([(x - 1.0, y - 1.0) for x, y in loop])
    return loops


def _rdp(points, eps):
    """Douglas-Peucker simplification of a closed loop (no recursion)."""
    if len(points) < 4:
        return points
    import numpy as np
    pts = np.asarray(points, dtype=np.float64)
    far = int(np.argmax(np.hypot(pts[:, 0] - pts[0, 0], pts[:, 1] - pts[0, 1])))
    pts = np.concatenate([pts, pts[:1]])
    keep = {0, far, len(pts) - 1}
    stack = [(0, far), (far, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        p, q = pts[a], pts[b]
        seg = q - p
        length = np.hypot(seg[0], seg[1])
        inner = pts[a + 1:b]
        if length < 1e-12:
            d = np.hypot(inner[:, 0] - p[0], inner[:, 1] - p[1])
        else:
            d = np.abs(seg[0] * (inner[:, 1] - p[1]) - seg[1] * (inner[:, 0] - p[0])) / length
        k = int(np.argmax(d))
        if d[k] > eps:
            mid = a + 1 + k
            keep.add(mid)
            stack.append((a, mid))
            stack.append((mid, b))
    idx = sorted(i for i in keep if i < len(pts) - 1)
    return [tuple(pts[i]) for i in idx]


def _chaikin(points, iterations):
    for _ in range(int(iterations)):
        out = []
        n = len(points)
        for i in range(n):
            p, q = points[i], points[(i + 1) % n]
            out.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            out.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        points = out
    return points


def _inside(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def outline_from_image(path, width=None, height=None, threshold=0.5, simplify=0.004, smooth=0, invert=False,
                       max_res=400, min_area=0.002):
    """Outlines of the shape in a picture (transparent background, or a plain one), in meters, centered.

    Returns [{"outline": [(u, v), ...], "holes": [[...], ...]}, ...] biggest first. width / height: the shape's
    size in meters (default width 1). simplify: allowed error as a fraction of the picture; smooth: rounding passes.

        shapes = n.outline_from_image("C:/refs/sword.png", height=0.9)
    """
    mask = _mask_from_image(path, threshold, invert, max_res)
    if not mask.any():
        raise ValueError("no shape found in the picture (try invert=True or another threshold)")
    loops = _trace(mask)
    eps = max(0.5, simplify * max(mask.shape))
    loops = [_rdp(l, eps) for l in loops]
    if smooth:
        loops = [_chaikin(l, smooth) for l in loops]
    loops = [l for l in loops if len(l) >= 3]
    areas = [_area2(l) for l in loops]
    biggest = max(abs(a) for a in areas)
    outers = [(l, a) for l, a in zip(loops, areas) if a > 0 and a >= biggest * min_area]
    holes = [l for l, a in zip(loops, areas) if a < 0 and -a >= biggest * min_area]
    outers.sort(key=lambda la: -la[1])
    shapes = [{"outline": l, "holes": []} for l, _ in outers]
    for h in holes:
        for s in shapes:
            if _inside(h[0], s["outline"]):
                s["holes"].append(h)
                break
    allpts = [p for s in shapes for p in s["outline"]]
    xs = [p[0] for p in allpts]
    ys = [p[1] for p in allpts]
    w_px, h_px = max(xs) - min(xs), max(ys) - min(ys)
    if width:
        scale = float(width) / w_px
    elif height:
        scale = float(height) / h_px
    else:
        scale = 1.0 / w_px
    cx, cy = (max(xs) + min(xs)) / 2.0, (max(ys) + min(ys)) / 2.0

    def conv(loop):
        return [((x - cx) * scale, (y - cy) * scale) for x, y in loop]
    return [{"outline": conv(s["outline"]), "holes": [conv(h) for h in s["holes"]]} for s in shapes]


def extrude_image(path, depth=0.02, width=None, height=None, plane="XZ", threshold=0.5, simplify=0.004, smooth=0,
                  invert=False, keep="all", at=(0, 0, 0), rot=None, bevel=None, name="Silhouette", material=None,
                  collection=None, parent=None):
    """A solid from a picture's silhouette (holes included): outline_from_image + extrude, joined in one object.

    keep: "all" or "largest". Good for blades, keys, signs, logos and side profiles to model against.

        key = n.extrude_image("C:/refs/key.png", depth=0.004, width=0.07, plane="XY", bevel=0.0006, name="Key")
    """
    shapes = outline_from_image(path, width=width, height=height, threshold=threshold, simplify=simplify,
                                smooth=smooth, invert=invert)
    if keep == "largest":
        shapes = shapes[:1]
    parts = [extrude(s["outline"], depth=depth, plane=plane, holes=s["holes"], name=name, collection=collection)
             for s in shapes]
    obj = parts[0]
    if len(parts) > 1:
        from .assemble import merge_parts
        obj = merge_parts(parts, name=name, weld=False)
    obj.location = at
    if rot is not None:
        obj.rotation_euler = [math.radians(a) for a in rot]
    if parent is not None:
        obj.parent = core.get(parent)
    if material is not None:
        from .paint import paint
        paint(obj, material)
    if bevel:
        from .modify import bevel as add_bevel
        add_bevel(obj, width=bevel)
    return obj


def outline_from_curve(curve, samples=None):
    """2D outlines (x, y in the curve's own space) of a curve object's closed splines, for extrude / lathe.

        loops = n.outline_from_curve("ProfileCurve"); n.extrude(loops[0], depth=0.03)
    """
    from mathutils.geometry import interpolate_bezier
    obj = core.get(curve)
    if obj.type != "CURVE":
        raise ValueError(f"{obj.name} is not a curve")
    res = int(samples or max(4, core.bevel_segments() * 3))
    loops = []
    for sp in obj.data.splines:
        pts = []
        if sp.type == "BEZIER":
            bp = sp.bezier_points
            count = len(bp) if sp.use_cyclic_u else len(bp) - 1
            for i in range(count):
                a, b = bp[i], bp[(i + 1) % len(bp)]
                seg = interpolate_bezier(a.co, a.handle_right, b.handle_left, b.co, res + 1)
                pts.extend((p.x, p.y) for p in seg[:-1])
            if not sp.use_cyclic_u:
                pts.append((bp[-1].co.x, bp[-1].co.y))
        else:
            pts = [(p.co.x, p.co.y) for p in sp.points]
        if len(pts) >= 2:
            loops.append(_dedupe2(pts))
    return loops
