# SPDX-License-Identifier: GPL-3.0-or-later
# Bevels, booleans, panel cuts, mirror / array / radial, merging, cleanup.

FRESH_SCENE = True  # tests/run.py: an empty factory scene before each test

import math

from _util import n, raises


def _types(obj):
    return [m.type for m in obj.modifiers]


def test_bevel_stack_order_and_update():
    b = n.box((0.4, 0.3, 0.2))
    n.bevel(b, width=0.01)
    assert _types(b) == ["BEVEL", "WELD", "WEIGHTED_NORMAL"]
    mod = b.modifiers["Bevel"]
    assert mod.harden_normals and mod.limit_method == "ANGLE" and mod.segments % 2 == 0
    n.mirror(b, "X")
    n.array(b, 2, offset=(0.5, 0, 0))
    assert _types(b) == ["MIRROR", "ARRAY", "BEVEL", "WELD", "WEIGHTED_NORMAL"]
    n.bevel(b, width=0.02, segments=2)  # updates, no second bevel
    assert _types(b).count("BEVEL") == 1 and abs(b.modifiers["Bevel"].width - 0.02) < 1e-7
    n.subdivide(b, 1)
    assert _types(b)[-2:] == ["SUBSURF", "WEIGHTED_NORMAL"]
    assert n.verify(b)["pass"]


def test_bevel_clears_sharp_edges_smooth_by_angle_marks_them():
    b = n.box(0.2)
    sharp = b.data.attributes.get("sharp_edge")
    assert sharp is not None and any(v.value for v in sharp.data)
    n.bevel(b)
    sharp = b.data.attributes.get("sharp_edge")
    assert sharp is None or not any(v.value for v in sharp.data)
    assert all(p.use_smooth for p in b.data.polygons)


def test_boolean_cut_and_hole():
    target = n.box((0.4, 0.4, 0.4), name="Block")
    cutter = n.cylinder(0.05, 1.0, axis="X")
    n.boolean_cut(target, cutter)
    assert "Cylinder" not in [o.name for o in n.objects()]
    assert n.is_manifold(target)
    n.hole(target, 0.04, axis="Z")
    assert n.is_manifold(target)
    rep = n.verify(target)
    assert rep["pass"], rep["errors"]
    assert target.data.polygons and len(target.data.polygons) > 6


def test_boolean_live_modifier_keeps_cutter_as_helper():
    target = n.box((0.4, 0.4, 0.4), name="Live")
    cutter = n.box((0.1, 1, 0.1), name="Slot")
    n.bevel(target)
    n.boolean_cut(target, cutter, apply=False)
    assert _types(target) == ["BOOLEAN", "BEVEL", "WELD", "WEIGHTED_NORMAL"]
    assert cutter.get("nighty_role") == "cutter" and cutter.hide_render and cutter.parent == target
    assert "Slot" not in [o.name for o in n.objects()]
    assert n.verify(target)["pass"]


def test_solvers_by_version():
    have = n.compat.boolean_solvers()
    assert "EXACT" in have
    assert n.compat.boolean_solver("fast") in ("FAST", "FLOAT")
    assert n.compat.boolean_solver("manifold") in ("MANIFOLD", "EXACT")
    if n.compat.at_least(5):
        assert n.compat.boolean_solver("fast") == "FLOAT" and "MANIFOLD" in have
    else:
        assert n.compat.boolean_solver("fast") == "FAST"


def test_panel_cut_and_vents():
    hull = n.box((0.6, 0.3, 0.4), name="Hull")
    n.panel_cut(hull, "-Y", size=(0.3, 0.2), radius=0.02)
    n.panel_cut(hull, "+X", size=0.15, shape="circle")
    n.vents(hull, "+Z", count=4, slot=(0.2, 0.015))
    n.bevel(hull, width=0.002)
    rep = n.verify(hull)
    assert rep["pass"], rep["errors"]
    assert len(hull.data.polygons) > 50
    b = n.bounds(hull)
    assert abs(b.size.x - 0.6) < 1e-3 and abs(b.size.z - 0.4) < 1e-3
    raises(n.panel_cut, hull, "+Q", contains="side")


def test_mirror_array_radial_apply():
    half = n.box((0.1, 0.1, 0.1), at=(0.1, 0, 0))
    n.mirror(half, "X", apply=True)
    assert not half.modifiers and len(half.data.polygons) == 12
    bar = n.box((0.05, 0.05, 0.3))
    n.array(bar, 3, offset=(0.1, 0, 0), apply=True)
    assert len(bar.data.polygons) == 18
    bolt = n.cylinder(0.01, 0.02, at=(0.2, 0, 0))
    count = len(bolt.data.polygons)
    n.radial(bolt, 6)
    assert len(bolt.data.polygons) == count * 6
    b = n.bounds(bolt)
    assert abs(b.size.x - 0.42) < 2e-3 and abs(b.center.x) < 1e-3


def test_merge_parts_keeps_materials_and_welds():
    red = n.material("Red", "#ff0000")
    blue = n.material("Blue", "#0000ff", metallic=1)
    a = n.box((0.2, 0.2, 0.2), material=red, name="A")
    b = n.box((0.2, 0.2, 0.2), at=(0.2, 0, 0), material=blue, name="B")
    n.bevel(a)
    m = n.merge_parts([a, b], name="AB")
    assert m.name == "AB" and len(n.objects()) == 1
    assert {s.material.name for s in m.material_slots} == {"Red", "Blue"}
    assert not m.modifiers
    # welding the shared face's corners made one shell with inner faces: the check sees it
    rep = n.verify(m)
    assert rep["objects"]["AB"]["faces"] > 12


def test_cleanup_and_manifold():
    b = n.box(0.3)
    me = b.data
    me.vertices.add(1)  # a loose vertex
    me.update()
    assert not n.verify(b)["pass"]
    out = n.cleanup(b)
    assert out["loose_removed"] >= 1
    assert n.verify(b)["pass"]
    o = n.cylinder(0.1, 0.2, caps="none")
    assert not n.is_manifold(o)


def test_displace_and_deform():
    rock = n.sphere(0.3, name="Rock")
    before = [v.co.copy() for v in rock.data.vertices]
    n.displace(rock, 0.05, scale=0.2, seed=1)
    moved = sum(1 for v, b in zip(rock.data.vertices, before) if (v.co - b).length > 1e-6)
    assert moved > len(before) * 0.5
    col = n.cylinder(0.1, 1.0)
    n.deform(col, "taper", 0.5)
    assert any(m.type == "SIMPLE_DEFORM" for m in col.modifiers)


def test_mark_bevel_keeps_later_cuts_crisp():
    blade = n.box((0.6, 0.01, 0.06), name="Blade")
    marked = n.mark_bevel(blade)
    assert marked == 12
    n.boolean_cut(blade, n.box((0.4, 0.004, 0.012), at=(0, -0.005, 0)))
    n.bevel(blade, width=0.002, limit="weight")
    assert blade.modifiers["Bevel"].limit_method == "WEIGHT"
    assert n.verify(blade)["pass"]


def test_safe_bevel_never_leaves_overlaps():
    slab = n.extrude(n.rounded_rect(0.3, 0.2, 0.004), depth=0.05, name="Slab")
    n.vents(slab, "-Y", count=4, slot=(0.12, 0.004), depth=0.003)
    n.bevel(slab, width=0.006)
    width = slab.modifiers["Bevel"].width
    assert width <= 0.006 + 1e-6 and abs(slab["nighty_bevel_width"] - width) < 1e-6
    rep = n.verify(slab)
    assert rep["pass"] and not rep["warnings"], (width, rep["warnings"])
