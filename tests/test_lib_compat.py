# SPDX-License-Identifier: GPL-3.0-or-later
# Version shims behave the same on 4.2 and 5.x.

FRESH_SCENE = True  # tests/run.py: an empty factory scene before each test

import bpy

from _util import n


def test_engine_names():
    sc = bpy.context.scene
    eid = n.compat.set_engine(sc, "eevee")
    assert eid == n.compat.eevee_id() == sc.render.engine
    assert eid == ("BLENDER_EEVEE" if n.compat.at_least(5) else "BLENDER_EEVEE_NEXT")
    assert n.compat.set_engine(sc, "workbench") == "BLENDER_WORKBENCH"
    assert n.compat.set_engine(sc, "cycles") == "CYCLES"
    try:
        n.compat.set_engine(sc, "NOPE")
    except ValueError as e:
        assert "not available" in str(e)
    else:
        raise AssertionError("bad engine accepted")


def test_compositor_tree():
    sc = bpy.context.scene
    tree = n.compat.compositor_tree(sc)
    assert tree is not None and tree.bl_idname == "CompositorNodeTree"
    assert n.compat.compositor_tree(sc) == tree


def test_fcurves_legacy_and_layered():
    obj = n.box(0.1)
    n.compat.keyframe(obj, "location", 1, (0, 0, 0))
    n.compat.keyframe(obj, "location", 10, (0, 0, 1))
    curves = n.compat.fcurves(obj)
    assert len(curves) == 3
    fc = n.compat.find_fcurve(obj, "location", 2)
    assert fc is not None and len(fc.keyframe_points) == 2
    assert n.compat.fcurves(obj.animation_data.action)


def test_materials_and_sockets():
    m = n.material("Glow", "#33ccff", emission="#33ccff", strength=5, variation=0.3)
    p = n.compat.principled(m)
    assert abs(n.compat.socket(p, "Emission").default_value[2] - n.hex_color("#33ccff")[2]) < 1e-6
    assert n.compat.socket(p, "Emission Strength").default_value == 5
    assert n.compat.socket(p, "Specular") is not None  # the old name still finds Specular IOR Level
    assert p.inputs["Base Color"].is_linked  # variation drives the color
    m2 = n.material("Glow", "#ffffff")  # updating removes the variation nodes
    assert not n.compat.principled(m2).inputs["Base Color"].is_linked
    glass = n.material("Glass", (0.9, 1, 0.95), transmission=1, roughness=0.02, alpha=0.6)
    assert glass.surface_render_method == "BLENDED" if hasattr(glass, "surface_render_method") else True


def test_shading_and_misc():
    obj = n.cylinder(0.1, 0.2)
    n.compat.shade_flat(obj.data)
    assert not any(p.use_smooth for p in obj.data.polygons)
    n.compat.shade_smooth(obj.data, angle=30)
    assert all(p.use_smooth for p in obj.data.polygons)
    assert n.compat.sculpt_brush_type_attr() in bpy.types.Brush.bl_rna.properties
    assert n.compat.set_view_transform(bpy.context.scene, "Standard")
    assert n.compat.studio_light("world", ["forest.exr"]) == "forest.exr"
    assert n.compat.studio_light("matcap", ["nope.exr"]).endswith(".exr")


def test_help_lists_and_explains():
    text = n.help()
    for name in ("cylinder", "bevel", "align", "verify", "boolean_cut", "merge_parts", "lathe", "panel_cut"):
        assert f"{name}:" in text
    one = n.help("cylinder")
    assert one.startswith("cylinder(") and "caps" in one
