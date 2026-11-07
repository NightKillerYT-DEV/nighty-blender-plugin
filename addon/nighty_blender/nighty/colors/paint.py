# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact color maps for a low poly from its dense original (no ray casting), after the bake.

The baker casts rays from the low poly to the dense original: where the two surfaces differ (raised buttons,
narrow grooves the low poly doesn't model, sliver triangles) a ray lands on the wrong side or a texel is never
reached, leaving fuzzy bands and dark streaks. Here every texel a low-poly triangle touches is painted directly:
its point on the low poly -> the nearest point on the dense surface (never down a groove) -> there:
- clean (flat colors): the region (the same argmax of the per-vertex region shares the material uses); texels on a
  border get 3 x 3 samples, so borders are smooth anti-aliased lines at any size;
- gentle (real texture detail, e.g. wood grain): the AI's own color and roughness maps at that point's UV.
Base color, metallic (by region, 0 / 1) and roughness are overwritten in the bake folder; the normal map keeps the
baker's except on texels only sliver triangles touch (flat there); AO stays the baker's.
"""

import os
import threading
import time

import bpy
import numpy as np

from . import palette as P

SS = 3      # samples per side on border texels (9 per texel)


def _high_of(low):
    name = low.get("nighty_high")
    h = bpy.data.objects.get(name) if name else None
    return h if h is not None and h.type == "MESH" else None


def wanted(lows):
    """The parts whose bake source went through clean colors (clean or gentle): {low: high}."""
    from . import info
    out = {}
    for o in lows:
        h = _high_of(o)
        if h is not None and (info(h) or {}).get("mode") in ("clean", "gentle"):
            out[o] = h
    return out


def _world(obj):
    me = obj.data
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    mw = np.array(obj.matrix_world, dtype=np.float64)
    return co.reshape(-1, 3).astype(np.float64) @ mw[:3, :3].T + mw[:3, 3]


def _tris(me):
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    tv = np.empty(n * 3, np.int32)
    tl = np.empty(n * 3, np.int32)
    me.loop_triangles.foreach_get("vertices", tv)
    me.loop_triangles.foreach_get("loops", tl)
    return tv.reshape(-1, 3).astype(np.int64), tl.reshape(-1, 3).astype(np.int64)


def _read_high(high):
    from . import SHARE_PREFIX, info
    rows = info(high)["palette"]
    me = high.data
    co = _world(high)
    tv, _tl = _tris(me)
    k = len(rows)
    sh = np.zeros((len(me.vertices), k), np.float32)
    for j in range(k):
        a = me.attributes.get(f"{SHARE_PREFIX}{j}")
        if a is not None:
            a.data.foreach_get("value", sh[:, j])
    size = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0))) if len(co) else 1.0
    out = {"co": co, "tv": tv, "shares": sh, "rows": rows, "radius": 0.02 * size, "mode": info(high)["mode"]}
    if out["mode"] == "gentle":
        # the AI's own color and roughness maps, read where the nearest dense point lies (its UVs)
        from . import _array, source_material, textures_of
        tex = textures_of(source_material(high, 0))
        lay = me.uv_layers.active or me.uv_layers[0]
        uv = np.empty(len(me.loops) * 2, np.float32)
        lay.data.foreach_get("uv", uv)
        out["tri_uv"] = uv.reshape(-1, 2).astype(np.float64)[_tl]
        out["base"] = _array(tex["base"][0], {})
        r = tex["rough"]
        out["rough"] = (_array(r[0], {}), r[1] if r[1] is not None else 0) if isinstance(r, tuple) else float(r)
    return out


def _read_low(low, layer, n):
    from ..bake import uvraster
    me = low.data
    lay = me.uv_layers.get(layer) if layer else None
    lay = lay or me.uv_layers.active
    uv = np.empty(len(me.loops) * 2, np.float32)
    lay.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2).astype(np.float64)
    tv, tl = _tris(me)
    co = _world(low)
    tri_uv = uv[tl]
    center, _ov, idm = uvraster.rasterize(tri_uv, n, ids=np.arange(len(tl)), id_map=True)
    reached = np.zeros(len(tl), bool)                  # triangles the baker reached (they own a texel center)
    reached[idm[idm >= 0]] = True
    idm = _conservative(idm, tri_uv, n)
    unreached = (idm >= 0) & ~reached[np.maximum(idm, 0)]
    return {"tri_uv": tri_uv, "tri_co": co[tv], "idm": idm, "unreached": unreached}


def _conservative(idm, tri_uv, n):
    """Every texel a triangle touches belongs to it, not only texels whose center it covers: a sliver triangle
    (thinner than a texel in UV, common at creases) otherwise owns no texel at all, and the margin fill paints it
    with whatever island lies next to it (the dark streaks across the blaster's grey). Points along each triangle
    every half texel (edges and inside) mark the texels it touches; texels a center already owns keep it."""
    out = idm.copy()
    t = np.asarray(tri_uv, np.float64) * n
    edge = np.max(np.linalg.norm(t[:, [1, 2, 0]] - t, axis=2), axis=1)
    steps = np.clip(np.ceil(edge / 0.5).astype(np.int64), 1, 512)
    for m in np.unique(steps):
        ids = np.nonzero(steps == m)[0]
        i, j = np.meshgrid(np.arange(m + 1), np.arange(m + 1), indexing="ij")
        keep = (i + j) <= m
        w1 = (i[keep] / m)[None, :, None]
        w2 = (j[keep] / m)[None, :, None]
        for c0 in range(0, len(ids), max(1, 200000 // int(keep.sum()))):
            tt = t[ids[c0:c0 + max(1, 200000 // int(keep.sum()))]]
            pts = tt[:, None, 0] * (1 - w1 - w2) + tt[:, None, 1] * w1 + tt[:, None, 2] * w2
            px = np.clip(np.floor(pts[..., 0]).astype(np.int64), 0, n - 1)
            py = np.clip(np.floor(pts[..., 1]).astype(np.int64), 0, n - 1)
            tid = np.broadcast_to(ids[c0:c0 + len(tt)][:, None], px.shape)
            free = out[py, px] < 0
            out[py[free], px[free]] = tid[free]
    return out


def _bary(low, t, uv):
    a, b, c = (low["tri_uv"][t, i] for i in range(3))
    v0, v1, v2 = b - a, c - a, uv - a
    d00 = (v0 * v0).sum(1)
    d01 = (v0 * v1).sum(1)
    d11 = (v1 * v1).sum(1)
    d20 = (v2 * v0).sum(1)
    d21 = (v2 * v1).sum(1)
    den = d00 * d11 - d01 * d01
    den = np.where(np.abs(den) < 1e-20, 1e-20, den)
    w1 = (d11 * d20 - d01 * d21) / den
    w2 = (d00 * d21 - d01 * d20) / den
    return w1, w2


def _sub_points(low, n, ys, xs, ox, oy):
    """World points for sub-texel samples: in the texel's own triangle when the sample is inside it, else in the
    neighboring texel's triangle that holds it (so anti-aliasing across a triangle edge stays exact), else the
    closest point of the own triangle."""
    t = low["idm"][ys, xs].copy()
    uv = np.stack([(xs + 0.5 + ox) / n, (ys + 0.5 + oy) / n], axis=1)
    w1, w2 = _bary(low, t, uv)
    inside = (w1 >= -1e-6) & (w2 >= -1e-6) & (w1 + w2 <= 1 + 1e-6)
    sx, sy = int(np.sign(ox)), int(np.sign(oy))
    for dy, dx in ((0, sx), (sy, 0), (sy, sx)):
        if inside.all() or (dx == 0 and dy == 0):
            continue
        out = np.nonzero(~inside)[0]
        yy = np.clip(ys[out] + dy, 0, n - 1)
        xx = np.clip(xs[out] + dx, 0, n - 1)
        cand = low["idm"][yy, xx]
        ok = cand >= 0
        if not ok.any():
            continue
        o2 = out[ok]
        c1, c2 = _bary(low, cand[ok], uv[o2])
        hit = (c1 >= -1e-6) & (c2 >= -1e-6) & (c1 + c2 <= 1 + 1e-6)
        t[o2[hit]] = cand[ok][hit]
        inside[o2[hit]] = True
    return _points_t(low, t, uv)


def _points_t(low, t, uv):
    w1, w2 = _bary(low, t, uv)
    w1 = np.clip(w1, 0.0, 1.0)
    w2 = np.clip(w2, 0.0, 1.0)
    tot = w1 + w2
    over = tot > 1.0
    w1[over] /= tot[over]
    w2[over] /= tot[over]
    w0 = 1.0 - w1 - w2
    p = low["tri_co"][t]
    return p[:, 0] * w0[:, None] + p[:, 1] * w1[:, None] + p[:, 2] * w2[:, None]


def _points(low, n, ys, xs, ox=0.0, oy=0.0):
    """World points on the low poly for texel (ys, xs) + sub-texel offsets (the texel's triangle's affine map;
    a sample just outside the triangle lands just off its plane, close enough for the nearest-point lookup)."""
    t = low["idm"][ys, xs]
    uv = np.stack([(xs + 0.5 + ox) / n, (ys + 0.5 + oy) / n], axis=1)
    a, b, c = (low["tri_uv"][t, i] for i in range(3))
    v0, v1, v2 = b - a, c - a, uv - a
    d00 = (v0 * v0).sum(1)
    d01 = (v0 * v1).sum(1)
    d11 = (v1 * v1).sum(1)
    d20 = (v2 * v0).sum(1)
    d21 = (v2 * v1).sum(1)
    den = d00 * d11 - d01 * d01
    den = np.where(np.abs(den) < 1e-20, 1e-20, den)
    w1 = (d11 * d20 - d01 * d21) / den
    w2 = (d00 * d21 - d01 * d20) / den
    # clamped into the triangle: a texel only touched by a sliver (or a sample past an edge) takes the closest
    # point of that triangle, never a point far off its plane
    w1 = np.clip(w1, 0.0, 1.0)
    w2 = np.clip(w2, 0.0, 1.0)
    tot = w1 + w2
    over = tot > 1.0
    w1[over] /= tot[over]
    w2[over] /= tot[over]
    w0 = 1.0 - w1 - w2
    p = low["tri_co"][t]
    return p[:, 0] * w0[:, None] + p[:, 1] * w1[:, None] + p[:, 2] * w2[:, None]


def _labels(tree, high, pts, stop, with_where=False):
    """Region per point: nearest point on the dense surface, its region shares interpolated, the biggest wins."""
    m = len(pts)
    loc = np.empty((m, 3))
    idx = np.zeros(m, np.int64)
    find = tree.find_nearest
    r = high["radius"]
    for i in range(m):
        if stop[0]:
            raise RuntimeError("cancelled")
        hit = find(pts[i], r)                 # a search radius keeps each lookup short
        if hit[0] is None:
            hit = find(pts[i])
        if hit[0] is None:
            loc[i] = pts[i]
            idx[i] = 0
        else:
            loc[i] = hit[0]
            idx[i] = hit[2]
    tri = high["co"][high["tv"][idx]]
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    v0, v1, v2 = b - a, c - a, loc - a
    d00 = (v0 * v0).sum(1)
    d01 = (v0 * v1).sum(1)
    d11 = (v1 * v1).sum(1)
    d20 = (v2 * v0).sum(1)
    d21 = (v2 * v1).sum(1)
    den = d00 * d11 - d01 * d01
    den = np.where(np.abs(den) < 1e-30, 1e-30, den)
    w1 = np.clip((d11 * d20 - d01 * d21) / den, 0, 1)
    w2 = np.clip((d00 * d21 - d01 * d20) / den, 0, 1)
    w0 = np.clip(1.0 - w1 - w2, 0, 1)
    s = high["shares"]
    tv = high["tv"][idx]
    val = s[tv[:, 0]] * w0[:, None] + s[tv[:, 1]] * w1[:, None] + s[tv[:, 2]] * w2[:, None]
    if with_where:
        return np.argmax(val, axis=1), idx, np.stack([w0, w1, w2], axis=1)
    return np.argmax(val, axis=1)


def _bilinear(arr, uv):
    h, w = arr.shape[:2]
    x = np.mod(uv[:, 0], 1.0) * w - 0.5
    y = np.mod(uv[:, 1], 1.0) * h - 0.5
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = (x - x0)[:, None]
    fy = (y - y0)[:, None]
    x0m, x1m, y0m, y1m = x0 % w, (x0 + 1) % w, y0 % h, (y0 + 1) % h
    return ((arr[y0m, x0m] * (1 - fx) + arr[y0m, x1m] * fx) * (1 - fy) +
            (arr[y1m, x0m] * (1 - fx) + arr[y1m, x1m] * fx) * fy)


def paint_steps(lows, folder, manifest):
    """Generator (a job's steps): repaints base color, metallic and roughness of the baked maps in `folder` for the
    parts whose dense original has clean colors. Returns a short report (or None when nothing applies)."""
    from mathutils.bvhtree import BVHTree
    from ..bake import maps, png
    pairs = wanted(lows)
    if not pairs:
        return None
    t0 = time.monotonic()
    n = int(manifest["size"])
    layer = manifest.get("uv_layer")
    yield 0.0, "painting the clean colors"
    highs = {}
    for lo, hi in pairs.items():
        if hi.name not in highs:
            highs[hi.name] = _read_high(hi)
            yield 0.05, "painting the clean colors"
    trees = {name: BVHTree.FromPolygons(h["co"].tolist(), h["tv"].tolist(), all_triangles=True)
             for name, h in highs.items()}
    yield 0.15, "painting the clean colors"
    lowd = {lo: _read_low(lo, layer, n) for lo in pairs}
    yield 0.2, "painting the clean colors"
    box = {"p": 0.2, "out": None, "err": None}
    stop = [False]

    def work():
        try:
            k_all = max(len(h["rows"]) for h in highs.values())
            lab = np.full((n, n), -1, np.int64)
            frac = np.zeros((n, n, k_all), np.float32)
            owner = np.full((n, n), -1, np.int64)
            gentle = np.zeros((n, n, 3), np.float32)
            grough = np.zeros((n, n), np.float32)
            is_gentle = np.zeros((n, n), bool)
            box["gentle"] = (gentle, grough, is_gentle)
            rows_of = {}
            for oi, (lo, hi) in enumerate(pairs.items()):
                L, H, tree = lowd[lo], highs[hi.name], trees[hi.name]
                rows_of[oi] = H["rows"]
                cov = (L["idm"] >= 0) & (owner < 0)
                ys, xs = np.nonzero(cov)
                owner[ys, xs] = oi
                if H["mode"] == "gentle":
                    # the AI's own texture (wood grain) read at the nearest dense point of every texel: no rays,
                    # so no streaks; metal by region, roughness the AI's inside the region's range
                    lb, idx, w = _labels(tree, H, _points(L, n, ys, xs), stop, with_where=True)
                    lab[ys, xs] = lb
                    frac[ys, xs, lb] = 1.0
                    uv = (H["tri_uv"][idx] * w[:, :, None]).sum(axis=1)
                    gentle[ys, xs] = _bilinear(H["base"], uv)[:, :3]
                    rr = H["rough"]
                    gr = _bilinear(rr[0], uv)[:, rr[1]] if isinstance(rr, tuple) else np.full(len(uv), rr)
                    from . import rough_range
                    lo_ = np.array([rough_range(r["kind"], r["metal"])[0] for r in H["rows"]])
                    hi_ = np.array([rough_range(r["kind"], r["metal"])[1] for r in H["rows"]])
                    grough[ys, xs] = np.clip(gr, lo_[lb], hi_[lb])
                    is_gentle[ys, xs] = True
                    box["looked_up"] = box.get("looked_up", 0) + int(len(ys))
                    box["p"] = 0.85
                    continue
                # coarse to fine: one lookup per 2 x 2 block; a block whose neighboring blocks all agree takes
                # that region, the rest are looked up texel by texel
                ay, ax = (ys // 2) * 2, (xs // 2) * 2
                first = ((ys == ay) & (xs == ax)) | ~cov[ay, ax]
                q = np.nonzero(first)[0]
                lab[ys[q], xs[q]] = _labels(tree, H, _points(L, n, ys[q], xs[q]), stop)
                box["p"] = 0.3
                grid = np.full((n // 2 + 2, n // 2 + 2), -2, np.int64)
                anc = lab[0:n:2, 0:n:2]
                grid[1:-1, 1:-1] = np.where(cov[0:n:2, 0:n:2], anc, -2)
                same = np.ones((n // 2, n // 2), bool)
                core = grid[1:-1, 1:-1]
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nb = grid[1 + dy:n // 2 + 1 + dy, 1 + dx:n // 2 + 1 + dx]
                        same &= (nb == core) | (nb == -2)
                same &= core >= 0
                rest = np.nonzero(~first)[0]
                uni = same[ys[rest] // 2, xs[rest] // 2]
                fill = rest[uni]
                lab[ys[fill], xs[fill]] = lab[ay[fill], ax[fill]]
                q2 = rest[~uni]
                if len(q2):
                    lab[ys[q2], xs[q2]] = _labels(tree, H, _points(L, n, ys[q2], xs[q2]), stop)
                box["looked_up"] = box.get("looked_up", 0) + int(len(q) + len(q2))
                box["p"] = 0.5
                # border texels: a neighbor (of the same part) has another region -> 3 x 3 samples
                mine = owner == oi
                diff = np.zeros((n, n), bool)
                for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
                    sh = np.roll(np.roll(lab, dy, axis=0), dx, axis=1)
                    sm = np.roll(np.roll(mine, dy, axis=0), dx, axis=1)
                    diff |= mine & sm & (sh != lab)
                by, bx = np.nonzero(diff)
                frac[ys, xs, lab[ys, xs]] = 1.0
                if len(by):
                    frac[by, bx] = 0.0
                    offs = (np.arange(SS) + 0.5) / SS - 0.5
                    for oy in offs:
                        for ox in offs:
                            pts = _sub_points(L, n, by, bx, ox, oy)
                            sl = _labels(tree, H, pts, stop)
                            frac[by, bx, sl] += 1.0 / (SS * SS)
                    box["borders"] = box.get("borders", 0) + int(len(by))
                box["p"] = 0.85
            box["out"] = (lab, frac, owner, rows_of)
        except Exception as exc:  # noqa: BLE001 - handed back to the job
            box["err"] = exc

    th = threading.Thread(target=work, name="nighty-paint", daemon=True)
    th.start()
    try:
        while th.is_alive():
            th.join(0.02)
            yield 0.2 + 0.6 * box["p"], "painting the clean colors"
    except GeneratorExit:
        stop[0] = True
        th.join(5)
        raise
    if box["err"] is not None:
        raise box["err"]
    lab, frac, owner, rows_of = box["out"]
    cover = owner >= 0
    # colors per texel: coverage-weighted mean (linear light), metal by majority, roughness mean
    base = np.zeros((n, n, 3), np.float32)
    metal = np.zeros((n, n), np.float32)
    rough = np.zeros((n, n), np.float32)
    for oi, rows in rows_of.items():
        m = owner == oi
        lin = maps.srgb_to_linear(np.array([r["rgb"] for r in rows], np.float32))
        k = len(rows)
        f = frac[m][:, :k]
        base[m] = f @ lin
        metal[m] = (f @ np.array([r["metal"] for r in rows], np.float32) >= 0.5).astype(np.float32)
        rough[m] = f @ np.array([r["roughness"] for r in rows], np.float32)
    gentle, grough, is_gentle = box["gentle"]
    if is_gentle.any():           # AI texture colors are sRGB as stored
        base[is_gentle] = maps.srgb_to_linear(gentle[is_gentle])
        rough[is_gentle] = grough[is_gentle]
    yield 0.85, "writing the maps"
    margin = int(manifest.get("margin_px") or max(4, n // 128))
    names = {k: (manifest.get("maps") or {}).get(k) for k in ("base_color", "metallic", "roughness")}
    names = {k: v for k, v in names.items() if v}
    # the old maps under the new texels; one margin grow + fill for all three maps together
    stack = np.zeros((n, n, 5), np.float32)
    for key, ch in (("base_color", slice(0, 3)), ("metallic", slice(3, 4)), ("roughness", slice(4, 5))):
        if key not in names:
            continue
        old = png.read(os.path.join(folder, names[key])).astype(np.float32)
        old = (old / (65535.0 if old.max() > 255 else 255.0))[::-1]
        if old.ndim == 2:
            old = old[..., None]
        if key == "base_color":
            stack[..., ch] = maps.srgb_to_linear(old[..., :3])
        else:
            stack[..., ch] = old[..., :1]
    stack[cover, 0:3] = base[cover]
    stack[cover, 3] = metal[cover]
    stack[cover, 4] = rough[cover]
    yield 0.88, "writing the maps"
    stack, filled = maps.dilate(stack, cover, margin)
    stack = maps.fill_rest(stack, filled)
    written = {}
    for key, fname in names.items():
        path = os.path.join(folder, fname)
        if key == "base_color":
            out = png.to_uint(maps.linear_to_srgb(stack[..., 0:3]))
        elif key == "metallic":
            out = png.to_uint(maps.snap_binary(stack[..., 3]))
        else:
            out = png.to_uint(stack[..., 4])
        png.write(path, out[::-1])
        written[key] = fname
        yield 0.9, "writing the maps"
    # texels of sliver triangles the baker never reached (no texel center inside them): its margin fill put another
    # island's normal there (thin dark spikes in the light): a flat normal instead
    sliver = np.zeros((n, n), bool)
    for lo in pairs:
        sliver |= lowd[lo]["unreached"]
    sliver &= cover
    nfile = (manifest.get("maps") or {}).get("normal")
    if nfile and sliver.any():
        path = os.path.join(folder, nfile)
        nm = png.read(path)
        top = 65535 if nm.dtype == np.uint16 else 255
        flat = np.array([0.5, 0.5, 1.0])
        nm = nm[::-1].copy()
        nm[sliver, :3] = (flat * top + 0.5).astype(nm.dtype)
        png.write(path, nm[::-1])
        written["normal"] = nfile
    for img in bpy.data.images:
        try:
            if img.filepath and os.path.normcase(os.path.abspath(bpy.path.abspath(img.filepath))) in {
                    os.path.normcase(os.path.abspath(os.path.join(folder, f))) for f in written.values()}:
                img.reload()
        except (RuntimeError, ReferenceError):
            pass
    return {"painted": sorted(written), "texels": int(cover.sum()), "border_texels": int(box.get("borders", 0)),
            "sliver_texels": int(sliver.sum()),
            "lookups": int(box.get("looked_up", 0)), "seconds": round(time.monotonic() - t0, 1)}


def after_bake(gen, lows):
    """Wraps a bake job (nighty.bake.bake_steps with transfer): when it is done, the parts whose dense original has
    clean colors get their color maps painted exactly (paint_steps). The bake's result gains 'clean_colors'."""
    res = yield from gen
    try:
        rep = yield from paint_steps([o for o in lows if o is not None], res["folder"], res["manifest"])
    except RuntimeError as err:      # cancelled, or Blender data gone: the baker's maps stay
        rep = {"skipped": str(err)}
    if rep:
        res["clean_colors"] = rep
    return res


def stale_and_wanted(objs, made_for, size, name):
    """True when an export would bake these parts again (their maps are stale) and they come from a clean-colors
    dense original whose colors were taken from it (bake from_high): the export then has to repaint too."""
    from .. import bake as bk
    from ..export import engines
    if not wanted(objs) or not engines.needs_maps(made_for):
        return False
    if not all(o.get("nighty_bake_transfer") for o in objs):
        return False
    folder = bk.bake_folder_of(objs) or bk.asset_folder(name)
    return not bk.fresh(objs, folder, bk.maps.size_of(size))


def export_repainted(objs, size, maps_wanted, style, name, make_export):
    """Generator: bake these parts again from their dense original, paint the maps exactly, then run the export
    (make_export() builds it now, so it finds the maps fresh and does not bake over them)."""
    from .. import bake as bk
    folder = bk.bake_folder_of(objs) or bk.asset_folder(name)
    res = yield from after_bake(bk.bake_steps(objs, size=size, maps_wanted=maps_wanted, out_dir=folder, name=name,
                                              style=style, transfer=True), objs)
    out = yield from make_export()
    if isinstance(out, dict) and res.get("clean_colors"):
        out["clean_colors"] = res["clean_colors"]
        out["baked"] = True
    return out
