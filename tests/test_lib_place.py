# SPDX-License-Identifier: GPL-3.0-or-later
# Relational placement: align, snap, stack, distribute, ground, transforms, origin.

FRESH_SCENE = True  # tests/run.py: an empty factory scene before each test

import math

from _util import n, raises


def _near(a, b, tol=1e-4):
    return abs(a - b) <= tol


def test_align_relations():
    base = n.box((1, 1, 0.2), name="Base")
    top = n.box((0.2, 0.2, 0.2), at=(3, 3, 3), name="Top")
    n.align(top, base, "on_top")
    bt, bb = n.bounds(top), n.bounds(base)
    assert _near(bt.min.z, bb.max.z) and _near(bt.center.x, bb.center.x) and _near(bt.center.y, bb.center.y)
    n.align(top, base, "on_top", "flush_back", "flush_left", gap=0.01)
    bt = n.bounds(top)
    assert _near(bt.min.z, bb.max.z + 0.01) and _near(bt.max.y, bb.max.y) and _near(bt.min.x, bb.min.x)
    n.align(top, base, "front")
    bt = n.bounds(top)
    assert _near(bt.max.y, bb.min.y)
    n.align(top, base, "right", "keep_z")
    bt2 = n.bounds(top)
    assert _near(bt2.min.x, bb.max.x) and _near(bt2.center.z, bt.center.z)
    raises(n.align, top, base, "sideways", contains="unknown relation")


def test_snap_onto_curved_surface():
    ball = n.sphere(0.5, name="Ball")
    pin = n.box((0.05, 0.05, 0.05), at=(0, 0, 2), name="Pin")
    n.snap(pin, ball, "-Z")
    assert _near(n.bounds(pin).min.z, 0.4985, 3e-3)  # the faceted sphere is a bit lower off-center
    side = n.box((0.05, 0.05, 0.05), at=(0.2, -2, 0.1), name="Side")
    n.snap(side, ball, "+Y")
    d = n.distance(side, ball)
    assert d["surface_distance"] < 2e-3


def test_stack_distribute_ground_center():
    a = n.box((0.5, 0.5, 0.1), name="A")
    b = n.cylinder(0.05, 0.6, name="B")
    c = n.sphere(0.1, name="C")
    n.stack([a, b, c], "Z")
    assert _near(n.bounds(b).min.z, n.bounds(a).max.z) and _near(n.bounds(c).min.z, n.bounds(b).max.z, 1e-3)
    n.ground([a, b, c])
    assert _near(n.bounds([a, b, c]).min.z, 0.0)
    boxes = [n.box(0.1, at=(i * 0.13, 0, 0)) for i in range(4)]
    n.distribute(boxes, "X", spacing=0.05)
    xs = [n.bounds(o).min.x for o in boxes]
    assert all(_near(xs[i + 1] - xs[i], 0.15) for i in range(3))
    n.center(boxes, "XY")
    assert _near(n.bounds(boxes).center.x, 0.0)


def test_apply_transforms_and_scale_to():
    b = n.box((1, 1, 1))
    b.scale = (2, 1, 0.5)
    b.rotation_euler = (0, 0, math.radians(90))
    n.apply_transforms(b)
    assert tuple(b.scale) == (1, 1, 1) and tuple(b.rotation_euler) == (0, 0, 0)
    s = n.bounds(b).size
    assert _near(s.x, 1.0) and _near(s.y, 2.0) and _near(s.z, 0.5)
    n.scale_to(b, 1.8, "z", ground_it=True)
    s = n.bounds(b).size
    assert _near(s.z, 1.8) and _near(n.bounds(b).min.z, 0.0) and tuple(b.scale) == (1, 1, 1)


def test_set_origin_keeps_mesh_in_place():
    c = n.cylinder(0.1, 0.4, at=(1, 1, 1))
    before = n.bounds(c)
    n.set_origin(c, "bottom")
    after = n.bounds(c)
    assert _near(c.location.z, 0.8) and _near(after.min.z, before.min.z)


def test_parts_collections_duplicate():
    leg = n.box((0.05, 0.05, 0.7), at=(-0.3, -0.2, 0.35), name="Leg")
    n.part(leg, "LegFL", collection="Table")
    assert leg.name == "LegFL" and leg.users_collection[0].name == "Table"
    other = n.duplicate(leg, mirror_x=True, name="LegFR")
    assert _near(n.bounds(other).center.x, 0.3)
    assert n.verify(other)["pass"]
    n.parent(other, leg)
    assert other.parent == leg and _near(n.bounds(other).center.x, 0.3)
    coll = n.group([leg, other], "Furniture")
    assert set(o.name for o in coll.objects) == {"LegFL", "LegFR"}


def test_rotate_group_and_place_on():
    import math
    a = n.box((0.4, 0.1, 0.1), at=(0.2, 0, 0), name="Arm")
    b = n.box((0.1, 0.1, 0.1), at=(0.45, 0, 0), name="Tip")
    n.rotate([a, b], 90, "Z", pivot=(0, 0, 0))
    assert _near(n.bounds(b).center.y, 0.45) and _near(n.bounds(b).center.x, 0.0)
    ball = n.sphere(0.5, name="Cap")
    spot = n.dome(0.03, height=0.01, at=(0.3, 0.0, 2.0), name="Spot")
    n.place_on(spot, ball, "-Z")
    loc = spot.location
    assert abs(loc.length - 0.5) < 5e-3
    up = spot.matrix_world.to_3x3() @ __import__("mathutils").Vector((0, 0, 1))
    assert up.normalized().dot(loc.normalized()) > 0.98
    assert n.verify([ball, spot])["pass"]
