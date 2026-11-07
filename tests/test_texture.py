# SPDX-License-Identifier: GPL-3.0-or-later
"""Texturing tests (b-texture): materials, decals, stylize, bake, exports, checks, options, tools."""

import atexit
import json
import os
import shutil
import struct
import tempfile
import time

import bpy
import numpy as np

import texture_scene as ts
from nighty_blender.nighty import bake, export, materials, presets
from nighty_blender.nighty.bake import channels, core, maps, png, uvraster, verify
from nighty_blender.nighty.export import core as ecore
from nighty_blender.nighty.materials import compat, decals, library
from nighty_blender.nighty.materials import stylize as st

FRESH_SCENE = True   # the shared test runner gives each test an empty factory scene

_TMP = []


def tmpdir():
    d = tempfile.mkdtemp(prefix="nb_test_")
    _TMP.append(d)
    return d


def _cleanup():
    while _TMP:
        shutil.rmtree(_TMP.pop(), ignore_errors=True)


atexit.register(_cleanup)   # also when only some tests ran


def approx(a, b, tol):
    assert abs(a - b) <= tol, f"{a} != {b} (+-{tol})"


def _gun():
    parts = ts.make_gun()
    materials.assign(ts.GUN_MATERIALS, wear=0.45, dirt=0.35)
    return parts


# ----------------------------------------------------------------------------------------------- library

def test_library_metallic_is_binary_everywhere():
    for key, m in library.MATERIALS.items():
        assert m["metallic"] in (0, 1), key
        assert m["worn"]["metallic"] in (0, 1), key
        assert m["dirt"].get("metallic", 0) in (0, 1), key
        assert 0 <= m["rough"] <= 1, key
    assert library.resolve("Gun Metal") == "gunmetal"
    assert library.resolve("aluminium") == "aluminum"
    assert library.resolve("glow") == "emissive"
    assert library.resolve("unobtainium") is None
    assert len(library.describe()) >= 20


def test_assign_materials_per_part_and_instant_edit():
    parts = ts.make_gun()
    t = time.time()
    rows = materials.assign(ts.GUN_MATERIALS, wear=0.4, dirt=0.3)
    assert time.time() - t < 5.0 * float(__import__("os").environ.get("NIGHTY_TEST_SLOW", "3" if __import__("os").environ.get("CI") else "1"))
    assert len(rows) == len(ts.GUN_MATERIALS)
    for o in parts.values():
        m = o.material_slots[0].material
        assert m.name.startswith("NB "), m.name
        p = compat.principled_of(m)
        assert p is not None, m.name
        params = json.loads(m["nighty"])
        assert params["metallic"] in (0, 1)
        # metallic is a constant 0/1 or a hard switch between 0 and 1
        met = compat.socket(p.inputs, "Metallic")
        if not met.is_linked:
            assert met.default_value in (0.0, 1.0)
    # a small edit: the same material is rebuilt in place, instantly
    mag = parts["Magazine"]
    before = mag.material_slots[0].material
    t = time.time()
    materials.assign({"Magazine": {"material": "painted_metal", "color": "#8a2020"}})
    assert time.time() - t < 1.0 * float(__import__("os").environ.get("NIGHTY_TEST_SLOW", "3" if __import__("os").environ.get("CI") else "1"))
    assert mag.material_slots[0].material is before
    assert json.loads(before["nighty"])["tint"] == "#8a2020"
    try:
        materials.assign({"Magazine": "unobtainium"})
        raise AssertionError("unknown material accepted")
    except ValueError as e:
        assert "known" in str(e)


def test_metallic_switch_inputs_are_zero_or_one():
    ts.make_gun()
    materials.assign({"Magazine": "painted_metal", "Receiver": "rusty_metal"}, wear=0.5, dirt=0.5)
    for name in ("Magazine", "Receiver"):
        m = bpy.data.objects[name].material_slots[0].material
        p = compat.principled_of(m)
        node = compat.socket(p.inputs, "Metallic").links[0].from_node
        seen = 0
        while node.bl_idname == "ShaderNodeMix":
            fac = compat.socket(node.inputs, "Factor", kind="VALUE")
            assert fac.is_linked and fac.links[0].from_node.bl_idname == "ShaderNodeMath"
            assert fac.links[0].from_node.operation == "GREATER_THAN"   # a hard step, never a blend
            b = compat.socket(node.inputs, "B", kind="VALUE")
            assert b.default_value in (0.0, 1.0)
            a = compat.socket(node.inputs, "A", kind="VALUE")
            seen += 1
            if a.is_linked:
                node = a.links[0].from_node
            else:
                assert a.default_value in (0.0, 1.0)
                break
        assert seen >= 1


# ----------------------------------------------------------------------------------------------- small pieces

def test_png_round_trip():
    d = tmpdir()
    rng = np.random.default_rng(1)
    for shape, dtype in (((7, 5), np.uint8), ((6, 9, 3), np.uint8), ((4, 4, 4), np.uint8), ((5, 3), np.uint16),
                         ((3, 8, 3), np.uint16)):
        top = 255 if dtype == np.uint8 else 65535
        a = rng.integers(0, top + 1, size=shape).astype(dtype)
        p = os.path.join(d, "x.png")
        png.write(p, a)
        b = png.read(p)
        assert b.shape[:2] == a.shape[:2] and np.array_equal(b.reshape(a.shape), a)
        w, h, depth, ch = png.read_header(p)
        assert (w, h) == (a.shape[1], a.shape[0]) and depth == (8 if dtype == np.uint8 else 16)
    # Blender reads our files the same way
    a = (np.arange(16 * 16 * 3) % 256).astype(np.uint8).reshape(16, 16, 3)
    p = os.path.join(d, "y.png")
    png.write(p, a)
    img = bpy.data.images.load(p)
    img.colorspace_settings.name = "Non-Color"
    px = np.empty(16 * 16 * 4, np.float32)
    img.pixels.foreach_get(px)
    px = (px.reshape(16, 16, 4)[::-1, :, :3] * 255 + 0.5).astype(np.uint8)
    assert np.array_equal(px, a)


def test_map_operations():
    img = np.zeros((16, 16, 3), np.float32)
    filled = np.zeros((16, 16), bool)
    img[4:8, 4:8] = 0.7
    filled[4:8, 4:8] = True
    out, f2 = maps.dilate(img, filled, 2)
    assert f2.sum() > filled.sum() and abs(out[3, 5, 0] - 0.7) < 1e-6
    full = maps.fill_rest(out, f2)
    assert np.all(np.abs(full - 0.7) < 1e-5)
    assert set(np.unique(maps.snap_binary(np.array([0.1, 0.49, 0.5, 0.9])))) == {0.0, 1.0}
    n = np.array([[[0.5, 0.8, 0.9]]], np.float32)
    approx(float(maps.flip_green(n)[0, 0, 1]), 0.2, 1e-6)
    approx(float(maps.linear_to_srgb(np.array([0.5]))[0]), 0.7354, 1e-3)
    big = np.ones((8, 8, 1), np.float32)
    assert maps.resize(big, 4).shape == (4, 4, 1)
    p = maps.pack(np.zeros((2, 2)), np.ones((2, 2)), None, np.full((2, 2), 0.25))
    assert p.shape == (2, 2, 4) and p[0, 0, 1] == 1 and p[0, 0, 3] == 0.25
    assert maps.size_of("2K") == 2048 and maps.size_of(1024) == 1024


def test_uv_overlap_detection_and_atlas():
    objs = []
    for i in range(3):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(i * 2.0, 0, 0))
        objs.append(bpy.context.active_object)
    rep = uvraster.layout_report(objs, n=128)
    assert rep["overlap"] > 0.5, rep            # three cubes, the same UVs
    need, _ = core.needs_atlas(objs)
    assert need
    core.make_atlas(objs, 512, 4)
    rep2 = uvraster.layout_report(objs, n=256, layer_of=lambda o: core.ATLAS)
    assert rep2["overlap"] < 0.002 and rep2["outside"] == 0, rep2
    one = uvraster.layout_report(objs[:1], n=128, layer_of=lambda o: core.ATLAS)
    assert one["covered"] > 0.02


def test_channel_rewire_keeps_mixes():
    m = compat.new_material("Mixed")
    t = m.node_tree
    t.nodes.clear()
    out = t.nodes.new("ShaderNodeOutputMaterial")
    a = t.nodes.new("ShaderNodeBsdfPrincipled")
    b = t.nodes.new("ShaderNodeBsdfPrincipled")
    compat.socket(a.inputs, "Metallic").default_value = 1.0
    compat.socket(b.inputs, "Metallic").default_value = 0.0
    compat.socket(a.inputs, "Roughness").default_value = 0.2
    mix = t.nodes.new("ShaderNodeMixShader")
    t.links.new(a.outputs[0], mix.inputs[1])
    t.links.new(b.outputs[0], mix.inputs[2])
    t.links.new(mix.outputs[0], compat.socket(out.inputs, "Surface"))
    c = m.copy()
    channels.rewire(c.node_tree, "metallic")
    ems = [n for n in c.node_tree.nodes if n.type == "EMISSION"]
    assert len(ems) == 2 and not [n for n in c.node_tree.nodes if n.type == "BSDF_PRINCIPLED"]
    vals = sorted(e.inputs[0].default_value[0] for e in ems)
    assert vals == [0.0, 1.0]
    assert [n for n in c.node_tree.nodes if n.type == "MIX_SHADER"][0].inputs[1].is_linked
    d = m.copy()
    channels.rewire(d.node_tree, "normal")
    assert len([n for n in d.node_tree.nodes if n.type == "BSDF_DIFFUSE"]) == 2


# ----------------------------------------------------------------------------------------------- bake (in process)

def _flat_cube(color_lin=(0.5, 0.25, 0.1), metallic=0.0, rough=0.4):
    bpy.ops.mesh.primitive_cube_add(size=1)
    o = bpy.context.active_object
    m = compat.new_material("Flat")
    p = compat.principled_of(m)
    compat.socket(p.inputs, "Base Color").default_value = color_lin + (1.0,)
    compat.socket(p.inputs, "Metallic").default_value = metallic
    compat.socket(p.inputs, "Roughness").default_value = rough
    o.data.materials.append(m)
    return o


def test_bake_color_management_is_exact():
    """A known linear color must land in the PNG as its exact sRGB value; data maps are raw."""
    o = _flat_cube((0.5, 0.25, 0.1), metallic=1.0, rough=0.4)
    d = tmpdir()
    m = core.bake_asset({"objects": [o.name], "size": 128, "out_dir": d, "name": "Flat",
                         "maps": ["base_color", "roughness", "metallic", "normal"], "device": "CPU"})
    cov = verify.coverage([o], m["uv_layer"], 128)
    base = png.read(os.path.join(d, m["maps"]["base_color"])).astype(np.float32)[cov]
    want = maps.linear_to_srgb(np.array([0.5, 0.25, 0.1])) * 255
    assert np.all(np.abs(np.median(base, axis=0) - want) <= 1.5), (np.median(base, axis=0), want)
    rough = png.read(os.path.join(d, m["maps"]["roughness"])).astype(np.float32)[..., 0][cov]
    approx(float(np.median(rough)), 0.4 * 255, 1.5)
    met = png.read(os.path.join(d, m["maps"]["metallic"]))[..., 0]
    assert set(np.unique(met).tolist()) <= {0, 255} and np.median(met[cov]) == 255
    nrm = png.read(os.path.join(d, m["maps"]["normal"])).astype(np.float32)[cov] / 255
    assert np.all(np.abs(np.median(nrm, axis=0) - [0.5, 0.5, 1.0]) < 0.02)
    assert png.read_header(os.path.join(d, m["maps"]["roughness"]))[3] == 1   # true grayscale
    assert sum(m["unbaked_pixels"].values()) == 0
    # the scene is as before (materials back, no helper modifier)
    assert o.material_slots[0].material.name == "Flat"
    assert not [md for md in o.modifiers if md.name == "NB Triangulate"]


def _slope_plane():
    """A plane whose material bumps up toward +Y (+V): its normal tilts toward -V."""
    bpy.ops.mesh.primitive_plane_add(size=1)
    o = bpy.context.active_object
    m = compat.new_material("Slope")
    p = compat.principled_of(m)
    g = compat.Graph(m.node_tree)
    sep = g.node("ShaderNodeSeparateXYZ")
    g.set(sep.inputs[0], g.coords("Object"))
    g.set(compat.socket(p.inputs, "Normal"), g.bump(sep.outputs[1], 1.0, 0.3))
    o.data.materials.append(m)
    return o


def test_normal_map_is_opengl_and_unreal_gets_directx():
    o = _slope_plane()
    d = tmpdir()
    m = core.bake_asset({"objects": [o.name], "size": 64, "out_dir": d, "name": "Slope", "maps": ["normal"],
                         "device": "CPU"})
    n = png.read(os.path.join(d, m["maps"]["normal"])).astype(np.float32) / 255
    cov = verify.coverage([o], m["uv_layer"], 64)
    g = float(np.median(n[..., 1][cov]))
    assert g < 0.45, g      # OpenGL: green = +V; the surface faces away from +V
    tex, _ = ecore.engine_textures("unreal", m, d, os.path.join(d, "ue"), "Slope")
    ue = png.read(tex["normal"]).astype(np.float32) / 255
    assert float(np.median(ue[..., 1][cov])) > 0.55     # DirectX: green flipped
    tex2, _ = ecore.engine_textures("roblox", m, d, os.path.join(d, "rb"), "Slope")
    rb = png.read(tex2["normal"]).astype(np.float32) / 255
    approx(float(np.median(rb[..., 1][cov])), g, 0.01)   # Roblox: OpenGL


def test_high_poly_normal_bake():
    bpy.ops.mesh.primitive_plane_add(size=1)
    low = bpy.context.active_object
    low.name = "Panel"
    low.data.materials.append(compat.new_material("PanelMat"))
    bpy.ops.mesh.primitive_plane_add(size=1)
    hi = bpy.context.active_object
    hi.name = "Panel_high"
    me = hi.data
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=40, use_grid_fill=True)
    for v in bm.verts:   # a ridge along X in the middle
        v.co.z = 0.04 * max(0.0, 1.0 - abs(v.co.y) / 0.15)
    bm.to_mesh(me)
    bm.free()
    assert bake.find_high([low]) == {"Panel": hi}
    d = tmpdir()
    m = core.bake_asset({"objects": ["Panel"], "high": {"Panel": "Panel_high"}, "size": 128, "out_dir": d,
                         "name": "Panel", "maps": ["base_color", "normal", "ao"], "device": "CPU"})
    n = png.read(os.path.join(d, m["maps"]["normal"])).astype(np.float32) / 255
    cov = verify.coverage([low], m["uv_layer"], 128)
    dev = np.abs(n[..., 1] - 0.5)[cov]
    assert dev.max() > 0.05, dev.max()          # the ridge shows in the low poly's normal map
    assert sum(m["unbaked_pixels"].values()) < cov.sum() * 0.01


def test_bake_gun_maps_and_checks():
    parts = _gun()
    d = tmpdir()
    m = core.bake_asset({"objects": list(parts), "size": 256, "out_dir": d, "name": "Gun", "device": "CPU"})
    assert m["atlas"] and m["uv_layer"] == core.ATLAS
    for key in ("base_color", "roughness", "metallic", "normal", "ao", "emission", "opacity"):
        assert key in m["maps"], key
        w, h, _, _ = png.read_header(os.path.join(d, m["maps"][key]))
        assert (w, h) == (256, 256)
    checks = {c["name"]: c for c in verify.check_maps(m, d, list(parts.values()), "pbr")}
    for name in ("sizes", "metallic_binary", "normal_valid", "unbaked_pixels", "baked_lighting", "seams", "blur"):
        assert checks[name]["ok"], (name, checks[name])
    # missed texels show in every map baked from the high poly: counted once, not once per map
    limit = int(verify.coverage(list(parts.values()), m["uv_layer"], 256).sum() * 0.0005)
    few = dict(m, unbaked_pixels={k: max(0, limit - 1) for k in m["maps"]})
    assert {c["name"]: c for c in verify.check_maps(few, d, list(parts.values()), "pbr")}["unbaked_pixels"]["ok"]
    many = dict(m, unbaked_pixels={k: limit + 5 for k in m["maps"]})
    assert not {c["name"]: c for c in verify.check_maps(many, d, list(parts.values()), "pbr")}["unbaked_pixels"]["ok"]
    # the checks catch the classic AI-texture faults
    base_path = os.path.join(d, m["maps"]["base_color"])
    good = png.read(base_path).astype(np.float32) / 255
    ao = png.read(os.path.join(d, m["maps"]["ao"])).astype(np.float32)[..., :1] / 255
    shaded = np.clip(good * (ao ** 2.5) * 1.2, 0, 1)             # lighting baked into the colors
    png.write(base_path, png.to_uint(shaded))
    c = {c["name"]: c for c in verify.check_maps(m, d, list(parts.values()), "pbr")}
    assert not c["baked_lighting"]["ok"], c["baked_lighting"]
    blurred = good.copy()
    for _ in range(6):
        blurred = (blurred + maps._shift(blurred, 0, 1) + maps._shift(blurred, 0, -1) +
                   maps._shift(blurred, 1, 0) + maps._shift(blurred, -1, 0)) / 5
    png.write(base_path, png.to_uint(blurred))
    c = {c["name"]: c for c in verify.check_maps(m, d, list(parts.values()), "pbr")}
    assert not c["blur"]["ok"], c["blur"]
    met_path = os.path.join(d, m["maps"]["metallic"])
    png.write(met_path, np.full((256, 256), 128, np.uint8))
    c = {c["name"]: c for c in verify.check_maps(m, d, list(parts.values()), "pbr")}
    assert not c["metallic_binary"]["ok"]


# ----------------------------------------------------------------------------------------------- decals / stylize

def test_text_decal_is_sharp_and_projected():
    from nighty_blender.nighty.materials import textraster
    rgba = textraster.text_rgba("NIGHTY 7", height_px=64, color="#ffcc00", outline=0.08)
    a = rgba[..., 3]
    assert rgba.shape[0] > 60 and rgba.shape[1] > rgba.shape[0] * 2
    soft = float(((a > 0.05) & (a < 0.95)).sum()) / max(float((a > 0.5).sum()), 1)
    assert soft < 0.6, soft                     # crisp letters: few half-covered pixels
    parts = _gun()
    d = tmpdir()
    res = decals.add_decal(parts["Receiver"], text="NB-7", side="front", size=0.08, color="#f0f0f0", folder=d)
    proj = bpy.data.objects[res["projector"]]
    assert proj.empty_display_type == "IMAGE" and proj.parent is parts["Receiver"]
    mat = parts["Receiver"].material_slots[0].material
    assert any(n.type == "GROUP" and n.node_tree.name.startswith(decals.PREFIX) for n in mat.node_tree.nodes)
    assert decals.list_decals(parts["Receiver"])[0]["name"] == "NB-7"
    assert res["depth_m"] < 0.05                # never through the 5 cm receiver
    decals.remove_decal("NB-7")
    assert bpy.data.objects.get(res["projector"]) is None
    assert not any(n.type == "GROUP" and n.node_tree and n.node_tree.name.startswith(decals.PREFIX)
                   for n in mat.node_tree.nodes)


def test_image_decal_bakes_in():
    o = _flat_cube((0.05, 0.05, 0.05), 0.0, 0.5)
    o.name = "Box"
    d = tmpdir()
    red = np.zeros((32, 32, 4), np.float32)
    red[..., 0] = 1.0
    red[..., 3] = 1.0
    p = os.path.join(d, "red.png")
    png.write(p, png.to_uint(red))
    decals.add_decal(o, image_path=p, side="front", size=0.5, roughness=0.2, folder=d)
    m = core.bake_asset({"objects": ["Box"], "size": 128, "out_dir": d, "name": "Box",
                         "maps": ["base_color", "roughness"], "device": "CPU"})
    # the front face center, through the UVs: red there, dark elsewhere
    me = o.data
    dg = bpy.context.evaluated_depsgraph_get()
    ok, loc, nrm, face = o.ray_cast((0, -2, 0), (0, 1, 0), depsgraph=dg)
    assert ok
    lay = me.uv_layers[m["uv_layer"]] if m["uv_layer"] else me.uv_layers.active
    poly = me.polygons[face]
    uv = np.mean([lay.data[li].uv[:] for li in poly.loop_indices], axis=0)
    base = png.read(os.path.join(d, m["maps"]["base_color"])).astype(np.float32) / 255
    s = verify._sample(base, np.array([uv], np.float32))[0]
    assert s[0] > 0.9 and s[1] < 0.1, s
    rough = png.read(os.path.join(d, m["maps"]["roughness"])).astype(np.float32) / 255
    r = verify._sample(rough, np.array([uv], np.float32))[0][0]
    approx(float(r), 0.2, 0.03)
    cov = verify.coverage([o], m["uv_layer"], 128)
    assert float(np.median(base[..., 0][cov])) < 0.4    # the rest of the box stays dark


def test_stylized_materials():
    parts = ts.make_crate()
    rows = materials.assign(ts.CRATE_MATERIALS, style="stylized", wear=0.3)
    assert all(r["style"] == "stylized" for r in rows)
    for o in parts.values():
        m = o.material_slots[0].material
        assert any(n.type == "GROUP" and n.node_tree.name == st.GROUP for n in m.node_tree.nodes)
        p = compat.principled_of(m)
        assert compat.socket(p.inputs, "Metallic").default_value == 0.0
    # stylize on a foreign material wraps it
    bpy.ops.mesh.primitive_cube_add(size=0.3, location=(2, 0, 0))
    other = bpy.context.active_object
    other.data.materials.append(compat.new_material("Someone's"))
    res = st.stylize([other], {"edges": 0.9, "steps": 2})
    assert res[0]["stylized"]
    d = tmpdir()
    m = core.bake_asset({"objects": list(parts), "size": 128, "out_dir": d, "name": "Crate", "device": "CPU",
                         "maps": ["base_color", "roughness", "metallic", "ao"], "style": "stylized"})
    checks = {c["name"]: c for c in verify.check_maps(m, d, list(parts.values()), "stylized")}
    assert checks["baked_lighting"]["limit"] == "info" and checks["metallic_binary"]["ok"]
    rough = png.read(os.path.join(d, m["maps"]["roughness"]))[..., 0]
    assert rough.std() < 25          # flat roughness


# ----------------------------------------------------------------------------------------------- options

def test_options_menu_presets_and_store():
    menu = presets.menu()
    keys = [q["key"] for q in menu["questions"]]
    for k in ("mesh", "detail", "textures", "texture_type", "size", "made_for", "faces"):
        assert k in keys
    labels = [p["label"] for p in menu["presets"]]
    for want in ("Stylized weapon", "Realistic weapon", "Roblox prop", "Low-poly mobile", "Character",
                 "Environment piece"):
        assert want in labels
    o = presets.resolve(preset="Roblox prop")
    assert o["made_for"] == "roblox" and o["size"] == "1K" and o["faces"] == 1500 and o["mesh"] == "triangles"
    o = presets.resolve({"detail": "high", "faces": 7777, "textures": "Hand-painted", "size": "4096"},
                        preset="realistic_weapon")
    assert o["faces"] == 7777 and o["faces_exact"] and o["textures"] == "stylized" and o["size"] == "4K"
    assert o["texturing"]["style"] == "stylized"
    for bad in ({"mesh": "voxels"}, {"size": "3K"}, {"faces": 3}):
        try:
            presets.resolve(bad)
            raise AssertionError(f"accepted {bad}")
        except ValueError:
            pass
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    presets.store(presets.resolve({"made_for": "unity"}), [cube])
    assert presets.current()["made_for"] == "unity" and presets.current(cube)["made_for"] == "unity"
    assert presets.maps_for({"textures": "color"}) == ["base_color", "emission", "opacity"]


# ----------------------------------------------------------------------------------------------- jobs, exports

def _glb_json(path):
    with open(path, "rb") as f:
        data = f.read()
    assert data[:4] == b"glTF"
    n = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + n])


def test_worker_bake_then_export_every_engine():
    d = tmpdir()
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(d, "crate.blend"))
    parts = ts.make_crate()
    materials.assign(ts.CRATE_MATERIALS, wear=0.4, dirt=0.4)
    objs = list(parts.values())
    res = bake.run_steps(bake.bake_steps(objs, size=512, name="Crate", device="CPU"), tick=0.2, timeout=900)
    folder = res["folder"]
    assert folder.startswith(os.path.join(d, "textures"))
    assert res["material"] == "NB Baked · Crate"
    for o in objs:
        assert o.material_slots[0].material.name == "NB Baked · Crate"
        assert o.data.uv_layers.get(core.ATLAS) is not None
        assert o.get("nighty_source_materials")
    assert bake.fresh(objs, folder, 512)
    # an edit makes the bake stale; assigning again brings the source material back into the slot
    materials.assign({"CrateHandle": {"material": "rubber", "roughness": 0.3}})
    assert parts["CrateHandle"].material_slots[0].material.get("nighty")
    assert not bake.fresh(objs, folder, 512)
    out = {}
    for eng in ("roblox", "unity", "unreal", "godot", "gltf", "blender"):
        r = bake.run_steps(export.export_steps(objs, eng, path=os.path.join(d, "out", eng), name="Crate",
                                               size=512, device="CPU"), tick=0.2, timeout=900)
        out[eng] = r
        for f in r["files"]:
            assert os.path.exists(os.path.join(r["folder"], f)), (eng, f)
    assert out["roblox"]["baked"] and not out["unity"]["baked"]       # baked once (after the edit), reused
    rb = out["roblox"]
    assert rb["mesh"]["parts"] == 1 and rb["mesh"]["triangles"] < 20000
    approx(rb["mesh"]["size_studs"][0], rb["mesh"]["size_m"][0] / 0.28, 0.01)
    rbd = rb["folder"]
    met = png.read(os.path.join(rbd, "Crate_Metalness.png"))
    assert met.shape[2] == 1 and set(np.unique(met).tolist()) <= {0, 255}
    assert png.read_header(os.path.join(rbd, "Crate_Roughness.png"))[3] == 1
    assert not os.path.exists(os.path.join(rbd, "Crate_Emissive.png"))    # nothing glows on the crate
    ue = out["unreal"]["folder"]
    orm = png.read(os.path.join(ue, "T_Crate_ORM.png")).astype(np.float32) / 255
    bm = json.load(open(os.path.join(folder, "bake.json"), encoding="utf-8"))
    rough = png.read(os.path.join(folder, bm["maps"]["roughness"])).astype(np.float32)[..., 0] / 255
    aoi = png.read(os.path.join(folder, bm["maps"]["ao"])).astype(np.float32)[..., 0] / 255
    assert np.abs(orm[..., 1] - rough).max() < 0.01 and np.abs(orm[..., 0] - aoi).max() < 0.01
    un = out["unity"]["folder"]
    mask = png.read(os.path.join(un, "Crate_MaskMap.png")).astype(np.float32) / 255
    assert np.abs(mask[..., 3] - (1 - rough)).max() < 0.01
    for eng in ("gltf", "godot"):
        j = _glb_json(os.path.join(out[eng]["folder"], "Crate.glb"))
        mat = j["materials"][0]
        pbr = mat["pbrMetallicRoughness"]
        assert "baseColorTexture" in pbr and "normalTexture" in mat
        mr = j["textures"][pbr["metallicRoughnessTexture"]["index"]]["source"]
        oc = j["textures"][mat["occlusionTexture"]["index"]]["source"]
        assert mr == oc, "ORM: occlusion, roughness and metallic in one image"
    # re-import: Unity / Unreal FBX come back at the real size (meters)
    for eng, fname in (("unity", "Crate.fbx"), ("unreal", "SM_Crate.fbx")):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=os.path.join(out[eng]["folder"], fname))
        new = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
        dims = ecore.world_dims(new)
        approx(max(dims), max(out[eng]["mesh"]["size_m"]), 0.02)
        for o in new:
            bpy.data.objects.remove(o)
    with bpy.data.libraries.load(os.path.join(out["blender"]["folder"], "Crate.blend")) as (src, _):
        assert "CrateBody" in src.objects


def test_lods_attribution_and_blender_materials():
    d = tmpdir()
    parts = ts.make_crate()
    lods = []
    for o in list(parts.values()):           # LOD1 made before the bake: no baked UVs yet
        lod = o.copy()
        lod.data = o.data.copy()
        lod.name = f"{o.name}_LOD1"
        bpy.context.scene.collection.objects.link(lod)
        lod.modifiers.new("Decimate", "DECIMATE").ratio = 0.5
        lods.append(lod)
    materials.assign(ts.CRATE_MATERIALS, wear=0.3, dirt=0.3)
    handle = parts["CrateHandle"]
    handle["nighty_license"] = "CC-BY 4.0"
    handle["nighty_source"] = "https://example.com/handle"
    handle["nighty_author"] = "Someone"
    objs = list(parts.values())
    assert export.find_lods(objs) == [sorted(lod.name for lod in lods)] or         sorted(export.find_lods(objs)[0]) == sorted(lod.name for lod in lods)
    r = bake.run_steps(export.export_steps(objs, "gltf", path=os.path.join(d, "gltf"), name="Crate", size=256,
                                           device="CPU"), tick=0.2, timeout=900)
    assert "Crate_LOD1.glb" in r["files"] and "ATTRIBUTION.txt" in r["files"], r
    j = _glb_json(os.path.join(r["folder"], "Crate_LOD1.glb"))
    assert all("TEXCOORD_0" in p["attributes"] for m in j["meshes"] for p in m["primitives"])
    att = open(os.path.join(r["folder"], "ATTRIBUTION.txt"), encoding="utf-8").read()
    assert "CC-BY 4.0  (attribution required)" in att and "Someone" in att
    # Texture type "Blender materials": the .blend keeps the procedural materials
    presets.store(presets.resolve({"texture_type": "blender", "made_for": "blender"}), objs)
    r = bake.run_steps(export.export_steps(objs, "blender", path=os.path.join(d, "blend"), name="Crate"),
                       tick=0.2, timeout=900)
    with bpy.data.libraries.load(os.path.join(r["folder"], "Crate.blend")) as (src, _):
        mats = list(src.materials)
    assert any(m.startswith("NB Wood") for m in mats) and not any(m.startswith("NB Baked") for m in mats), mats


def test_verify_job_and_report_on_scene():
    parts = _gun()
    objs = list(parts.values())
    d = tmpdir()
    bake.run_steps(bake.bake_steps(objs, size=256, out_dir=d, name="Gun", device="CPU"), tick=0.2, timeout=900)
    rep = bake.run_steps(bake.verify_steps(objs), tick=0.2, timeout=900)
    assert rep["passed"], rep["failed"]
    assert os.path.exists(rep["renders"]) and png.read_header(rep["renders"])[:2] == (960, 640)
    stored = json.loads(bpy.context.scene[bake.REPORT_KEY])
    assert stored["passed"] and stored["current"] and stored["stamp"] == bake.stamp(objs)
    assert os.path.exists(os.path.join(d, "texture_report.json"))


# ----------------------------------------------------------------------------------------------- tools

class FakeCtx:
    def __init__(self):
        self.jobs = []
        self.undo_label = None

    def start_job(self, step_fn, label):
        self.jobs.append((step_fn, label))
        return f"job{len(self.jobs)}"


def test_tools_registry_and_calls():
    from nighty_blender import tools
    import nighty_blender.tools.texture  # noqa: F401  (registers)
    for name in ("asset_options", "assign_materials", "add_decal", "stylize", "bake", "export_asset",
                 "verify_textures"):
        t = tools.ACTIONS[name]
        assert t.level == "tools" and isinstance(t.input_schema, dict) and len(t.description) < 320, name
    assert tools.ACTIONS["bake"].slow and tools.ACTIONS["export_asset"].slow and tools.ACTIONS["verify_textures"].slow
    assert not tools.ACTIONS["assign_materials"].slow and not tools.ACTIONS["verify_textures"].changes
    ctx = FakeCtx()
    T = {n: tools.ACTIONS[n].fn for n in tools.ACTIONS}
    menu = T["asset_options"](ctx, {})
    assert len(menu["presets"]) == 6
    st_ = T["asset_options"](ctx, {"preset": "Realistic weapon", "choice": {"size": "1K", "made_for": "gltf"}})
    assert st_["stored"]["size"] == "1K"
    lib = T["assign_materials"](ctx, {"parts": {}})
    assert any(r["material"] == "gunmetal" for r in lib["materials"])
    ts.make_gun()
    r = T["assign_materials"](ctx, {"parts": ts.GUN_MATERIALS})
    assert len(r["parts"]) == len(ts.GUN_MATERIALS) and ctx.undo_label == "AI: assign materials"
    try:
        T["assign_materials"](ctx, {"parts": {"Nope": "steel"}})
        raise AssertionError("no error")
    except tools.ToolError:
        pass
    dres = T["add_decal"](ctx, {"part": "Stock", "text": "77", "side": "front", "size": 0.05})
    assert dres["name"] == "77"
    assert T["add_decal"](ctx, {"remove": "77"}) == {"removed": "77"}
    s = T["stylize"](ctx, {"parts": ["Stock"], "edges": 0.8})
    assert s["parts"][0]["stylized"]
    T["assign_materials"](ctx, {"parts": {"Stock": "wood"}})
    j = T["bake"](ctx, {"size": "1K"})
    assert j == {"job": "job1"} and ctx.jobs[0][1].startswith("Bake")

    class FakeJob:
        cancelled = False
    gen = ctx.jobs[0][0](FakeJob())
    p, msg = next(gen)              # the first slice only: the job framework drives the rest
    assert 0.0 <= p <= 1.0 and isinstance(msg, str)
    FakeJob.cancelled = True
    try:
        next(gen)
        raise AssertionError("a cancelled job kept running")
    except StopIteration as stop:
        assert stop.value == {"cancelled": True}
    try:
        T["verify_textures"](ctx, {"parts": ["Stock"]})
        raise AssertionError("verify without a bake")
    except tools.ToolError as e:
        assert "bake first" in str(e)


def test_cc0_needs_consent():
    from nighty_blender.nighty.materials import cc0
    cc0.revoke()
    assert cc0.consent() is None
    try:
        list(cc0.download_steps([("polyhaven", "wood_table_001")]))
        raise AssertionError("downloaded without consent")
    except PermissionError:
        pass
    d = tmpdir()
    folder = cc0.agree(os.path.join(d, "cc0"))
    assert cc0.consent()["folder"] == folder and os.path.isdir(folder)
    assert cc0.cached("polyhaven", "wood_table_001") is None
    if os.environ.get("NIGHTY_NET_TESTS") == "1":   # a real download (opt-in: network)
        files = cc0.fetch("polyhaven", "wood_table_001", "1k")
        assert set(files) >= {"color", "roughness"} and all(os.path.exists(p) for p in files.values())
        assert cc0.cached("polyhaven", "wood_table_001")
    cc0.revoke()


def test_zz_cleanup():
    _cleanup()
