# SPDX-License-Identifier: GPL-3.0-or-later
# Clean colors for imported models (nighty.colors, the clean_colors step, make_game_ready's colors option): a synthetic "AI"
# surface with a known three-color pattern painted the way 3D generators paint (stair-stepped, noisy borders, a dark halo
# strip between two colors, specks, a highlight painted in) must come out as exactly three flat regions with smooth
# borders, metallic exactly 0 / 1, and crisp borders after the bake; wood grain must be kept (gentle).

import json
import math
import os
import shutil
import tempfile
import time

import bpy
import numpy as np

FRESH_SCENE = True

LIGHT = (0.62, 0.62, 0.63)      # sRGB: light grey body
BLACK = (0.09, 0.09, 0.1)       # near-black part
ORANGE = (0.95, 0.55, 0.13)     # orange light
HALO = (0.33, 0.33, 0.34)       # the AI's dark band between light grey and black
CREAM = (0.98, 0.9, 0.72)       # a highlight painted into the orange


def _colors():
    from nighty_blender.nighty import colors
    return colors


def _ai_material(name, base_px, orm_px=None):
    """A material like an imported AI model's: base color image (+ ORM image through Separate Color)."""
    h, w = base_px.shape[:2]
    img = bpy.data.images.new(name + "_base", w, h)
    rgba = np.concatenate([base_px, np.ones((h, w, 1), np.float32)], axis=2)
    img.pixels.foreach_set(rgba.astype(np.float32).ravel())
    img.pack()
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    t = mat.node_tree
    bsdf = next(n for n in t.nodes if n.type == "BSDF_PRINCIPLED")
    tb = t.nodes.new("ShaderNodeTexImage")
    tb.image = img
    t.links.new(tb.outputs[0], bsdf.inputs["Base Color"])
    if orm_px is not None:
        orm = bpy.data.images.new(name + "_orm", w, h)
        orm.colorspace_settings.name = "Non-Color"
        orm.pixels.foreach_set(np.concatenate([orm_px, np.ones((h, w, 1), np.float32)], axis=2).ravel())
        orm.pack()
        tm = t.nodes.new("ShaderNodeTexImage")
        tm.image = orm
        sep = t.nodes.new("ShaderNodeSeparateColor")
        t.links.new(tm.outputs[0], sep.inputs[0])
        t.links.new(sep.outputs[1], bsdf.inputs["Roughness"])
        t.links.new(sep.outputs[2], bsdf.inputs["Metallic"])
    return mat


def _grid(name="Panel", n=160, size=0.4):
    """A dense flat panel (n x n quads, triangulated) with planar UVs, standing up on the ground."""
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=n, y_subdivisions=n, size=size, location=(0, 0, 0))
    ob = bpy.context.active_object
    ob.name = name
    me = ob.data
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    lv = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", lv)
    uv = (co[lv, :2] / size + 0.5).astype(np.float32)
    me.uv_layers.active.data.foreach_set("uv", uv.ravel())
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.quads_convert_to_tris()
    bpy.ops.object.mode_set(mode="OBJECT")
    return ob


def _painted(res=512, seed=1):
    """The known pattern, painted like an AI texture. True regions in UV: light grey u < 0.4, black 0.4..0.7,
    orange disc (center (0.85, 0.5), r 0.1) on light grey for u > 0.7. AI mess on top: stair-stepped borders, a mid
    grey halo band on the light / black border, orange specks in the grey, a cream highlight in the orange."""
    rng = np.random.default_rng(seed)
    v, u = np.mgrid[0:res, 0:res].astype(np.float64)
    u, v = (u + 0.5) / res, (v + 0.5) / res
    steps = 0.004 * np.sign(np.sin(v * 2 * math.pi * 48))            # stair steps along the borders
    px = np.empty((res, res, 3))
    px[:] = LIGHT
    b1 = 0.4 + steps
    b2 = 0.7 - steps
    black = (u > b1) & (u < b2)
    px[black] = BLACK
    px[(u > b1 - 0.008) & (u <= b1)] = HALO                           # the halo band on the grey side
    disc = (u - 0.85) ** 2 + (v - 0.5) ** 2 < 0.1 ** 2 * (1 + 0.08 * np.sin(np.arctan2(v - 0.5, u - 0.85) * 18))
    px[disc] = ORANGE
    hl = (u - 0.82) ** 2 + (v - 0.54) ** 2 < 0.025 ** 2
    px[hl] = CREAM
    for _ in range(25):                                                # specks (2 x 2 texels)
        x, y = rng.integers(10, int(res * 0.35)), rng.integers(10, res - 10)
        px[y:y + 2, x:x + 2] = ORANGE
    px += rng.normal(0, 0.004, px.shape)                               # a little noise (like a generator)
    return np.clip(px, 0, 1).astype(np.float32), (u, v)


def _truth(u, v):
    """0 light grey, 1 black, 2 orange for UV points (the pattern without the mess)."""
    lab = np.zeros(len(u), np.int64)
    lab[(u > 0.4) & (u < 0.7)] = 1
    lab[(u - 0.85) ** 2 + (v - 0.5) ** 2 < 0.1 ** 2] = 2
    return lab


def _panel(n=160):
    ob = _grid(n=n)
    base, _uv = _painted()
    orm = np.zeros(base.shape, np.float32)
    orm[..., 1] = 0.5                                   # roughness 0.5
    u = (np.arange(base.shape[1]) + 0.5) / base.shape[1]
    orm[:, (u > 0.4) & (u < 0.7), 2] = 1.0              # the AI says the black part is metal (it is not sure: 1.0)
    ob.data.materials.append(_ai_material("Material_0", base, orm))
    return ob


def _face_uv_centers(ob):
    me = ob.data
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers.active.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    st = np.empty(len(me.polygons), np.int32)
    tt = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_start", st)
    me.polygons.foreach_get("loop_total", tt)
    lf = np.repeat(np.arange(len(st)), tt)
    c = np.stack([np.bincount(lf, weights=uv[:, j]) for j in range(2)], axis=1) / tt[:, None]
    return c


# ------------------------------------------------------------------------------------------------- pure parts

def test_palette_finds_the_flat_colors_and_merges_shades():
    from nighty_blender.nighty.colors import palette as P
    rng = np.random.default_rng(0)
    cols = np.concatenate([np.tile(c, (n, 1)) for c, n in ((LIGHT, 5000), (BLACK, 4000), (ORANGE, 800))])
    cols = cols + rng.normal(0, 0.008, cols.shape)
    lab = P.srgb_to_oklab(np.clip(cols, 0, 1))
    centers, shares = P.fit(lab, np.ones(len(lab)), k=10)
    assert len(centers) == 3, (len(centers), shares)
    got = sorted(P.hex_of(c) for c in P.oklab_to_srgb(centers))
    want = sorted(P.hex_of(c) for c in (LIGHT, BLACK, ORANGE))
    for g, w in zip(got, want):
        assert abs(int(g[1:3], 16) - int(w[1:3], 16)) <= 4, (got, want)
    flat, _med = P.flatness(lab, np.ones(len(lab)), centers)
    assert flat > 0.95
    # round trip of the color math
    x = rng.random((50, 3))
    assert np.abs(P.oklab_to_srgb(P.srgb_to_oklab(x)) - x).max() < 1e-6


def test_regions_drop_crumbs_and_halo_strips():
    from nighty_blender.nighty.colors import regions as R
    # a strip of faces in a row: 200 grey, 3 mid-grey (halo), 200 black; plus one orange crumb in the grey
    n = 403
    lab = np.array([0] * 200 + [1] * 3 + [2] * 200)
    lab[10] = 3
    fa, fb = np.arange(n - 1), np.arange(1, n)
    elen = np.full(n - 1, 0.001)
    area = np.full(n, 1e-6)
    centers = np.array([[0.7, 0, 0], [0.45, 0, 0], [0.2, 0, 0], [0.75, 0.06, 0.15]])
    colors = centers[lab]
    same = lab[fa] == lab[fb]
    comp = R.components(n, fa[same], fb[same])
    st = R.region_stats(lab, comp, area, colors, fa, fb, elen, 4)
    kill, why = R.pick_dissolve(st, centers, crumb_area=3e-6, thin_width=1e-4, halo_width=0.01)
    assert why["crumbs"] >= 1 and why["halos"] == 1, why
    out, left = R.fill(lab, kill[comp], fa, fb, elen, 4)
    assert not left.any()
    assert set(out[:200]) == {0} and set(out[203:]) == {2}, out
    assert set(out[200:203]) <= {0, 2}


def test_picture_fixes_drifted_hues_only():
    from nighty_blender.nighty.colors import palette as P
    px = np.ones((200, 200, 3)) * 0.97                       # the picture: white background ...
    px[40:160, 30:170] = (0.8, 0.8, 0.81)                   # ... a light grey body
    px[80:120, 60:100] = (0.95, 0.6, 0.17)                  # ... an orange light
    px[130:150, 120:160] = (0.12, 0.12, 0.13)               # ... a black part
    pic = P.picture_palette(px)
    assert pic is not None and len(pic[0]) >= 3, pic
    lavender = P.srgb_to_oklab(np.array([0.79, 0.77, 0.88]))   # what a Max model made of the light grey
    fixed = P.toward_picture(lavender, pic)
    assert fixed is not None and abs(fixed[0] - lavender[0]) < 1e-9, "lightness kept"
    assert np.hypot(fixed[1], fixed[2]) < 0.01, "the lavender tint is gone"
    salmon = P.srgb_to_oklab(np.array([0.96, 0.42, 0.32]))
    f2 = P.toward_picture(salmon, pic)
    hue = math.degrees(math.atan2(f2[2], f2[1]))
    assert 50 < hue < 80, hue                                 # orange again
    assert P.toward_picture(P.srgb_to_oklab(np.array([0.11, 0.1, 0.16])), pic) is None   # near-black left alone
    assert P.toward_picture(P.srgb_to_oklab(np.array([0.8, 0.8, 0.81])), pic) is None    # no drift: unchanged


# ------------------------------------------------------------------------------------------------- on a mesh

def test_clean_makes_three_flat_regions_with_smooth_borders():
    C = _colors()
    ob = _panel()
    t = time.monotonic()
    rep = C.clean(ob, mode="auto", size="1K")
    secs = time.monotonic() - t
    assert rep["mode"] == "clean", rep
    assert rep["colors"] == 3, rep["palette"]
    assert secs < 20 * float(__import__("os").environ.get("NIGHTY_TEST_SLOW", "3" if __import__("os").environ.get("CI") else "1")), secs
    kinds = {r["color"]: r for r in rep["palette"]}
    assert len(kinds) == 3
    labels = C.face_regions(ob)
    uvc = _face_uv_centers(ob)
    truth = _truth(uvc[:, 0], uvc[:, 1])
    # map each region to the truth label it mostly covers
    m = {int(r): int(np.bincount(truth[labels == r]).argmax()) for r in np.unique(labels)}
    assert sorted(m.values()) == [0, 1, 2], m
    got = np.array([m[int(r)] for r in labels])
    # away from the true borders (more than 2 % of the panel = 8 mm) every face is right: specks, the halo band and
    # the painted highlight are gone
    u, v = uvc[:, 0], uvc[:, 1]
    d_border = np.minimum.reduce([np.abs(u - 0.4), np.abs(u - 0.7),
                                  np.abs(np.hypot(u - 0.85, v - 0.5) - 0.1)])
    far = d_border > 0.02
    assert (got[far] == truth[far]).mean() > 0.999, (got[far] != truth[far]).sum()
    # the stair steps are gone: the grey / black border runs straight (its spread across the rows is small)
    row = np.round(v * 160).astype(int)
    xs = []
    for r in range(10, 150):
        sel = (row == r) & (u > 0.3) & (u < 0.55)
        if sel.any():
            uu = u[sel]
            gg = got[sel]
            black = uu[gg == 1]
            if len(black):
                xs.append(black.min())
    xs = np.array(xs)
    assert xs.std() < 0.0028, xs.std()         # painted steps: +-0.004 (std 0.004); smoothed: well under
    assert rep.get("blends_dropped"), "the halo grey is a blend of grey and black: not a color of its own"
    # metallic exactly 0 / 1 per region, sensible roughness; the AI's "metal" black part stays plastic (near-black
    # needs the AI to be sure, and the AI said 1.0 here: so it IS metal)
    for r in rep["palette"]:
        assert r["metal"] in (0, 1)
        assert 0.15 <= r["roughness"] <= 0.9
    # the material: one flat color per region from the point attributes, the AI material kept for restore
    mat = ob.material_slots[0].material
    assert mat.name.startswith(C.MAT_PREFIX) and mat.get(C.ORIG) == "Material_0"
    assert bpy.data.materials["Material_0"].use_fake_user
    assert all(ob.data.attributes.get(f"{C.SHARE_PREFIX}{j}") is not None for j in range(3))
    assert C.restore(ob)
    assert ob.material_slots[0].material.name == "Material_0"
    assert ob.data.attributes.get(C.ATTR_REGION) is None


def test_region_material_rules():
    C = _colors()
    # wood never metal, strong paint never metal, near-black only when the AI is sure, grey metal stays metal
    assert C.region_material((0.45, 0.26, 0.12), 1.0, 0.5)[0] == 0
    assert C.region_material((0.1, 0.3, 0.9), 1.0, 0.5)[0] == 0
    assert C.region_material((0.1, 0.1, 0.11), 0.6, 0.5)[0] == 0
    assert C.region_material((0.1, 0.1, 0.11), 0.95, 0.5)[0] == 1
    assert C.region_material((0.7, 0.71, 0.72), 0.9, 0.3)[0] == 1
    met, rough, kind = C.region_material((0.45, 0.26, 0.12), 0.0, 0.1)
    assert kind == "wood" and rough >= 0.5
    met, rough, kind = C.region_material((0.7, 0.71, 0.72), 0.9, 0.95)
    assert met == 1 and rough <= 0.6


def test_wood_grain_is_kept_gentle():
    C = _colors()
    ob = _grid("Crate", n=120)
    res = 256
    v, u = np.mgrid[0:res, 0:res].astype(np.float64) / res
    rng = np.random.default_rng(3)
    grain = 0.5 + 0.5 * np.sin(u * 90 + 3 * np.sin(v * 7) + rng.normal(0, 0.4, u.shape))
    dark, light = np.array([0.27, 0.13, 0.05]), np.array([0.5, 0.3, 0.15])
    px = dark + (light - dark) * grain[..., None]
    brass = (u > 0.8) & (v > 0.8)
    px[brass] = (0.75, 0.62, 0.33)
    orm = np.zeros((res, res, 3), np.float32)
    orm[..., 1] = 0.6
    orm[..., 2] = 0.7                                  # the AI marked everything metal (Max did that on the chest)
    ob.data.materials.append(_ai_material("Wood_AI", px.astype(np.float32), orm))
    rep = C.clean(ob, mode="auto", size="1K")
    assert rep["mode"] == "gentle", rep
    kinds = sorted((r["kind"], r["metal"]) for r in rep["palette"])
    assert ("wood", 0) in kinds, kinds
    assert any(m == 1 for k, m in kinds if k != "wood"), kinds      # the brass plate is the only metal
    assert len(rep["palette"]) == 2, rep["palette"]
    mat = ob.material_slots[0].material
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    src = bsdf.inputs["Base Color"].links[0].from_node
    assert src.type == "TEX_IMAGE", "gentle keeps the AI's own color texture (the grain)"
    assert bsdf.inputs["Metallic"].is_linked and bsdf.inputs["Roughness"].is_linked


def test_keep_changes_nothing_and_tool_refuses_untextured():
    C = _colors()
    from nighty_blender.tools import ACTIONS, ToolError
    ob = _panel()
    rep = C.clean(ob, mode="keep")
    assert rep["mode"] == "keep"
    assert ob.material_slots[0].material.name == "Material_0"
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    try:
        ACTIONS["clean_colors"].fn(object(), {"objects": [cube.name]})
        raise AssertionError("should refuse")
    except ToolError as e:
        assert "no image texture" in str(e)


def test_decimate_keeps_the_regions_and_carry_to_quads():
    C = _colors()
    from nighty_blender.nighty.mesh import topo
    ob = _panel()
    C.clean(ob, mode="clean", size="1K")
    src = topo.keep_bake_source(ob)
    topo.decimate(ob, faces=3000, symmetry=None, planar=None, keep_sharp=35.0)
    me = ob.data
    assert me.attributes.get(C.ATTR_REGION) is not None, "the decimate keeps the regions"
    assert all(me.attributes.get(f"{C.SHARE_PREFIX}{j}") is not None for j in range(3))
    # a rebuilt mesh (quads) has none: carry_to brings them from the dense original by position
    for a in [a.name for a in me.attributes if a.name.startswith(C.SHARE_PREFIX) or a.name == C.ATTR_REGION]:
        me.attributes.remove(me.attributes[a])
    assert C.carry_to(ob, src) == 3
    lab = C.face_regions(ob)
    uvc = _face_uv_centers(ob)
    truth = _truth(uvc[:, 0], uvc[:, 1])
    m = {int(r): int(np.bincount(truth[lab == r]).argmax()) for r in np.unique(lab)}
    got = np.array([m[int(r)] for r in lab])
    assert (got == truth).mean() > 0.95
    assert ob.material_slots[0].material.get(C.ORIG) == "Material_0"


def test_make_game_ready_cleans_colors_and_bakes_them_crisp():
    C = _colors()
    from nighty_blender.tools import ACTIONS
    from nighty_blender.jobs import JobManager

    class Ctx:
        level = "tools"
        undo_label = None

        def __init__(self):
            self.jobs = JobManager(lambda obj: None)

        def start_job(self, step_fn, label, **kw):
            return {"job": self.jobs.start_gen(step_fn, label, label, "test")}

    ob = _panel(n=100)
    out = tempfile.mkdtemp(prefix="nighty-colors-")
    try:
        ctx = Ctx()
        res = ACTIONS["make_game_ready"].fn(ctx, {"object": ob.name, "name": "Panel", "path": out,
                                            "options": {"mesh": "triangles", "faces": 1200, "textures": "pbr",
                                                        "size": "1K", "made_for": "gltf"},
                                            "confirmed": True})
        job = ctx.jobs.get(res["job"])
        end = time.monotonic() + 400
        while job.state == "running" and time.monotonic() < end:
            ctx.jobs.pump(budget=0.05)
            time.sleep(0.01)
        assert job.state == "done", job.error
        rep = json.loads(job.result[0]["text"])
        print("    steps", rep["steps"])
        steps = [s["step"] for s in rep["steps"]]
        assert steps.index("clean_colors") < steps.index("retopo"), steps
        assert rep["colors"]["mode"] == "clean" and len(rep["colors"]["regions"]) == 3, rep["colors"]
        folder = rep["maps"]["folder"]
        painted = rep["maps"].get("clean_colors") or {}
        assert "base_color" in painted.get("painted", []), rep["maps"]      # exact maps, not the ray-cast bake
        img = bpy.data.images.load(os.path.join(folder, rep["maps"]["maps"]["base_color"]))
        px = np.empty(img.size[0] * img.size[1] * 4, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(-1, 4)[:, :3]
        met = bpy.data.images.load(os.path.join(folder, rep["maps"]["maps"]["metallic"]))
        mp = np.empty(met.size[0] * met.size[1] * met.channels, np.float32)
        met.pixels.foreach_get(mp)
        assert set(np.unique(np.round(mp, 3))) <= {0.0, 1.0}, "metallic exactly 0 / 1"
        # crisp: nearly every texel the low poly covers is one of the three flat colors (only a soft one-texel
        # edge between them; the stair steps, halo and specks are gone)
        from nighty_blender.nighty.bake import uvraster
        from nighty_blender.nighty.colors import palette as P
        low = bpy.data.objects["Panel"]
        uv, tl, _tp, _lv = uvraster.mesh_arrays(low.data)
        cover, _over = uvraster.rasterize(uv[tl], img.size[0])
        pal = P.srgb_to_oklab(np.array([r["rgb"] for r in C.info(low)["palette"]]))
        lab = P.srgb_to_oklab(np.clip(px, 0, 1))          # PNG pixels as stored (sRGB)
        _l, d = P.nearest(lab, pal)
        exact = (np.sqrt(d) < 0.03)[cover.ravel()].mean()
        assert exact > 0.97, exact
        # a later export whose maps went stale bakes again: it must paint again too (not bring the ray-cast
        # colors back)
        low["nighty_bake_stamp"] = ""
        out2 = os.path.join(out, "again")
        res = ACTIONS["export_asset"].fn(ctx, {"parts": ["Panel"], "made_for": "roblox", "path": out2,
                                              "name": "Panel"})
        job = ctx.jobs.get(res["job"])
        end = time.monotonic() + 400
        while job.state == "running" and time.monotonic() < end:
            ctx.jobs.pump(budget=0.05)
            time.sleep(0.01)
        assert job.state == "done", job.error
        er = job.result if isinstance(job.result, dict) else json.loads(job.result[0]["text"])
        assert "base_color" in (er.get("clean_colors") or {}).get("painted", []), er
        color = next(os.path.join(dp, f) for dp, _d, fs in os.walk(out2) for f in fs if f.endswith("_Color.png"))
        img2 = bpy.data.images.load(color)
        px2 = np.empty(img2.size[0] * img2.size[1] * 4, np.float32)
        img2.pixels.foreach_get(px2)
        lab2 = P.srgb_to_oklab(np.clip(px2.reshape(-1, 4)[:, :3], 0, 1))
        _l, d2 = P.nearest(lab2, pal)
        cover2, _o = uvraster.rasterize(uv[tl], img2.size[0])
        assert (np.sqrt(d2) < 0.03)[cover2.ravel()].mean() > 0.97
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_small_blobby_dots_come_out_round():
    C = _colors()
    ob = _grid("Dots", n=200)
    res = 512
    v, u = np.mgrid[0:res, 0:res].astype(np.float64)
    u, v = (u + 0.5) / res, (v + 0.5) / res
    px = np.empty((res, res, 3))
    px[:] = LIGHT
    ang = np.arctan2(v - 0.5, u - 0.5)
    rad = 0.022 * (1 + 0.22 * np.sin(3 * ang) + 0.12 * np.cos(5 * ang))   # a lumpy dot (about 14 mm across)
    px[np.hypot(u - 0.5, v - 0.5) < rad] = ORANGE
    px[(u > 0.75)] = BLACK                                                     # a second color far away
    ob.data.materials.append(_ai_material("Dot_AI", px.astype(np.float32)))
    rep = C.clean(ob, mode="clean", size="1K")
    assert rep.get("border_smoothing", {}).get("round_dots", 0) >= 1, rep.get("border_smoothing")
    # the shares now draw a disk: inside the equal-area radius orange wins, outside it grey
    me = ob.data
    rows = rep["palette"]
    oi = min(range(len(rows)), key=lambda j: abs(rows[j]["rgb"][0] - ORANGE[0]) + abs(rows[j]["rgb"][2] - ORANGE[2]))
    sh = np.zeros((len(me.vertices), len(rows)), np.float32)
    for j in range(len(rows)):
        me.attributes[f"{C.SHARE_PREFIX}{j}"].data.foreach_get("value", sh[:, j])
    co = np.array([vv.co[:] for vv in me.vertices])
    lab = np.argmax(sh, axis=1)
    orange = lab == oi
    c = co[orange].mean(axis=0)
    dist = np.linalg.norm(co[:, :2] - c[:2], axis=1)
    r = np.sqrt(orange.sum() * (0.4 / 200) ** 2 / np.pi)
    edge = 0.4 / 200
    assert (dist[orange] < r + 1.5 * edge).all(), (dist[orange].max(), r)
    assert not (~orange & (dist < r - 1.5 * edge)).any()
