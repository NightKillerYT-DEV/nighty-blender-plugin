# SPDX-License-Identifier: GPL-3.0-or-later
# The nighty library's shapes: closed, clean, the right size, enough sides, transforms applied.

FRESH_SCENE = True  # tests/run.py: an empty factory scene before each test

import math

from _util import n


def _ok(obj, allow_open=False, quads_only=False):
    rep = n.verify(obj, allow_open=allow_open)
    assert rep["pass"], (obj.name, rep["errors"])
    r = rep["objects"][obj.name]
    if quads_only:
        assert r["tris"] == 0 and r["ngons"] == 0, (obj.name, r["tris"], r["ngons"])
    assert tuple(obj.scale) == (1.0, 1.0, 1.0)
    return r


def _close(a, b, tol=1e-4):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_segments_by_size_and_detail():
    assert n.segments(0.012) >= 16 and n.segments(0.012) % 4 == 0
    assert n.segments(0.3) == 64
    assert n.segments(0.3, "low") == 32
    assert n.segments(0.001, "low") == 12  # never fewer than 12 by default
    assert n.segments(0.3, "high") > n.segments(0.3) > n.segments(0.3, "low")
    n.settings(size=0.9)
    assert n.segments(0.0095) == 20  # a rifle barrel
    n.settings(size=0.3)
    assert n.segments(0.01) <= 32  # a small ring on a small asset stays light
    assert n.bevel_segments() % 2 == 0
    arc = n.segments(0.05, arc=90)
    assert 4 <= arc <= 16


def test_box_and_rounded_box():
    b = n.box((1, 0.5, 0.25), at=(1, 2, 3))
    r = _ok(b, quads_only=True)
    assert r["faces"] == 6
    assert _close(n.bounds(b).size, (1, 0.5, 0.25))
    assert _close(n.bounds(b).center, (1, 2, 3))
    rb = n.rounded_box((0.6, 0.4, 0.3), radius=0.05)
    _ok(rb, quads_only=True)
    assert _close(n.bounds(rb).size, (0.6, 0.4, 0.3))
    assert any(m.type == "WEIGHTED_NORMAL" for m in rb.modifiers)


def test_cylinders_and_caps():
    c = n.cylinder(0.2, 0.5, axis="X")
    r = _ok(c)
    assert _close(n.bounds(c).size, (0.5, 0.4, 0.4), 1e-3)
    assert r["quads"] == n.segments(0.2) and r["ngons"] == 2
    q = n.cylinder(0.05, 0.1, caps="quad")
    _ok(q, quads_only=True)
    f = n.cylinder(0.05, 0.1, caps="fan")
    _ok(f)
    o = n.cylinder(0.05, 0.1, caps="none")
    _ok(o, allow_open=True)
    assert n.verify(o)["pass"] is False  # open without allow_open
    tube = n.tube(0.2, 0.5, thickness=0.02)
    _ok(tube, quads_only=True)


def test_cone_sphere_dome_capsule_torus():
    _ok(n.cone(0.2, 0.4))
    _ok(n.cone(0.2, 0.4, top=0.05, caps="quad"), quads_only=True)
    s = n.sphere(0.25)
    _ok(s, quads_only=True)
    assert _close(n.bounds(s).size, (0.5, 0.5, 0.5), 1e-3)
    _ok(n.sphere(0.25, kind="uv"))
    d = n.dome(0.1, height=0.05)
    _ok(d)
    assert abs(n.bounds(d).size.z - 0.05) < 1e-3
    cap = n.capsule(0.1, 0.6)
    _ok(cap, quads_only=True)
    assert abs(n.bounds(cap).size.z - 0.6) < 1e-3
    _ok(n.torus(0.3, 0.05), quads_only=True)
    _ok(n.torus(0.3, 0.05, arc=120))


def test_lathe_pipe_extrude():
    prof = n.spline([(0, 0), (0.1, 0.01), (0.12, 0.15), (0.05, 0.25), (0.04, 0.3)])
    vase = n.lathe(prof)
    _ok(vase)
    wall = n.lathe([(0.05, 0), (0.06, 0), (0.06, 0.1), (0.05, 0.1), (0.05, 0)])   # closed profile: a ring, no caps
    _ok(wall, quads_only=True)
    pipe = n.pipe([(0, 0, 0), (0, 0, 0.3), (0.3, 0, 0.3), (0.3, 0.3, 0.5)], radius=0.02)
    r = _ok(pipe)
    assert r["tris"] == 0
    ring = n.pipe([(0, 0, 0), (0.3, 0, 0), (0.3, 0.3, 0), (0, 0.3, 0)], radius=0.02, closed=True)
    _ok(ring, quads_only=True)
    blade = n.extrude([(0, 0), (0.04, 0), (0.03, 0.6), (0, 0.66), (-0.03, 0.6), (-0.04, 0)], depth=0.006)
    _ok(blade)
    assert _close(n.bounds(blade).size, (0.08, 0.006, 0.66), 1e-4)
    plate = n.extrude(n.rounded_rect(0.3, 0.2, 0.02), depth=0.01, plane="XY",
                      holes=[n.circle_points(0.03, center=(0.05, 0)), n.circle_points(0.02, center=(-0.08, 0.04))])
    _ok(plate)


def test_fillet_and_spline_points():
    pts = n.fillet([(0, 0, 0), (1, 0, 0.2), (1, 1, 0.2), (0, 1, 0)])
    assert len(pts) > 6
    assert all(-1e-6 <= x <= 1 + 1e-6 and -1e-6 <= y <= 1 + 1e-6 for x, y in pts)  # 5.x Vectors are float32
    sp = n.spline([(0, 0), (1, 1), (2, 0)], samples=5)
    assert len(sp) == 11 and sp[0] == (0, 0) and sp[-1] == (2, 0)
    circle = n.circle_points(1.0, count=8)
    assert len(circle) == 8 and abs(circle[2][1] - 1.0) < 1e-9


def test_details():
    for kind in ("hex", "round", "socket"):
        _ok(n.bolt(0.01, kind=kind, axis="-Y", at=(0, -1, 0)))
    w = n.bolt(0.01, washer=True)
    assert n.verify(w)["pass"]
    _ok(n.rail(0.15))
    _ok(n.handle(0.12, 0.04, 0.006))
    t = n.text3d("AB", size=0.1, depth=0.01)
    assert t.type == "MESH" and len(t.data.polygons) > 10
    assert len(t.data.uv_layers) == 0


def test_no_eight_sided_defaults():
    for detail in ("low", "medium", "high"):
        n.settings(detail=detail)
        for obj in (n.cylinder(0.002, 0.01), n.cone(0.002, 0.01), n.tube(0.002, 0.01, thickness=0.0005)):
            zs = [v.co.z for v in obj.data.vertices]
            bottom = sum(1 for z in zs if abs(z - min(zs)) < 1e-9)
            assert bottom >= 12, (detail, obj.name, bottom)


def test_direction_vectors_and_text():
    c = n.cylinder(0.05, 0.4, axis=(1, 1, 0))
    b = n.bounds(c)
    assert abs(b.size.x - b.size.y) < 1e-3 and b.size.x > 0.25
    d = n.dome(0.02, axis=(0, -1, 1))
    assert n.verify(d)["pass"]
    plain = n.text3d("AB", size=0.1, depth=0.01, bevel=0)
    beveled = n.text3d("AB", size=0.1, depth=0.01)
    assert len(plain.data.polygons) < len(beveled.data.polygons)
    light = n.text3d("AB", size=0.1, depth=0.01, resolution=1, bevel=0)
    assert len(light.data.polygons) < len(plain.data.polygons)
