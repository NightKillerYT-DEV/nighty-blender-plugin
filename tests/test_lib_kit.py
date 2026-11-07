# SPDX-License-Identifier: GPL-3.0-or-later
# The detail kit, the procedural surfaces, the studio render and the hero view.

FRESH_SCENE = True  # tests/run.py: an empty factory scene before each test

import bpy

from _util import n, raises


def _clean(objs, **kw):
    rep = n.verify(objs, **kw)
    assert rep["pass"], rep["errors"]
    return rep


def test_bolt_rows_rings_and_nails():
    plate = n.box((0.4, 0.02, 0.2), at=(0, 0, 0.1), name="Plate")
    row = n.bolts_along((-0.15, -0.0098, 0.17), (0.15, -0.0098, 0.17), 5, radius=0.006, axis="-Y")
    ring = n.bolts_around((0.0, -0.0098, 0.08), 0.05, 6, radius=0.005, axis="-Y", kind="round")
    nl = n.nails([(x, -0.0098, 0.03) for x in (-0.1, 0.1)], axis="-Y")
    rep = _clean([plate, row, ring, nl])
    assert rep["objects"]["Bolts"]["shells"] == 5 and rep["objects"]["Bolts.001"]["shells"] == 6


def test_groove_grille_knurl_inset():
    hull = n.box((0.6, 0.12, 0.4), at=(0, 0, 0.2), name="Hull")
    n.inset(hull, "-Y", amount=0.03, depth=-0.006)
    n.groove(hull, [(-0.25, -0.0605, 0.05), (0.25, -0.0605, 0.05)], width=0.004)
    bars = n.grille(hull, "+Y", center=(0.0, 0.25), size=(0.2, 0.1), count=5, name="Bars")
    n.knurl(hull, "+X", center=(0.0, 0.2), size=(0.08, 0.16), pitch=0.008, depth=0.0015)
    n.bevel(hull, width=0.003)
    rep = _clean([hull, bars])
    assert rep["objects"]["Hull"]["faces"] > 300 and rep["objects"]["Bars"]["shells"] == 5
    stock = n.extrude([(0, 0, 0.004), (0.2, 0, 0.004), (0.2, 0.1, 0.004), (0, 0.1, 0.004)], depth=0.04, name="S")
    raises(n.inset, stock, "-Y", amount=0.02, depth=-0.002, contains="larger than a rounded corner")
    assert n.verify(stock)["pass"]  # left as it was


def test_planks_brackets_cable_stitches_plate():
    core = n.box((0.6, 0.4, 0.4), at=(0, 0, 0.2), name="Core")
    boards = n.planks((0.56, 0.36), count=4, thickness=0.02, plane="XZ", at=(0, -0.21, 0.2), split=1, seed=1)
    assert len({tuple(round(c, 3) for c in p.center) for p in boards.data.polygons}) > 20
    br = n.corner_bracket(core, (1, -1, 1), size=0.08, thickness=0.004, name="Bracket")
    hose = n.cable([(-0.29, 0.0, 0.39), (-0.45, 0.0, 0.25), (-0.29, 0.05, 0.05)], radius=0.008, sag=0.05, clips=2,
                   name="Hose")
    st = n.stitches([(-0.2, -0.2005, 0.39), (0.2, -0.2005, 0.39)], name="Stitch")
    badge = n.plate((0.1, 0.04), text="NB", axis="-Y", at=(0.1, -0.2195, 0.08), name="Badge")
    objs = [core, boards, br, n.get("BracketNails"), hose, n.get("HoseClips"), st, badge, n.get("BadgeText")]
    _clean(objs)
    assert n.bounds(br).max.z > 0.4 and n.bounds(br).max.x > 0.3


def test_stylized_helpers():
    toy = n.rounded_box((0.2, 0.2, 0.2), radius=0.03, at=(0, 0, 0.1), name="Toy")
    n.taper(toy, 0.3)
    shell = n.outline(toy, 0.003)
    assert shell.get("nighty_role") == "outline" and shell.parent == toy
    assert "ToyOutline" not in [o.name for o in n.objects()]  # verify / look skip it as a helper
    _clean([toy])
    coin = n.cylinder(0.05, 0.02, at=(0.3, 0, 0.01), name="Coin")
    mod = n.chunky(coin)
    assert mod.segments == 4
    c2 = n.box(0.1, at=(0.6, 0, 0.05))
    assert n.chamfer(c2).segments == 1
    c3 = n.box(0.1, at=(0.9, 0, 0.05))
    n.subd_crisp(c3)
    assert [m.type for m in c3.modifiers][-2:] == ["SUBSURF", "WEIGHTED_NORMAL"]


def test_surfaces_share_the_smart_material_library():
    import json
    kinds = [k for k, *_ in n.surfaces()]
    assert {"steel", "gunmetal", "anodized_aluminum", "polymer", "wood", "gold", "glass", "emissive"} <= set(kinds)
    for kind in kinds:
        for style in ("realistic", "stylized", "painted"):
            m = n.surface(f"S {kind} {style}", kind, style=style)
            params = json.loads(m["nighty"])
            assert params["kind"] == kind and m.node_tree
            p = next(nd for nd in m.node_tree.nodes if nd.type == "BSDF_PRINCIPLED")
            met = p.inputs["Metallic"]
            assert met.is_linked or met.default_value in (0.0, 1.0)   # the bake's contract: metal is 0 or 1
    assert n.surface("Anod", "anodized", color="#1d1e21")["nighty_surface"] == "anodized_aluminum"
    wood = n.surface("Pine", "wood", color="#a77d50", grain="Y")
    assert json.loads(wood["nighty"])["kind"] == "wood"
    neon = n.surface("Neon", "glow", color="#2fe0ff", glow=12)
    p = next(nd for nd in neon.node_tree.nodes if nd.type == "BSDF_PRINCIPLED")
    assert abs(p.inputs["Emission Strength"].default_value - 12) < 1e-6
    raises(n.surface, "Bad", "plutonium", contains="unknown kind")
    raises(n.surface, "Bad", "steel", style="cubist", contains="style must be")
    again = n.surface("Pine", "wood", color="#ff0000")
    assert again.name == "Pine"   # rebuilt in place
    ob = n.box(0.1)
    n.paint(ob, wood)
    from nighty_blender.nighty import materials
    assert materials.part_materials([ob])[ob.name][0]["kind"] == "wood"   # the texture tools read it


def test_studio_render_and_hero_view_leave_nothing_behind():
    b = n.box((0.8, 0.05, 0.1), at=(0, 0, 0.05), name="Long")
    n.paint(b, n.surface("Long Metal", "anodized"))
    before = (len(bpy.data.objects), len(bpy.data.lights), len(bpy.data.meshes), len(bpy.data.worlds))
    sc = bpy.context.scene
    vt = sc.view_settings.view_transform
    pngs, poses = n.view.look([b], views=["hero"], mode="material", size=160, height=100, labels=False)
    import struct
    w, h = struct.unpack(">II", pngs[0][16:24])
    assert (w, h) == (160, 100)
    assert poses[0]["projection"] == "perspective" and poses[0]["lens_mm"] == 70.0
    assert n.view.hero_angles(n.bounds(b).size) == (27.0, 10.0)
    after = (len(bpy.data.objects), len(bpy.data.lights), len(bpy.data.meshes), len(bpy.data.worlds))
    assert after == before and sc.view_settings.view_transform == vt


def test_view_labels_draw_every_letter_and_digit():
    from nighty_blender.nighty import view
    missing = [c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/-.:+()%=_," if c not in view._FONT]
    assert not missing, missing
    assert all(len(bits) == 15 and set(bits) <= {"0", "1"} for bits in view._FONT.values())
