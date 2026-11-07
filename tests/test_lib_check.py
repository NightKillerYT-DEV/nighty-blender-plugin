# SPDX-License-Identifier: GPL-3.0-or-later
# verify finds what it must: open / non-manifold edges, flipped and inside-out faces, floating parts, loose bits,
# degenerate faces, scale, UVs, self-intersections; measure / distance / compare give meters.

FRESH_SCENE = True  # tests/run.py: an empty factory scene before each test

import bmesh
import bpy

from _util import n


def _mesh(name, build):
    bm = bmesh.new()
    build(bm)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _cube(bm, size=1.0, at=(0, 0, 0)):
    from mathutils import Matrix
    bmesh.ops.create_cube(bm, size=size, matrix=Matrix.Translation(at))


def test_clean_box_passes():
    rep = n.verify(n.box(0.5))
    assert rep["pass"] and not rep["warnings"], rep
    r = rep["objects"]["Box"]
    assert r["quads"] == 6 and r["shells"] == 1 and r["symmetry"]["score"] == 1.0 and r["scale_applied"]
    assert abs(r["volume"] - 0.125) < 1e-6


def test_open_and_non_manifold():
    plane = n.plane(1.0)
    rep = n.verify(plane)
    assert not rep["pass"] and "open edges" in rep["errors"][0]
    assert n.verify(plane, allow_open=True)["pass"]

    def fin(bm):
        _cube(bm)
        a = [v for v in bm.verts if v.co.z > 0 and v.co.x > 0]
        top = bm.verts.new((a[0].co.x + 1, a[0].co.y, a[0].co.z))
        top2 = bm.verts.new((a[1].co.x + 1, a[1].co.y, a[1].co.z))
        bm.faces.new((a[0], a[1], top2, top))
    rep = n.verify(_mesh("Fin", fin), allow_open=True)
    assert rep["objects"]["Fin"]["non_manifold_edges"] == 1 and not rep["pass"]


def test_flipped_and_inside_out():
    def one_flipped(bm):
        _cube(bm)
        bm.faces.ensure_lookup_table()
        bmesh.ops.reverse_faces(bm, faces=[bm.faces[0]])
    rep = n.verify(_mesh("Flip", one_flipped))
    assert rep["objects"]["Flip"]["flipped_faces"] == 4 and not rep["pass"]

    def inside_out(bm):
        _cube(bm)
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    rep = n.verify(_mesh("Inv", inside_out))
    assert rep["objects"]["Inv"]["inverted_shells"] == 1 and not rep["pass"]
    n.cleanup(bpy.data.objects["Inv"])
    assert n.verify(bpy.data.objects["Inv"])["pass"]


def test_floating_parts_between_objects_and_inside_one():
    body = n.box((0.4, 0.4, 0.4), at=(0, 0, 0.2), name="Body")
    lid = n.box((0.4, 0.4, 0.05), at=(0, 0, 0.6), name="Lid")  # 0.175 m above the body
    rep = n.verify([body, lid])
    assert not rep["pass"] and rep["floating"] and rep["floating"][0]["object"] == "Lid"
    n.align(lid, body, "on_top")
    assert n.verify([body, lid])["pass"]
    assert n.verify([body, lid], allow_floating=[])["pass"]

    def two_shells(bm):
        _cube(bm, 0.2)
        _cube(bm, 0.05, at=(0, 0, 0.5))
    rep = n.verify(_mesh("Two", two_shells))
    assert rep["floating"] and not rep["pass"]

    def touching(bm):
        _cube(bm, 0.2)
        _cube(bm, 0.05, at=(0, 0, 0.12))  # pokes into the first: fine
    assert n.verify(_mesh("Touch", touching))["pass"]


def test_two_grounded_assets_are_not_floating():
    a = n.box(0.5, at=(0, 0, 0.25))
    b = n.box(0.3, at=(2, 0, 0.15))
    assert n.verify([a, b])["pass"]


def test_loose_degenerate_scale_budget():
    def loose(bm):
        _cube(bm)
        bm.verts.new((3, 3, 3))
    rep = n.verify(_mesh("Loose", loose))
    assert rep["objects"]["Loose"]["loose_verts"] == 1 and not rep["pass"]

    def zero(bm):
        _cube(bm)
        c = (0.0, 0.0, 0.5)
        v1 = bm.verts.new(c)
        v2 = bm.verts.new(c)
        v3 = bm.verts.new(c)
        bm.faces.new((v1, v2, v3))
    rep = n.verify(_mesh("Zero", zero), allow_open=True)
    assert rep["objects"]["Zero"]["zero_area_faces"] >= 1 and not rep["pass"]

    b = n.box(0.5, name="Scaled")
    b.scale = (2, 2, 2)
    rep = n.verify(b)
    assert rep["pass"] and any("not applied" in w for w in rep["warnings"])
    b.scale = (-1, 1, 1)
    assert not n.verify(b)["pass"]
    s = n.sphere(0.3, name="Ball")
    rep = n.verify(s, budget=100)
    assert not rep["pass"] and "budget" in rep["errors"][-1]


def test_uv_overlap_and_stretch():
    def stacked(bm):
        _cube(bm)
        uv = bm.loops.layers.uv.new("UVMap")
        for f in bm.faces:
            for loop, co in zip(f.loops, [(0, 0), (1, 0), (1, 1), (0, 1)]):
                loop[uv].uv = co
    rep = n.verify(_mesh("Stack", stacked))
    r = rep["objects"]["Stack"]
    assert r["uv"] and r["uv_overlap"] > 0.9 and any("overlap" in w for w in rep["warnings"])

    def grid(bm):
        bmesh.ops.create_grid(bm, x_segments=4, y_segments=4, size=0.5)
        uv = bm.loops.layers.uv.new("UVMap")
        for f in bm.faces:
            for loop in f.loops:
                loop[uv].uv = (loop.vert.co.x + 0.5, loop.vert.co.y + 0.5)
    rep = n.verify(_mesh("Grid", grid), allow_open=True)
    r = rep["objects"]["Grid"]
    assert r["uv_overlap"] == 0 and r["uv_stretch"] < 0.01 and abs(r["uv_coverage"] - 1.0) < 0.02


def test_self_intersection_and_symmetry():
    knot = n.torus(0.1, 0.15, name="Knot")  # the tube passes through itself in the middle
    r = n.verify(knot)["objects"]["Knot"]
    assert r["self_intersections"] > 0
    lop = n.extrude([(0, 0), (1, 0), (1, 0.2), (0.2, 1)], depth=0.1, name="Lop")
    r = n.verify(lop)["objects"]["Lop"]
    assert r["symmetry"]["score"] < 0.8


def test_measure_distance_compare():
    a = n.box((1, 0.5, 0.2), at=(0, 0, 0.1), name="A")
    b = n.box((0.2, 0.2, 0.2), at=(1.0, 0, 0.1), name="B")
    m = n.measure([a, b])
    assert m["A"]["size"] == [1.0, 0.5, 0.2] and m["all"]["size"][0] == 1.6
    d = n.distance(a, b)
    assert abs(d["surface_distance"] - 0.4) < 1e-3 and not d["touching"]
    assert abs(d["gap_xyz"][0] - 0.4) < 1e-6
    n.align(b, a, "right")
    assert n.distance(a, b)["touching"]
    ghost = n.box((1.1, 0.5, 0.2), at=(0, 0, 0.1), name="Ghost")
    c = n.compare(a, ghost)
    assert abs(c["size_ratio"][0] - 1 / 1.1) < 1e-3 and c["bounds_iou"] > 0.85
    assert c["chamfer_share"] < 0.05


def test_flat_contact_is_touching_and_same_plane_is_warned():
    frame = n.box((0.1, 0.4, 0.05), at=(-0.5, 0, 0.025), name="FrameL")
    frame2 = n.box((0.1, 0.4, 0.05), at=(0.5, 0, 0.025), name="FrameR")
    slat = n.box((1.2, 0.08, 0.02), at=(0, 0, 0.06), name="Slat")  # lies on both frames, no shared points
    rep = n.verify([frame, frame2, slat])
    assert rep["pass"] and not rep["floating"], rep["errors"]
    cap = n.box((0.2, 0.2, 0.1), at=(2, 0, 0.05), name="Cap")
    twin = n.box((0.1, 0.1, 0.1), at=(2.02, 0, 0.05), name="Twin")  # same top and bottom planes, overlapping
    rep = n.verify([cap, twin])
    assert any("same plane" in w for w in rep["warnings"]), rep["warnings"]
    side = n.box((0.2, 0.2, 0.1), at=(3, 0, 0.05), name="SideA")
    side2 = n.box((0.2, 0.2, 0.1), at=(3.2, 0, 0.05), name="SideB")  # flush neighbors: no overlap, no warning
    rep = n.verify([side, side2])
    assert not any("same plane" in w for w in rep["warnings"]), rep["warnings"]
