# SPDX-License-Identifier: GPL-3.0-or-later
"""Texture checks (verify_textures), the opposite of the usual AI-texture faults:
- blur: fine detail against coarser detail (a smeared or upscaled map has none) + variance of the Laplacian;
- metallic: every pixel exactly 0 or 1;
- lighting baked into the colors: albedo against AO (high-passed) must not move together;
- pixels left unbaked (fill color), seams that show (colors across UV seams vs inside faces);
- normal map: valid tangent-space vectors, the format the engine wants;
- renders: albedo only and two different lights, from two sides (one picture), for a look.
Writes texture_report.json next to the maps. Runs in the worker (or a test)."""

import json
import math
import os
import time

import bpy
import numpy as np

from . import maps, png, uvraster
from ..materials import compat

PBR_STYLES = ("pbr",)


def _load(folder, manifest, key):
    f = manifest["maps"].get(key)
    if not f:
        return None
    a = png.read(os.path.join(folder, f)).astype(np.float32)
    return a / (65535.0 if a.max() > 255 else 255.0)


def _erode(mask, steps=2):
    m = mask.copy()
    for _ in range(steps):
        m = m & maps._shift(m, 0, 1) & maps._shift(m, 0, -1) & maps._shift(m, 1, 0) & maps._shift(m, -1, 0)
    return m


def coverage(objects, layer, n, islands=False):
    """Which pixels the UVs use (row 0 = top, like the PNGs); with islands=True also an island id per pixel."""
    tris, ids, base = [], [], 0
    for o in objects:
        me = o.data
        arr = uvraster.mesh_arrays(me, layer if (layer and me.uv_layers.get(layer)) else None)
        if arr is None:
            continue
        uv, tl, tp, lv = arr
        isl = uvraster.islands(me, uv, lv) if islands else np.zeros(len(me.polygons), np.int64)
        tris.append(uv[tl])
        ids.append(isl[tp] + base)
        base += (int(isl.max()) + 1) if len(isl) else 1
    if not tris:
        z = np.zeros((n, n), bool)
        return (z, np.full((n, n), -1)) if islands else z
    cov, _, idm = uvraster.rasterize(np.concatenate(tris), n, np.concatenate(ids), id_map=True)
    if islands:
        return cov[::-1], idm[::-1]
    return cov[::-1]


def edge_sharpness(lum, mask, min_step=0.08):
    """Median of (largest 1-pixel step) / (range over 5x5) at strong color edges: ~1 sharp, < 0.35 smeared."""
    h, w = lum.shape
    dx = np.abs(np.diff(lum, axis=1, append=lum[:, -1:]))
    dy = np.abs(np.diff(lum, axis=0, append=lum[-1:, :]))
    g = np.maximum(dx, dy)
    g = np.maximum(g, np.maximum(maps._shift(dx, 0, 1), maps._shift(dy, 1, 0)))
    hi = lum.copy()
    lo = lum.copy()
    for dy_ in range(-2, 3):
        for dx_ in range(-2, 3):
            if dy_ == 0 and dx_ == 0:
                continue
            s = maps._shift(lum, dy_, dx_)
            hi = np.maximum(hi, s)
            lo = np.minimum(lo, np.where(s == 0, lo, s))
    rng = hi - lo
    sel = mask & (rng > min_step)
    if sel.sum() < 50:
        return None, int(sel.sum())
    s = g[sel] / np.maximum(rng[sel], 1e-6)
    return float(np.median(s)), int(sel.sum())


def octave_ratio(lum):
    """Fine detail against the next coarser detail: power in the top frequency octave (0.25-0.5 cycles per pixel)
    divided by the octave below (0.125-0.25). Natural and procedural maps keep ~0.15-0.5; a map that was smeared
    or upscaled has an empty top octave (< 0.05). None when the map is flat."""
    h, w = lum.shape
    a = lum - lum.mean()
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    f = np.abs(np.fft.rfft2(a * win)) ** 2
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    r = np.sqrt(fy * fy + fx * fx)
    top = float(f[(r >= 0.25) & (r < 0.5)].sum())
    mid = float(f[(r >= 0.125) & (r < 0.25)].sum())
    total = float(f[r > 0.01].sum())
    if total < 1e-6 * h * w or mid <= 0:
        return None
    return top / mid


def laplacian_var(lum, mask):
    lap = (-4 * lum + maps._shift(lum, 0, 1) + maps._shift(lum, 0, -1) + maps._shift(lum, 1, 0) +
           maps._shift(lum, -1, 0))
    m = _erode(mask, 1)
    if m.sum() < 10:
        return 0.0
    v = float(lum[m].var())
    return float(lap[m].var() / max(v, 1e-6))


def _blur(a, r=6):
    out = a.copy()
    for _ in range(r):
        out = (out + maps._shift(out, 0, 1) + maps._shift(out, 0, -1) + maps._shift(out, 1, 0) +
               maps._shift(out, -1, 0)) / 5.0
    return out


def lighting_corr(lum, ao, mask, ids):
    """Correlation of albedo with AO inside each UV island (each island's mean taken out first, so different
    materials on different parts don't count): shadows painted into the colors make it high; a clean albedo
    (dirt only in some cavities, broken up) keeps it low. Returns (island-centered, raw)."""
    m = _erode(mask, 2) & (ids >= 0)
    if m.sum() < 100:
        return None, None
    a, b, k = lum[m].astype(np.float64), ao[m].astype(np.float64), ids[m]
    k = np.unique(k, return_inverse=True)[1].reshape(-1)
    cnt = np.bincount(k)
    ac = a - (np.bincount(k, a) / cnt)[k]
    bc = b - (np.bincount(k, b) / cnt)[k]
    raw = float(np.corrcoef(a, b)[0, 1]) if a.std() > 1e-6 and b.std() > 1e-6 else 0.0
    if ac.std() < 1e-6 or bc.std() < 1e-6:
        return 0.0, raw
    return float(np.corrcoef(ac, bc)[0, 1]), raw


def _sample(img, uv):
    """Bilinear samples of an H x W x C image (row 0 = top) at UVs (N x 2)."""
    h, w = img.shape[:2]
    x = np.clip(uv[:, 0] * w - 0.5, 0, w - 1.001)
    y = np.clip((1.0 - uv[:, 1]) * h - 0.5, 0, h - 1.001)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = (x - x0)[:, None], (y - y0)[:, None]
    a = img[y0, x0] * (1 - fx) + img[y0, x0 + 1] * fx
    b = img[y0 + 1, x0] * (1 - fx) + img[y0 + 1, x0 + 1] * fx
    return a * (1 - fy) + b * fy


def seam_ratio(objects, layer, base, size, mask=None):
    """The color jump across UV seams (points just inside the two islands) divided by the jump over the same
    distance inside each face (the texture's own variation): 1-3 = seams invisible; > 4.5 = seams show."""
    parts = [[], [], [], []]
    for o in objects:
        res = uvraster.seam_samples(o.data, layer if o.data.uv_layers.get(layer or "") else None, count=4,
                                    size=size)
        if len(res[0]):
            for i in range(4):
                parts[i].append(res[i])
    if not parts[0]:
        return None, 0
    A, B, AI, BI = (np.concatenate(p) for p in parts)
    sa, sb = _sample(base, A), _sample(base, B)
    seam = np.abs(sa - sb).mean(axis=1)
    local = 0.5 * (np.abs(sa - _sample(base, AI)).mean(axis=1) + np.abs(sb - _sample(base, BI)).mean(axis=1))
    # 75th percentiles: robust to a few hard spots, still sees seams that jump along their length
    return float(np.percentile(seam, 75) / max(np.percentile(local, 75), 0.004)), int(len(A))


def check_maps(manifest, folder, objects, style="pbr", made_for=None):
    """Deterministic checks on the baked maps -> list of {name, ok, value, limit, note}."""
    checks = []

    def add(name, ok, value, limit, note):
        checks.append({"name": name, "ok": bool(ok), "value": value, "limit": limit, "note": note})

    size = int(manifest["size"])
    layer = manifest.get("uv_layer")
    loaded = {k: _load(folder, manifest, k) for k in manifest["maps"]}
    sizes = {k: list(v.shape[:2]) for k, v in loaded.items() if v is not None}
    ok_sizes = all(s == [size, size] for s in sizes.values()) and (size & (size - 1)) == 0
    add("sizes", ok_sizes, sizes, f"{size} x {size}", "all maps the same power-of-two size")
    cov, ids = coverage(objects, layer, size, islands=True)
    if cov.sum() == 0:
        cov, ids = np.ones((size, size), bool), np.zeros((size, size), np.int64)
    add("coverage", cov.mean() > 0.05, round(float(cov.mean()), 3), "> 0.05", "share of the texture the UVs use")

    met = loaded.get("metallic")
    if met is not None:
        m = met[..., 0][cov]
        frac = float(((m > 0.02) & (m < 0.98)).mean())
        add("metallic_binary", frac <= 0.001, round(frac, 5), "<= 0.001", "metallic pixels that are not 0 or 1")
    nrm = loaded.get("normal")
    if nrm is not None:
        v = nrm[..., :3][cov] * 2 - 1
        ln = np.linalg.norm(v, axis=1)
        bad = float(((v[:, 2] < 0.0) | (ln < 0.8) | (ln > 1.2)).mean())
        add("normal_valid", bad <= 0.01, round(bad, 4), "<= 0.01", "tangent-space vectors pointing out")
        fmt = manifest.get("normal_format", "opengl")
        want = "directx" if made_for == "unreal" else "opengl"
        add("normal_format", True, fmt, want, "maps are stored OpenGL; the export flips green for DirectX")
    base = loaded.get("base_color")
    if base is not None:
        lum = maps.luminance(base[..., :3])
        er = _erode(cov, 2)
        sharp, n_edges = edge_sharpness(lum, er)
        oct_r = octave_ratio(lum)
        add("blur", oct_r is None or oct_r >= 0.06, None if oct_r is None else round(oct_r, 3), ">= 0.06",
            "fine detail vs coarser detail (smeared or upscaled maps have none)")
        add("edge_sharpness", True, None if sharp is None else round(sharp, 3), "info",
            f"steepness of {n_edges} color edges (1 = one-pixel step)")
        add("laplacian_variance", True, round(laplacian_var(lum, cov), 4), "info",
            "fine detail relative to contrast (higher = more fine detail)")
        # the same missed texels show in every map baked from the high poly: count them once (the worst map)
        unb = int(max((manifest.get("unbaked_pixels") or {}).values(), default=0))
        magenta = int(((base[..., 0] > 0.99) & (base[..., 1] < 0.01) & (base[..., 2] > 0.99) & cov).sum())
        add("unbaked_pixels", unb + magenta <= cov.sum() * 0.0005, unb + magenta, "~0",
            "pixels left at the fill color")
        ao = loaded.get("ao")
        if ao is not None:
            hp, raw = lighting_corr(lum, ao[..., 0], cov, ids)
            if style in PBR_STYLES:
                add("baked_lighting", hp is None or hp < 0.7, None if hp is None else round(hp, 3), "< 0.7",
                    f"albedo vs AO (raw {raw if raw is None else round(raw, 3)}): shadows in the colors")
            else:
                add("baked_lighting", True, None if hp is None else round(hp, 3), "info",
                    "stylized: AO in the albedo on purpose")
        sr, n = seam_ratio(objects, layer, base[..., :3], size, cov)
        add("seams", sr is None or sr < 4.5, None if sr is None else round(sr, 2), "< 4.5",
            f"color jump across {n} seam samples vs inside faces (1-3 = invisible)")
        if style in PBR_STYLES:
            dark = float((lum[cov] < 0.012).mean())
            add("albedo_range", dark < 0.25, round(dark, 3), "< 0.25", "share of albedo darker than real materials")
    rough = loaded.get("roughness")
    if rough is not None:
        r = rough[..., 0][cov]
        add("roughness_range", True, [round(float(r.min()), 3), round(float(r.mean()), 3), round(float(r.max()), 3)],
            "info", "min / mean / max")
    return checks


# ----------------------------------------------------------------------------------------------- renders

def _frame(objects):
    from mathutils import Vector
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return (lo + hi) / 2, max((hi - lo).length / 2, 0.01)


def _albedo_material(mat):
    """A copy that shows only the base color (emission, no light)."""
    m = mat.copy()
    t = m.node_tree
    p = compat.principled_of(m)
    out = compat.output_node(t)
    em = t.nodes.new("ShaderNodeEmission")
    src = compat.socket(p.inputs, "Base Color")
    if src.is_linked:
        t.links.new(src.links[0].from_socket, em.inputs[0])
    else:
        em.inputs[0].default_value = src.default_value
    t.links.new(em.outputs[0], compat.socket(out.inputs, "Surface"))
    return m


def render_sheet(objects, material, path, cell=320, samples=24):
    """2 views x (albedo only, light A, light B) in one PNG."""
    from mathutils import Vector
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    try:
        sc.cycles.use_denoising = True
    except AttributeError:
        pass
    sc.render.resolution_x = sc.render.resolution_y = cell
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    sc.view_settings.view_transform = "Standard"
    world = sc.world or bpy.data.worlds.new("NB Verify")
    sc.world = world
    wt = compat.ensure_nodes(world)
    bg = next(n for n in wt.nodes if n.type == "BACKGROUND")
    center, radius = _frame(objects)
    cam = bpy.data.objects.new("NB Cam", bpy.data.cameras.new("NB Cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"           # framing that always fits, no perspective stretch
    cam.data.ortho_scale = radius * 1.75
    dist = radius * 3.0
    cam.data.clip_end = radius * 10.0
    cam.data.clip_start = radius * 0.01
    lights = []
    for nm, energy in (("A", 1.0), ("B", 1.0)):
        ld = bpy.data.lights.new(f"NB Light {nm}", "SUN")
        lo = bpy.data.objects.new(f"NB Light {nm}", ld)
        sc.collection.objects.link(lo)
        lights.append(lo)
    alb = _albedo_material(material)
    rows = []
    for view in (Vector((0.6, -1.0, 0.45)), Vector((-0.6, 1.0, 0.35))):
        d = view.normalized()
        cam.location = center + d * dist
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        row = []
        for mode in ("albedo", "A", "B"):
            for o in objects:
                for s in o.material_slots:
                    s.material = alb if mode == "albedo" else material
            for lo, nm in zip(lights, ("A", "B")):
                lo.hide_render = mode != nm
            if mode == "A":   # key from the upper left of the camera, a soft sky
                kd = (d + Vector((-1.0, -0.2, 1.2))).normalized()
                lights[0].data.energy = 3.0
                bg.inputs[0].default_value = (0.25, 0.27, 0.3, 1)
                bg.inputs[1].default_value = 0.6
                lights[0].rotation_euler = (-kd).to_track_quat("-Z", "Y").to_euler()
            elif mode == "B":  # low warm light from behind on the right
                kd = (-d + Vector((1.2, 0.0, 0.25))).normalized()
                lights[1].data.energy = 3.5
                lights[1].data.color = (1.0, 0.85, 0.7)
                bg.inputs[0].default_value = (0.2, 0.22, 0.28, 1)
                bg.inputs[1].default_value = 0.35
                lights[1].rotation_euler = (-kd).to_track_quat("-Z", "Y").to_euler()
            else:
                bg.inputs[0].default_value = (0.5, 0.5, 0.5, 1)
                bg.inputs[1].default_value = 1.0
            tmp = path + f".{mode}.png"
            sc.render.filepath = tmp
            bpy.ops.render.render(write_still=True)
            img = bpy.data.images.load(tmp)
            a = np.empty(cell * cell * 4, np.float32)
            img.pixels.foreach_get(a)
            bpy.data.images.remove(img)
            os.remove(tmp)
            row.append(a.reshape(cell, cell, 4)[::-1, :, :3])
        rows.append(np.concatenate(row, axis=1))
    sheet = np.concatenate(rows, axis=0)
    png.write(path, png.to_uint(sheet))
    bpy.data.objects.remove(cam)
    for lo in lights:
        bpy.data.objects.remove(lo)
    bpy.data.materials.remove(alb)
    return path


def run(spec, progress):
    """Worker task 'verify': the map checks, then the render sheet. Returns the report."""
    from . import apply
    folder = spec["folder"]
    with open(os.path.join(folder, "bake.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    objects = [bpy.data.objects[n] for n in spec["objects"] if n in bpy.data.objects]
    progress(0.05, "Checking maps")
    style = spec.get("style") or manifest.get("style", "pbr")
    checks = check_maps(manifest, folder, objects, style, spec.get("made_for"))
    sheet = None
    if spec.get("renders", True):
        progress(0.4, "Rendering")
        mat = apply.baked_material(manifest, folder, name=manifest["name"] + " verify")
        for o in objects:
            o.hide_render = False
        sheet = render_sheet(objects, mat, os.path.join(folder, "texture_check.png"),
                             cell=int(spec.get("cell", 320)), samples=int(spec.get("samples", 24)))
    failed = [c["name"] for c in checks if not c["ok"]]
    report = {"passed": not failed, "failed": failed, "checks": checks, "renders": sheet, "folder": folder,
              "name": manifest["name"], "size": manifest["size"], "style": style, "time": time.time(),
              "stamp": spec.get("stamp")}
    with open(os.path.join(folder, "texture_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    progress(1.0, "Done")
    return report
