# SPDX-License-Identifier: GPL-3.0-or-later
"""Clean colors for imported models whose texture is a few ragged flat colors (nighty.colors).

A texture from a 3D generator (common in imported models) is mostly a few flat colors with ragged borders: dark halos
around parts, a stray band of one color between two others, stair-stepped edges, a highlight painted in. This works
on the dense 3D surface (not in texture space, so there are no seams):

1. every face gets its AI color (from the model's own texture), the palette is found (k-means in Oklab, near colors
   merged, rare ones dropped);
2. faces are labeled with a palette color and the labels smoothed over the mesh (borders prefer geometric creases);
   crumbs, thin halo strips and painted highlights are dissolved into their neighbors;
3. each region gets one clean color, metallic exactly 0 or 1 and a sensible roughness (wood never metal, black
   plastic not metal unless the AI is sure);
4. the result goes on the mesh: a face attribute `nighty_color_region` (retopology keeps those borders, parts can be
   split by it), per-vertex region shares `nb_cr_<i>` and a material that shows one flat color per region with
   crisp borders that run through the triangles (no stair steps). The AI's own material is kept for `restore`.

Modes: clean (flat colors), gentle (keeps the AI's color texture, e.g. wood grain; only metal / roughness per region),
keep (nothing), auto (clean when the texture is mostly flat colors, else gentle).

    from nighty import colors
    rep = colors.clean(obj)                      # or a job: colors.clean_steps(obj) (a generator of progress)
    colors.restore(obj)                          # the AI's own material back
"""

import json
import math
import os
import time

import bpy
import numpy as np

from . import palette as P
from . import regions as R

ATTR_REGION = "nighty_color_region"      # FACE INT: the palette color of each face
SHARE_PREFIX = "nb_cr_"                  # POINT FLOAT per palette color: how much of the area around the vertex
KEY = "nighty_colors"                    # mesh property: JSON (mode, palette rows); travels with the mesh into
                                         # retopology's hidden bake source
ORIG = "nighty_colors_of"                # clean material property: the AI's own material's name (kept, fake user)
MAT_PREFIX = "NB Clean colors"
MODES = ("auto", "clean", "gentle", "keep")
MAX_COLORS = 12


# ------------------------------------------------------------------------------------------------- textures

def _tex_source(sock, depth=0):
    """(image, channel or None) feeding a shader input, through Separate Color and simple nodes."""
    if sock is None or not sock.is_linked or depth > 5:
        return None
    link = sock.links[0]
    node = link.from_node
    if node.type == "TEX_IMAGE":
        return (node.image, None) if node.image is not None else None
    if node.type in ("SEPARATE_COLOR", "SEPRGB", "SEPARATE_RGB"):
        ch = list(node.outputs).index(link.from_socket)
        r = _tex_source(node.inputs[0], depth + 1)
        return (r[0], ch) if r else None
    for inp in node.inputs:
        if inp.is_linked and inp.type in ("RGBA", "VALUE", "VECTOR") and inp.name not in ("Vector", "UV"):
            r = _tex_source(inp, depth + 1)
            if r:
                return r
    return None


def _principled(mat):
    if mat is None or mat.node_tree is None:
        return None
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def source_material(obj, slot_index=0):
    """The AI's own material of a slot (the kept original when clean colors replaced it)."""
    if slot_index >= len(obj.material_slots):
        return None
    mat = obj.material_slots[slot_index].material
    name = mat.get(ORIG) if mat is not None else None
    if name and bpy.data.materials.get(name) is not None:
        return bpy.data.materials[name]
    return mat


def info(obj):
    """The clean-colors report stored on the object's mesh (mode, palette rows), or its bake source's; or None."""
    if obj is None or obj.type != "MESH":
        return None
    raw = obj.data.get(KEY)
    if not raw and obj.get("nighty_high"):
        src = bpy.data.objects.get(obj["nighty_high"])
        raw = src.data.get(KEY) if src is not None and src.type == "MESH" else None
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def textures_of(mat):
    """{'base': (img, ch), 'metal': (img, ch) | value, 'rough': (img, ch) | value} of a Principled material, or None
    when its base color is not an image texture."""
    b = _principled(mat)
    if b is None:
        return None
    base = _tex_source(b.inputs["Base Color"])
    if not base:
        return None
    out = {"base": base}
    for key, name in (("metal", "Metallic"), ("rough", "Roughness")):
        src = _tex_source(b.inputs[name])
        out[key] = src if src else float(b.inputs[name].default_value)
    return out


def _array(img, cache):
    a = cache.get(img.name)
    if a is None:
        w, h = img.size
        a = np.empty(w * h * img.channels, dtype=np.float32)
        img.pixels.foreach_get(a)
        a = a.reshape(h, w, img.channels)
        cache[img.name] = a
    return a


def _texels(arr, uv):
    """The texel under each UV point (nearest; callers average several points per face)."""
    h, w = arr.shape[:2]
    x = np.minimum((np.mod(uv[:, 0], 1.0) * w).astype(np.int64), w - 1)
    y = np.minimum((np.mod(uv[:, 1], 1.0) * h).astype(np.int64), h - 1)
    return arr[y, x]


# ------------------------------------------------------------------------------------------------- reading (main thread)

def read_steps(obj, picture=None):
    """Generator (main thread, short steps): the mesh arrays, the AI texture pixels and (optional) the generation's
    source picture. Returns `raw` (plain numpy, safe to hand to a thread)."""
    me = obj.data
    n, nl = len(me.polygons), len(me.loops)
    raw = {"n": n, "matrix": np.array(obj.matrix_world, dtype=np.float64), "picture": None}
    if picture and os.path.isfile(picture):
        try:
            img = bpy.data.images.load(picture, check_existing=False)
            try:
                raw["picture"] = _array(img, {})
            finally:
                bpy.data.images.remove(img)
        except RuntimeError:
            pass
        yield "picture"

    def get(coll, attr, count, dtype):
        a = np.empty(count, dtype)
        if count:
            coll.foreach_get(attr, a)
        return a
    raw["start"] = get(me.polygons, "loop_start", n, np.int32)
    raw["total"] = get(me.polygons, "loop_total", n, np.int32)
    raw["mat"] = get(me.polygons, "material_index", n, np.int32)
    yield "mesh"
    raw["lv"] = get(me.loops, "vertex_index", nl, np.int32)
    raw["le"] = get(me.loops, "edge_index", nl, np.int32)
    yield "mesh"
    raw["co"] = get(me.vertices, "co", len(me.vertices) * 3, np.float32).reshape(-1, 3)
    raw["ev"] = get(me.edges, "vertices", len(me.edges) * 2, np.int32).reshape(-1, 2)
    raw["uv"] = None
    if me.uv_layers:
        layer = me.uv_layers.active or me.uv_layers[0]
        raw["uv"] = get(layer.data, "uv", nl * 2, np.float32).reshape(-1, 2)
    yield "mesh"
    # the AI's textures per material slot: (base, metal, rough) as (pixel array, channel) or a plain value
    raw["slots"] = {}
    cache = {}
    for slot in range(max(1, len(obj.material_slots))):
        tex = textures_of(source_material(obj, slot))
        if tex is None:
            continue
        row = {}
        for key in ("base", "metal", "rough"):
            src = tex[key]
            if isinstance(src, tuple):
                if src[0].name not in cache:
                    cache[src[0].name] = _array(src[0], {})
                    yield "textures"
                row[key] = (cache[src[0].name], src[1])
            else:
                row[key] = float(src)
        raw["slots"][slot] = row
    raw["multi"] = len(obj.material_slots) > 1
    return raw


# ------------------------------------------------------------------------------------------------- the surface

def surface(raw):
    """World-space faces, loops, the face graph (pairs of faces sharing an edge), areas, normals."""
    n = raw["n"]
    start, total = raw["start"].astype(np.int64), raw["total"].astype(np.int64)
    lv, le = raw["lv"].astype(np.int64), raw["le"].astype(np.int64)
    mw = raw["matrix"]
    co = raw["co"].astype(np.float64) @ mw[:3, :3].T + mw[:3, 3]
    ev = raw["ev"].astype(np.int64)
    lf = np.repeat(np.arange(n), total)
    nrm = np.zeros((n, 3))
    first = co[lv[start]]
    for k in range(1, int(total.max()) - 1 if n else 0):     # a fan from the first corner: any polygon
        f = np.nonzero(total > k + 1)[0]
        nrm[f] += np.cross(co[lv[start[f] + k]] - first[f], co[lv[start[f] + k + 1]] - first[f])
    area2 = np.linalg.norm(nrm, axis=1)
    nrm = nrm / np.maximum(area2, 1e-30)[:, None]
    count = np.bincount(le, minlength=len(ev))
    order = np.argsort(le, kind="stable")
    le_s, lf_s = le[order], lf[order]
    two = np.nonzero(count == 2)[0]
    first_i = np.searchsorted(le_s, two)
    fa, fb = lf_s[first_i], lf_s[first_i + 1]
    elen = np.linalg.norm(co[ev[two, 0]] - co[ev[two, 1]], axis=1)
    lo, hi = (co.min(axis=0), co.max(axis=0)) if len(co) else (np.zeros(3), np.zeros(3))
    return {"n": n, "start": start, "total": total, "lv": lv, "le": le, "lf": lf, "co": co, "ev": ev,
            "mat": raw["mat"].astype(np.int64), "area": area2 * 0.5, "normal": nrm, "edges2": two, "fa": fa,
            "fb": fb, "elen": elen, "uv": None if raw["uv"] is None else raw["uv"].astype(np.float64),
            "size": float(np.linalg.norm(hi - lo))}


def sample(raw, s):
    """Per face: sRGB color (n, 3), AI metal (n,), AI roughness (n,), and which faces had a texture (n,) bool.
    The color is the average (in Oklab) of four points inside the face: never a texel of the next UV island."""
    n = s["n"]
    col = np.zeros((n, 3))
    metal = np.zeros(n)
    rough = np.full(n, 0.5)
    ok = np.zeros(n, bool)
    if s["uv"] is None or n == 0:
        return col, metal, rough, ok
    uv, start, total = s["uv"], s["start"], s["total"]
    cen = np.stack([np.bincount(s["lf"], weights=uv[:, j], minlength=n) for j in range(2)], axis=1)
    cen /= np.maximum(total, 1)[:, None]
    for slot, row in raw["slots"].items():
        faces = np.nonzero(s["mat"] == slot)[0] if raw["multi"] else np.arange(n)
        if len(faces) == 0:
            continue
        arr, _ch = row["base"]
        c = cen[faces]
        acc = _texels(arr, c)[:, :3].astype(np.float64)
        for k in range(3):     # three more points between the middle and the corners
            acc += _texels(arr, 0.5 * c + 0.5 * uv[start[faces] + np.minimum(k, total[faces] - 1)])[:, :3]
        col[faces] = acc / 4.0
        for key, dst in (("metal", metal), ("rough", rough)):
            src = row[key]
            if isinstance(src, tuple):
                v = _texels(src[0], c)
                dst[faces] = v[:, src[1] if src[1] is not None else 0]
            else:
                dst[faces] = src
        ok[faces] = True
    return col, metal, rough, ok


# ------------------------------------------------------------------------------------------------- the step

def _texel(s, texel=None, size=None):
    """Meters per texel of the final texture (when the caller doesn't know: 2K with 38% coverage)."""
    if texel:
        return float(texel)
    px = {"1K": 1024, "2K": 2048, "4K": 4096}.get(str(size).upper()) if size else None
    if px is None and isinstance(size, (int, float)) and size:
        px = int(size)
    px = px or 2048
    return math.sqrt(max(s["area"].sum(), 1e-12) / (0.38 * px * px))


def material_groups(centers, shares):
    """Palette colors that are one material (every shade of the wood grain) -> one group id per color. Wood-like
    browns join each other; other colors join only near shades of themselves."""
    from ..io import looks
    rgb = P.oklab_to_srgb(centers)
    k = len(centers)
    gid = np.arange(k)
    woody = np.array([looks.wood_like(tuple(c)) or looks.guess(tuple(c), False)[0] in ("wood", "leather")
                      for c in rgb])
    d = np.sqrt(((centers[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2))
    for i in range(k):
        for j in range(i + 1, k):
            if (woody[i] and woody[j]) or d[i, j] < 0.1:
                gid[gid == gid[j]] = gid[i]
    _, gid = np.unique(gid, return_inverse=True)
    return gid


def region_material(rgb, ai_metal_share, ai_rough):
    """(metal 0/1, roughness, kind) for a region of this sRGB color, from the AI's own metal share and roughness:
    metal only when the AI says so and the color can be metal (wood and strong paint never; near-black only when
    the AI is sure); roughness kept inside a sensible range for the kind."""
    from ..io import looks
    lab = P.srgb_to_oklab(np.asarray(rgb, dtype=np.float64))
    metal = bool(looks.metal_ok(tuple(rgb), ai_metal_share))
    if metal and lab[0] < 0.32 and ai_metal_share < 0.8:
        metal = False
    kind, _paint = looks.guess(tuple(rgb), metal)
    lo, hi = rough_range(kind, metal)
    return int(metal), round(float(np.clip(ai_rough, lo, hi)), 3), kind


def rough_range(kind, metal):
    """Sensible roughness for a kind of surface (the AI's own value is kept inside it)."""
    if metal:
        return 0.15, 0.6
    return (0.5, 0.9) if kind in ("wood", "leather", "fabric", "stone", "concrete") else (0.3, 0.85)


def _drop_blends(centers, shares, lab, s, halo_w, rep):
    """Palette colors that are only the blend where two others meet (P.transitions) AND lie on the surface as
    narrow bands, never as a real area of their own (a dim-orange panel stays): dropped."""
    cand = P.transitions(centers, shares)
    if not cand.any() or cand.all():
        return centers, shares
    near, _d = P.nearest(lab, centers)
    fa, fb, a = s["fa"], s["fb"], s["area"]
    drop = np.zeros(len(centers), bool)
    for i in np.nonzero(cand)[0]:
        m = near == i
        e = m[fa] & m[fb]
        idx = np.nonzero(m)[0]
        if len(idx) == 0:
            drop[i] = True
            continue
        sub = np.full(len(near), -1, np.int64)
        sub[idx] = np.arange(len(idx))
        comp = R.components(len(idx), sub[fa[e]], sub[fb[e]])
        ca = np.bincount(comp, weights=a[idx])
        border = m[fa] != m[fb]
        el = s["elen"][border]
        own = np.where(m[fa[border]], fa[border], fb[border])
        cp = np.bincount(comp[sub[own]], weights=el, minlength=len(ca))
        width = 2.0 * ca / np.maximum(cp, 1e-30)
        big = (width > 1.5 * halo_w) & (ca > (4.0 * halo_w) ** 2)
        drop[i] = not big.any()
    if drop.any() and not drop.all():
        rep["blends_dropped"] = [P.hex_of(c) for c in P.oklab_to_srgb(centers[drop])]
        return centers[~drop], shares[~drop]
    return centers, shares


def compute(raw, mode="auto", texel=None, size=None, progress=None, picture_fix=True):
    """Everything between reading and writing (pure numpy: runs in a thread). Returns the report with the arrays
    `_labels` (per face) and `_shares` (per vertex, per region color)."""
    p = progress or (lambda f, msg: None)
    times = {}
    t = time.monotonic()
    rep = {"asked": mode}
    s = surface(raw)
    if s["n"] == 0:
        raise ValueError("the mesh has no faces")
    p(0.12, "reading the AI colors")
    col, metal, rough, ok = sample(raw, s)
    if not ok.any():
        raise ValueError("no image texture for the base color (nothing to clean)")
    times["sample"] = round(time.monotonic() - t, 2)
    t = time.monotonic()
    area = s["area"] * ok + 1e-30
    lab = P.srgb_to_oklab(col)
    p(0.25, "finding the palette")
    tex = _texel(s, texel, size)
    noise = math.sqrt(max(s["area"].sum(), 1e-12) / max(s["n"], 1)) * 1.4   # the AI's own grain (face size)
    scale = max(tex, noise)
    halo_w = max(3.5 * scale, 0.004 * s["size"])
    border_len = 9.0 * noise / 1.4         # how far the border regularizing reaches (about 9 AI faces)
    centers, shares = P.fit(lab, area, k=MAX_COLORS, merge=0.05, min_share=0.0008)
    centers, shares = _drop_blends(centers, shares, lab, s, halo_w, rep)
    flat, _med = P.flatness(lab, area, centers)
    # painted / plastic: neighbors of one color have the same color and borders are few; grain / photo textures
    # change color from face to face (many borders between shades, much variation along the surface)
    near, _d = P.nearest(lab, centers)
    fa0, fb0, el0 = s["fa"], s["fb"], s["elen"]
    border = float(el0[near[fa0] != near[fb0]].sum() / max(el0.sum(), 1e-30))
    same0 = near[fa0] == near[fb0]
    step = np.sqrt(((lab[fa0[same0]] - lab[fb0[same0]]) ** 2).sum(axis=1))
    wiggle = float(np.mean(step)) if len(step) else 0.0
    rep["texture"] = {"flat_share": round(flat, 3), "border_share": round(border, 4), "wiggle": round(wiggle, 4)}
    if mode == "auto":
        mode = "clean" if (flat >= 0.8 and len(centers) <= 10 and border < 0.055 and wiggle < 0.006) else "gentle"
        rep["why"] = (f"mostly flat colors ({len(centers)}): cleaned to flat colors with crisp borders"
                      if mode == "clean" else
                      "real texture detail (the color changes all along the surface, e.g. wood grain): the AI's "
                      "colors kept; metal and roughness cleaned per material region")
    rep["mode"] = mode
    rep["flat_share"] = round(flat, 3)
    group = None
    if mode == "gentle":
        # regions at the material level (all the wood one region, the brass latch another), not every shade
        centers, shares = P.fit(lab, area, k=MAX_COLORS, merge=0.05, min_share=0.0005)
        centers, shares = _drop_blends(centers, shares, lab, s, halo_w, {})
        group = material_groups(centers, shares)
        ng = int(group.max()) + 1
        gw = np.bincount(group, weights=shares, minlength=ng)
        centers_g = np.stack([np.bincount(group, weights=shares * centers[:, j], minlength=ng) for j in range(3)],
                             axis=1) / np.maximum(gw, 1e-30)[:, None]
    k = len(centers) if group is None else ng
    times["palette"] = round(time.monotonic() - t, 2)
    # 1. labels: the color fit + smoothing over the mesh; borders prefer creases (cheap to cross, and the color
    # fit counts less next to a crease, so a ragged border moves onto it)
    p(0.35, "labeling the surface")
    t = time.monotonic()
    fa, fb, elen = s["fa"], s["fb"], s["elen"]
    ne = len(s["ev"])
    ea, eb = np.full(ne, -1, np.int64), np.full(ne, -1, np.int64)
    ea[s["edges2"]], eb[s["edges2"]] = fa, fb
    e_len = np.zeros(ne)
    e_len[s["edges2"]] = elen

    def face_graph(weights):
        return R.Graph.of_faces(s["n"], s["start"], s["total"], s["le"], ea, eb, weights)
    g_len = face_graph(e_len)
    sn = R.smooth_vectors(s["normal"], g_len, steps=2)
    crease = R.crease_strength(sn[fa], sn[fb])
    w = elen * (1.0 - 0.92 * crease)
    e_w = np.zeros(ne)
    e_w[s["edges2"]] = w
    g = face_graph(e_w)
    cprox = np.zeros(s["n"])
    np.maximum.at(cprox, fa, crease)
    np.maximum.at(cprox, fb, crease)
    cprox = R.diffuse(cprox[:, None], g_len, steps=2, beta=0.7)[:, 0]
    sigma = 0.06 if mode == "clean" else 0.1
    d2 = ((lab[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
    if group is not None:          # a face's distance to a material region = to its nearest member color
        d2 = np.stack([d2[:, group == g].min(axis=1) for g in range(ng)], axis=1)
        centers, shares = centers_g, gw
    init = np.argmin(d2, axis=1)
    cost = np.minimum(d2 / (sigma * sigma), 1.0).astype(np.float32)
    cost[~ok] = 0.0
    fid = (0.55 if mode == "clean" else 0.35) * (1.0 - 0.75 * np.clip(cprox * 1.5, 0, 1))
    labels = R.smooth_labels(cost, g, fid.astype(np.float32), iters=4, steps=2, beta=0.6, init=init)
    times["labels"] = round(time.monotonic() - t, 2)
    # 2. drop crumbs, slivers, halos, shading and painted highlights (twice: one gone can uncover another)
    p(0.6, "dropping crumbs and halos")
    t = time.monotonic()
    dropped = {"shades": 0}
    # families: palette colors that are shades of one color (black and dark grey, a grey and its painted shadow)
    fam, fcol = R.families(centers, shares, merge=0.1)
    nf = len(fcol)
    n = s["n"]

    def comps(lab_):
        same = lab_[fa] == lab_[fb]
        return R.components(n, fa[same], fb[same])
    for _ in range(2):
        # a) inside a family: small / narrow bits of another shade join the shade around them
        fcomp = comps(fam[labels])
        farea = np.bincount(fcomp, weights=s["area"])
        comp = comps(labels)
        st = R.region_stats(labels, comp, s["area"], lab, fa, fb, elen, k)
        one = np.zeros(len(st["area"]), np.int64)
        one[comp] = np.arange(n)
        kill_in = R.pick_within(st, fam, farea[fcomp[one]], halo_w) if mode == "clean" else np.zeros(0, bool)
        left = np.zeros(n, bool)
        if kill_in.any():
            dropped["shades"] += int(kill_in.sum())
            labels, left = R.fill(labels, kill_in[comp], fa, fb, w, k, family=fam)
        # b) between families: crumbs, slivers, halos, painted shading and highlights
        fcomp = comps(fam[labels])
        fst = R.region_stats(fam[labels], fcomp, s["area"], lab, fa, fb, elen, nf)
        fcrease = np.bincount(fcomp, weights=s["area"] * cprox) / np.maximum(fst["area"], 1e-30)
        kill, why = R.pick_dissolve(fst, fcol, crumb_area=(3.0 * scale) ** 2, thin_width=1.3 * scale,
                                    halo_width=halo_w, shading=(mode == "clean"), highlight=(mode == "clean"),
                                    crease=fcrease if mode == "clean" else None)
        for key_, v in why.items():
            dropped[key_] = dropped.get(key_, 0) + v
        if not kill.any() and not left.any() and not kill_in.any():
            break
        if kill.any() or left.any():
            labels, _left = R.fill(labels, kill[fcomp] | left, fa, fb, w, k)
    times["regions"] = round(time.monotonic() - t, 2)
    # 3. one color, metal and roughness per palette color (from the faces that really are that color)
    p(0.75, "region colors and materials")
    rows = []
    a = s["area"]
    pic = None
    if mode == "clean" and picture_fix and raw.get("picture") is not None:
        pic = P.picture_palette(raw["picture"])
    fixed_hues = []
    for j in range(k):
        m = (labels == j) & ok
        if not m.any():
            rows.append(None)
            continue
        idx = np.nonzero(m)[0]
        inl = d2[idx, j] < 0.05 ** 2
        mm = idx[inl] if inl.sum() > 0.2 * len(idx) else idx
        wj = a[mm]
        c_lab = (lab[mm] * wj[:, None]).sum(axis=0) / max(wj.sum(), 1e-30)
        better = P.toward_picture(c_lab, pic)
        if better is not None and np.sqrt(((better - c_lab) ** 2).sum()) > 0.01:
            fixed_hues.append(f"{P.hex_of(P.oklab_to_srgb(c_lab))} -> {P.hex_of(P.oklab_to_srgb(better))}")
            c_lab = better
        rgb = P.oklab_to_srgb(c_lab)
        msh = float((wj * (metal[mm] > 0.5)).sum() / max(wj.sum(), 1e-30))
        order = np.argsort(rough[mm])
        cw = np.cumsum(wj[order])
        r_med = float(rough[mm][order][np.searchsorted(cw, cw[-1] / 2)])
        met, rgh, kind = region_material(rgb, msh, r_med)
        rows.append({"color": P.hex_of(rgb), "rgb": [round(float(v), 4) for v in rgb],
                     "share": round(float(a[m].sum() / max(a.sum(), 1e-30)), 4), "metal": met, "roughness": rgh,
                     "kind": kind, "ai_metal": round(msh, 2)})
    if fixed_hues:
        # two regions that the picture says are one color (salmon and peach both the picture's orange) become one
        for i in range(k):
            for j in range(i + 1, k):
                if rows[i] is None or rows[j] is None:
                    continue
                li, lj = P.srgb_to_oklab(np.array(rows[i]["rgb"])), P.srgb_to_oklab(np.array(rows[j]["rgb"]))
                if np.sqrt(((li - lj) ** 2).sum()) < 0.06:
                    big, small = (i, j) if rows[i]["share"] >= rows[j]["share"] else (j, i)
                    wb, ws = rows[big]["share"], rows[small]["share"]
                    mix = P.oklab_to_srgb((li * rows[i]["share"] + lj * rows[j]["share"]) / max(wb + ws, 1e-30))
                    rows[big].update(rgb=[round(float(v), 4) for v in mix], color=P.hex_of(mix),
                                     share=round(wb + ws, 4))
                    labels[labels == small] = big
                    rows[small] = None
    keep = [j for j in range(k) if rows[j] is not None]
    remap = np.full(k, -1, np.int64)
    remap[keep] = np.arange(len(keep))
    rep["relabeled_share"] = round(float(a[init != labels].sum() / max(a.sum(), 1e-30)), 4)
    labels = remap[labels]
    rows = [rows[j] for j in keep]
    k = len(rows)
    rep["palette"] = rows
    rep["dropped"] = dropped
    if fixed_hues:
        rep["hue_from_picture"] = fixed_hues
    # 4. per-vertex region shares, smoothed along the surface (not across creases): the borders become smooth
    # curves through the triangles instead of stair steps along them
    p(0.85, "smoothing the borders")
    t = time.monotonic()
    vs = R.vertex_shares(labels, a, s["lf"], s["lv"], len(s["co"]), k)
    ev = s["ev"]
    e_crease = np.zeros(len(ev))
    e_crease[s["edges2"]] = crease
    vg = R.Graph(len(s["co"]), ev[:, 0], ev[:, 1], 1.0 - 0.92 * e_crease)
    vs = R.diffuse(vs, vg, steps=2, beta=0.5)
    if mode == "clean":
        # regularize the borders where no crease holds them: blobby dots become round, wavy edges straight, and
        # nothing shrinks (Taubin smoothing); the length it works over follows the AI's own grain (its face size)
        edge = float(np.median(np.linalg.norm(s["co"][ev[:, 0]] - s["co"][ev[:, 1]], axis=1))) if len(ev) else 1.0
        iters = int(np.clip(round((border_len / max(edge, 1e-9)) ** 2 / 2.0), 4, 60))
        t1 = time.monotonic()
        vs = R.taubin_band(vs, vg, iters)
        times["taubin"] = round(time.monotonic() - t1, 2)
        rep["border_smoothing"] = {"iterations": iters, "length_mm": round(border_len * 1000, 2)}
        n_round = _round_dots(labels, vs, s, k, r_max=max(6.0 * scale, 0.012 * s["size"]), edge=edge)
        if n_round:
            rep["border_smoothing"]["round_dots"] = n_round
    times["borders"] = round(time.monotonic() - t, 2)
    rep["colors"] = k
    rep["texel_mm"] = round(tex * 1000, 3)
    rep["faces"] = int(s["n"])
    rep["_labels"] = labels.astype(np.int32)
    rep["_shares"] = vs
    rep["_times"] = times
    return rep


def _round_dots(labels, vs, s, k, r_max, edge):
    """Small, nearly round regions inside one other region (indicator dots, rivets, small lights) are drawn as true
    disks of the same area: the AI paints them as blobs. Writes the shares in place; returns how many."""
    fa, fb = s["fa"], s["fb"]
    same = labels[fa] == labels[fb]
    comp = R.components(s["n"], fa[same], fb[same])
    nc = int(comp.max()) + 1 if len(comp) else 0
    area = s["area"]
    c_area = np.bincount(comp, weights=area, minlength=nc)
    is_small = (c_area > 0) & (c_area < np.pi * r_max * r_max)
    if not is_small.any():
        return 0
    # each small component's border: the other side's label and the shared length (one pass over the edges)
    border = ~same
    ea, eb, el = fa[border], fb[border], s["elen"][border]
    ca, cb = comp[ea], comp[eb]
    key = np.concatenate([ca * k + labels[eb], cb * k + labels[ea]])
    wts = np.concatenate([el, el])
    keep = is_small[key // k]
    shared = {}
    if keep.any():
        u, inv = np.unique(key[keep], return_inverse=True)
        tot = np.bincount(inv, weights=wts[keep])
        for kk, v in zip(u, tot):
            shared.setdefault(int(kk // k), {})[int(kk % k)] = float(v)
    cen_f = np.zeros((s["n"], 3))
    for j in range(3):
        cen_f += s["co"][s["lv"][s["start"] + j]] / 3.0
    nv = len(s["co"])
    vn = np.zeros((nv, 3))
    for j in range(3):
        for d in range(3):
            vn[:, d] += np.bincount(s["lv"][s["start"] + j], weights=s["normal"][:, d] * area, minlength=nv)
    vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)
    order = np.argsort(comp, kind="stable")
    bounds = np.searchsorted(comp[order], np.arange(nc + 1))
    done = 0
    for c in np.nonzero(is_small)[0]:
        sur = shared.get(int(c))
        if not sur:
            continue
        o, top = max(sur.items(), key=lambda kv: kv[1])
        if top < 0.85 * sum(sur.values()):
            continue
        faces = order[bounds[c]:bounds[c + 1]]
        lab = int(labels[faces[0]])
        w = area[faces]
        c3 = (cen_f[faces] * w[:, None]).sum(0) / w.sum()
        d = cen_f[faces] - c3
        cov = (d * w[:, None]).T @ d / w.sum()
        ev = np.sort(np.linalg.eigvalsh(cov))[::-1]
        if ev[1] <= 0 or np.sqrt(ev[0] / ev[1]) > 1.5 or ev[2] > 0.25 * ev[1]:
            continue                      # long (a capsule, a slot) or not flat enough: not a dot
        nrm = (s["normal"][faces] * w[:, None]).sum(0)
        nrm /= max(np.linalg.norm(nrm), 1e-12)
        r = np.sqrt(w.sum() / np.pi)
        reach = r + 3.0 * edge
        near = np.nonzero(np.all(np.abs(s["co"] - c3) < reach, axis=1))[0]
        near = near[np.linalg.norm(s["co"][near] - c3, axis=1) < reach]
        near = near[(vn[near] @ nrm) > 0.3]
        near = near[vs[near][:, [lab, o]].sum(axis=1) > 0.9]          # never eat into a third region nearby
        if len(near) == 0:
            continue
        dist = np.linalg.norm(s["co"][near] - c3, axis=1)
        inside = np.clip(0.5 + (r - dist) / max(edge, 1e-9), 0.0, 1.0).astype(np.float32)
        vs[near] = 0.0
        vs[near, lab] = inside
        vs[near, o] = 1.0 - inside
        done += 1
    return done


def clean_steps(obj, mode="auto", texel=None, size=None, write=True, picture=None):
    """The clean-colors step as a job generator: yields (progress 0..1, message), returns the report (dict).
    Reading and writing Blender data happen in short main-thread steps; the work itself runs in a thread, so
    Blender stays responsive. mode: auto | clean | gentle | keep. texel / size: the final texture's meters per
    texel or its size (1K / 2K / 4K): smaller or thinner things than it can show are dropped."""
    import threading
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    t0 = time.monotonic()
    if mode == "keep":
        return {"object": obj.name, "asked": "keep", "mode": "keep", "why": "kept the AI's own colors"}
    yield 0.02, "reading the surface"
    gen = read_steps(obj, picture)
    while True:
        try:
            msg = next(gen)
        except StopIteration as stop:
            raw = stop.value
            break
        yield 0.05, f"reading the {msg}"
    if not raw["slots"]:
        raise ValueError(f"{obj.name} has no image texture for its base color (nothing to clean)")
    t_read = round(time.monotonic() - t0, 2)
    box = {"progress": (0.1, "working"), "result": None, "error": None}

    def work():
        try:
            box["result"] = compute(raw, mode, texel, size, lambda f, m: box.__setitem__("progress", (f, m)))
        except Exception as exc:  # noqa: BLE001 - handed back to the job
            box["error"] = exc
    th = threading.Thread(target=work, name="nighty-colors", daemon=True)
    th.start()
    while th.is_alive():
        th.join(0.02)
        yield box["progress"]
    if box["error"] is not None:
        raise box["error"]
    rep = box["result"]
    rep["object"] = obj.name
    times = {"read": t_read, **rep.pop("_times")}
    if write:
        yield 0.92, "writing the clean material"
        t = time.monotonic()
        write_result(obj, rep["_labels"], rep["_shares"], rep["palette"], rep["mode"])
        obj.data[KEY] = json.dumps({k_: rep[k_] for k_ in ("mode", "palette", "flat_share") if k_ in rep})
        times["write"] = round(time.monotonic() - t, 2)
    times["total"] = round(time.monotonic() - t0, 2)
    rep["seconds"] = times
    yield 1.0, "done"
    return rep


def run(gen):
    """Runs a step generator to the end and returns its result (scripts and tests)."""
    while True:
        try:
            next(gen)
        except StopIteration as stop:
            return stop.value


def clean(obj, mode="auto", texel=None, size=None, picture=None):
    """clean_steps in one go (scripts / tests). Returns the report without the internal arrays."""
    rep = run(clean_steps(obj, mode, texel=texel, size=size, picture=picture))
    return {k: v for k, v in rep.items() if not k.startswith("_")}


# ------------------------------------------------------------------------------------------------- writing

def _set_attr(me, name, domain, kind, values):
    a = me.attributes.get(name)
    if a is not None and (a.domain != domain or a.data_type != kind):
        me.attributes.remove(a)
        a = None
    if a is None:
        a = me.attributes.new(name, kind, domain)
    a.data.foreach_set("value", np.ascontiguousarray(values))


def _clear_attrs(me):
    for a in [a for a in me.attributes if a.name.startswith(SHARE_PREFIX) or a.name == ATTR_REGION]:
        me.attributes.remove(a)


def write_result(obj, labels, shares, rows, mode):
    me = obj.data
    _clear_attrs(me)
    _set_attr(me, ATTR_REGION, "FACE", "INT", labels.astype(np.int32))
    for j in range(len(rows)):
        _set_attr(me, f"{SHARE_PREFIX}{j}", "POINT", "FLOAT", shares[:, j].astype(np.float32))
    for i, slot in enumerate(obj.material_slots):
        orig = source_material(obj, i)
        if orig is None or textures_of(orig) is None:
            continue
        orig.use_fake_user = True
        slot.material = build_material(obj, orig, rows, mode, slot.material if slot.material is not orig else None)


def _mix(nt, kind, fac, a, b):
    """A Mix node (Blender 4.2 .. 5.x): kind 'RGBA' or 'FLOAT'; a / b are sockets or values."""
    from ..materials.compat import socket
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = kind
    suffix = "Color" if kind == "RGBA" else "Float"
    nt.links.new(fac, socket(n.inputs, "Factor_Float"))
    for name, v in (("A_" + suffix, a), ("B_" + suffix, b)):
        sk = socket(n.inputs, name)
        if hasattr(v, "is_linked"):
            nt.links.new(v, sk)
        else:
            sk.default_value = v
    return socket(n.outputs, "Result_" + suffix)


def build_material(obj, orig, rows, mode, old=None):
    """A copy of the AI's material: one flat color (clean) per region with crisp borders, metallic 0 / 1 and
    roughness per region (gentle keeps the AI's color texture)."""
    from ..materials.compat import srgb_to_linear
    if old is not None and old.name.startswith(MAT_PREFIX) and old.users <= 1:
        bpy.data.materials.remove(old)
    m = orig.copy()
    m.use_fake_user = False
    m.name = f"{MAT_PREFIX} · {obj.name}"[:63]
    m[ORIG] = orig.name
    nt = m.node_tree
    bsdf = _principled(m)
    attrs = []
    for j in range(len(rows)):
        n = nt.nodes.new("ShaderNodeAttribute")
        n.attribute_type = "GEOMETRY"
        n.attribute_name = f"{SHARE_PREFIX}{j}"
        n.label = f"region {j} {rows[j]['color']}"
        attrs.append(n.outputs["Fac"])
    lin = [tuple(srgb_to_linear(c) for c in r["rgb"]) + (1.0,) for r in rows]
    best = attrs[0]
    gts = []
    color, met, rgh = lin[0], float(rows[0]["metal"]), float(rows[0]["roughness"])
    for j in range(1, len(rows)):
        gt = nt.nodes.new("ShaderNodeMath")
        gt.operation = "GREATER_THAN"
        nt.links.new(attrs[j], gt.inputs[0])
        nt.links.new(best, gt.inputs[1])
        mx = nt.nodes.new("ShaderNodeMath")
        mx.operation = "MAXIMUM"
        nt.links.new(attrs[j], mx.inputs[0])
        nt.links.new(best, mx.inputs[1])
        best = mx.outputs[0]
        gts.append(gt.outputs[0])
        met = _mix(nt, "FLOAT", gt.outputs[0], met, float(rows[j]["metal"]))
        if mode == "clean":
            color = _mix(nt, "RGBA", gt.outputs[0], color, lin[j])
            rgh = _mix(nt, "FLOAT", gt.outputs[0], rgh, float(rows[j]["roughness"]))

    def put(sock, v):
        for link in list(sock.links):
            nt.links.remove(link)
        if hasattr(v, "is_linked"):
            nt.links.new(v, sock)
        elif sock.type == "RGBA":
            sock.default_value = v
        else:
            sock.default_value = float(v)
    if mode == "clean":
        put(bsdf.inputs["Base Color"], color)
        put(bsdf.inputs["Roughness"], rgh)
    else:
        # gentle: the AI's own roughness map, kept inside each region's sensible range
        r_in = bsdf.inputs["Roughness"]
        src = r_in.links[0].from_socket if r_in.is_linked else float(r_in.default_value)
        lo_v = [rough_range(r["kind"], r["metal"])[0] for r in rows]
        hi_v = [rough_range(r["kind"], r["metal"])[1] for r in rows]
        lo, hi = lo_v[0], hi_v[0]
        for j in range(1, len(rows)):
            lo = _mix(nt, "FLOAT", gts[j - 1], lo, lo_v[j])
            hi = _mix(nt, "FLOAT", gts[j - 1], hi, hi_v[j])
        mx = nt.nodes.new("ShaderNodeMath")
        mx.operation = "MAXIMUM"
        mn = nt.nodes.new("ShaderNodeMath")
        mn.operation = "MINIMUM"
        for sock, v in ((mx.inputs[0], src), (mx.inputs[1], lo), (mn.inputs[1], hi)):
            if hasattr(v, "is_linked"):
                nt.links.new(v, sock)
            else:
                sock.default_value = float(v)
        nt.links.new(mx.outputs[0], mn.inputs[0])
        put(r_in, mn.outputs[0])
    put(bsdf.inputs["Metallic"], met)
    # nodes the copy no longer uses (the AI color / ORM textures when they feed nothing) are left: harmless
    return m


def restore(obj):
    """The AI's own material back, the region attributes removed. Returns True when something changed."""
    changed = False
    for slot in obj.material_slots:
        cur = slot.material
        name = cur.get(ORIG) if cur is not None else None
        if name and bpy.data.materials.get(name) is not None:
            slot.material = bpy.data.materials[name]
            changed = True
            if cur.users == 0:
                bpy.data.materials.remove(cur)
    if obj.type == "MESH":
        before = len(obj.data.attributes)
        _clear_attrs(obj.data)
        changed |= len(obj.data.attributes) != before
        if KEY in obj.data:
            del obj.data[KEY]
            changed = True
    return changed


# ------------------------------------------------------------------------------------------------- low poly / parts

def _face_centers_world(obj):
    me = obj.data
    c = np.empty(len(me.polygons) * 3, np.float32)
    me.polygons.foreach_get("center", c)
    mw = np.array(obj.matrix_world, dtype=np.float64)
    return c.reshape(-1, 3).astype(np.float64) @ mw[:3, :3].T + mw[:3, 3]


def carry_to(low, high, refresh=False):
    """The dense original's regions onto its low poly (or a part of it). A triangle decimate keeps them by itself
    (then only the report and the clean material are passed on); otherwise (quads are rebuilt from scratch, or
    refresh) each low face takes the region of the nearest dense face and each vertex the shares there.
    Returns the region count."""
    from mathutils import kdtree
    hm = high.data
    a = hm.attributes.get(ATTR_REGION)
    rows = (info(high) or {}).get("palette") or []
    if a is None or not rows or len(low.data.polygons) == 0:
        return 0
    lm = low.data
    k = len(rows)
    have = lm.attributes.get(ATTR_REGION) is not None and all(
        lm.attributes.get(f"{SHARE_PREFIX}{j}") is not None for j in range(k))
    if have and not refresh:
        lm[KEY] = hm[KEY]
        _pass_material(low, high)
        return k
    lab = np.empty(len(hm.polygons), np.int32)
    a.data.foreach_get("value", lab)
    hc = _face_centers_world(high)
    tree = kdtree.KDTree(len(hc))
    for i, p in enumerate(hc):
        tree.insert(p, i)
    tree.balance()
    # each low face: the region most of it lies on (7 points per triangle; one point at the center would hand a
    # big flat triangle to the small latch next to it)
    lm.calc_loop_triangles()
    nt = len(lm.loop_triangles)
    ltv = np.empty(nt * 3, np.int32)
    lm.loop_triangles.foreach_get("vertices", ltv)
    lpi = np.empty(nt, np.int32)
    lm.loop_triangles.foreach_get("polygon_index", lpi)
    lco = np.empty(len(lm.vertices) * 3, np.float32)
    lm.vertices.foreach_get("co", lco)
    lmw = np.array(low.matrix_world, dtype=np.float64)
    lco = lco.reshape(-1, 3).astype(np.float64) @ lmw[:3, :3].T + lmw[:3, 3]
    tri = lco[ltv.reshape(-1, 3)]
    bary = np.array([[1, 1, 1], [4, 1, 1], [1, 4, 1], [1, 1, 4], [2, 2, 1], [1, 2, 2], [2, 1, 2]], np.float64)
    bary /= bary.sum(axis=1, keepdims=True)
    pts = np.einsum("sk,tkd->tsd", bary, tri).reshape(-1, 3)
    near = np.array([tree.find(p)[1] for p in pts], dtype=np.int64)
    k_ = int(lab.max()) + 1
    poly = np.repeat(lpi.astype(np.int64), len(bary))
    votes = np.bincount(poly * k_ + lab[near], minlength=len(lm.polygons) * k_).reshape(len(lm.polygons), k_)
    _set_attr(lm, ATTR_REGION, "FACE", "INT", np.argmax(votes, axis=1).astype(np.int32))
    if any(lm.attributes.get(f"{SHARE_PREFIX}{j}") is None for j in range(k)):
        # per vertex: the shares of the nearest dense face's corners (averaged)
        hs = np.zeros((len(hm.vertices), k), np.float32)
        for j in range(k):
            at = hm.attributes.get(f"{SHARE_PREFIX}{j}")
            if at is not None:
                at.data.foreach_get("value", hs[:, j])
        st = np.empty(len(hm.polygons), np.int32)
        tt = np.empty(len(hm.polygons), np.int32)
        hm.polygons.foreach_get("loop_start", st)
        hm.polygons.foreach_get("loop_total", tt)
        lv = np.empty(len(hm.loops), np.int32)
        hm.loops.foreach_get("vertex_index", lv)
        face_sh = np.zeros((len(hm.polygons), k), np.float32)
        for c in range(3):
            face_sh += hs[lv[st + np.minimum(c, tt - 1)]]
        face_sh /= 3.0
        co = np.empty(len(lm.vertices) * 3, np.float32)
        lm.vertices.foreach_get("co", co)
        mw = np.array(low.matrix_world, dtype=np.float64)
        co = co.reshape(-1, 3).astype(np.float64) @ mw[:3, :3].T + mw[:3, 3]
        vnear = np.array([tree.find(p)[1] for p in co], dtype=np.int64)
        for j in range(k):
            _set_attr(lm, f"{SHARE_PREFIX}{j}", "POINT", "FLOAT", face_sh[vnear, j])
    lm[KEY] = hm[KEY]
    _pass_material(low, high)
    return k


def _pass_material(low, high):
    for i, slot in enumerate(high.material_slots):
        clean_m = slot.material
        if i < len(low.material_slots) and clean_m is not None and clean_m.get(ORIG):
            cur = low.material_slots[i].material      # only the AI's material or an older clean one is replaced,
            if cur is None or cur.get(ORIG) or cur.name == clean_m[ORIG]:      # never a baked or library one
                low.material_slots[i].material = clean_m


def face_regions(obj):
    """Per-face region index of a mesh that carries them (low poly or dense), or None."""
    a = obj.data.attributes.get(ATTR_REGION) if obj.type == "MESH" else None
    if a is None or a.domain != "FACE":
        return None
    lab = np.empty(len(obj.data.polygons), np.int32)
    a.data.foreach_get("value", lab)
    return lab


def part_looks(parts):
    """Each part's own color and metal share from its color regions: {part: ((r, g, b) sRGB, metal share,
    region row)}, the region that covers most of the part. None when the parts carry no regions."""
    out = {}
    for o in parts:
        rows = (info(o) or {}).get("palette")
        lab = face_regions(o)
        if not rows or lab is None or len(lab) == 0:
            continue
        area = np.empty(len(o.data.polygons), np.float32)
        o.data.polygons.foreach_get("area", area)
        w = np.bincount(lab.clip(0, len(rows) - 1), weights=area, minlength=len(rows))
        r = rows[int(np.argmax(w))]
        out[o.name] = (tuple(r["rgb"]), float(r["metal"]), r)
    return out or None


def mark_parts(obj):
    """Writes the face attribute split_parts(method='attribute') splits by: one part per color region (all the wood
    one part, the brass latch another), named after what each region looks like. Returns the number of parts, 0
    when there are no regions (or only one)."""
    lab = face_regions(obj)
    rows = (info(obj) or {}).get("palette")
    if lab is None or not rows:
        return 0
    used = np.unique(lab)
    if len(used) < 2:
        return 0
    _set_attr(obj.data, "nighty_part", "FACE", "INT", lab.astype(np.int32))
    names, seen = {}, {}
    for j in used:
        base = rows[int(j)]["kind"] if int(j) < len(rows) else f"region{int(j)}"
        seen[base] = seen.get(base, 0) + 1
        names[str(int(j))] = base if seen[base] == 1 else f"{base}{seen[base]}"
    obj["nighty_part_names"] = names
    return len(used)
