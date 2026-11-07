# SPDX-License-Identifier: GPL-3.0-or-later
"""Color regions on a dense surface (pure numpy, no bpy): label every face with a palette color, smooth the labels
over the mesh (borders prefer geometric creases), then drop what an AI texture gets wrong: crumbs, thin halo strips
between two colors, small light spots of painted-on highlights.

The face graph: faces fa[i] and fb[i] share an edge of length elen[i]; crease[i] is 0 (flat) .. 1 (a crisp crease)
from the smoothed normals of the two faces.
"""

import numpy as np


# ------------------------------------------------------------------------------------------------- graph helpers

def directed(fa, fb, w):
    return np.concatenate([fa, fb]), np.concatenate([fb, fa]), np.concatenate([w, w])


class Graph:
    """Weighted neighbors for fast neighbor sums: a padded table (a triangle's 3 neighbors) or, for anything with
    more neighbors, directed edges sorted by their source (CSR)."""

    def __init__(self, n, a, b, w, table=None, table_w=None):
        self.n = n
        if table is not None:
            self.table = table
            self.tw = table_w.astype(np.float32)
            self.deg = self.tw.sum(axis=1)
            return
        self.table = None
        src, dst, ww = directed(np.asarray(a, np.int64), np.asarray(b, np.int64), np.asarray(w, np.float32))
        order = np.argsort(src, kind="stable")
        self.src, self.dst, self.w = src[order], dst[order], ww[order].astype(np.float32)
        self.deg = np.bincount(self.src, weights=self.w, minlength=n).astype(np.float32)
        counts = np.bincount(self.src, minlength=n)
        self.rows = np.nonzero(counts > 0)[0]
        self.indptr = np.concatenate([[0], np.cumsum(counts)])[self.rows]

    @classmethod
    def of_faces(cls, n, start, total, le, edge_other_a, edge_other_b, edge_w, max_sides=6):
        """The face graph straight from the polygons' edges (no sorting): edge_other_a / _b = the two faces of each
        mesh edge (-1 when the edge doesn't join exactly two), edge_w = weight per mesh edge."""
        t = int(total.max()) if n else 0
        if t > max_sides:
            ok = (edge_other_a >= 0) & (edge_other_b >= 0)
            return cls(n, edge_other_a[ok], edge_other_b[ok], edge_w[ok])
        table = np.full((n, t), n, np.int64)
        tw = np.zeros((n, t), np.float32)
        faces = np.arange(n)
        for j in range(t):
            has = total > j
            f = faces[has]
            e = le[start[f] + j]
            fa_, fb_ = edge_other_a[e], edge_other_b[e]
            other = np.where(fa_ == f, fb_, fa_)
            good = (fa_ >= 0) & (fb_ >= 0)
            table[f[good], j] = other[good]
            tw[f[good], j] = edge_w[e[good]]
        return cls(n, None, None, None, table=table, table_w=tw)

    def neighbor_mean(self, u):
        """Weighted mean of each item's neighbors (items without neighbors keep their own value)."""
        if self.table is not None:
            pad = np.concatenate([u, np.zeros((1,) + u.shape[1:], u.dtype)])
            acc = pad[self.table[:, 0]] * self.tw[:, 0, None]
            for j in range(1, self.table.shape[1]):
                acc += pad[self.table[:, j]] * self.tw[:, j, None]
            has = self.deg > 0
            out = u.copy()
            out[has] = acc[has] / self.deg[has, None]
            return out
        out = u.copy()
        if len(self.rows):
            sums = np.add.reduceat(u[self.dst] * self.w[:, None], self.indptr, axis=0)
            out[self.rows] = sums / np.maximum(self.deg[self.rows], 1e-30)[:, None]
        return out


def diffuse(u, g, steps=2, beta=0.6):
    """A few steps of graph diffusion of u (n, k): u <- (1 - beta) u + beta * (weighted mean of the neighbors)."""
    u = np.asarray(u, dtype=np.float32)
    for _ in range(steps):
        u = (1.0 - beta) * u + beta * g.neighbor_mean(u)
    return u


def smooth_vectors(v, g, steps=2):
    """Smoothed unit vectors (face normals) over the face graph g."""
    out = diffuse(v, g, steps=steps, beta=0.5).astype(np.float64)
    ln = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.maximum(ln, 1e-12)


def crease_strength(na, nb, soft=15.0, hard=45.0):
    """0 below `soft` degrees between the (smoothed) normals, 1 above `hard`."""
    ang = np.degrees(np.arccos(np.clip((na * nb).sum(axis=1), -1.0, 1.0)))
    return np.clip((ang - soft) / (hard - soft), 0.0, 1.0)


def components(n, a, b):
    """Connected component id (0..k-1) of n items joined by pairs (a[i], b[i])."""
    parent = np.arange(n, dtype=np.int64)
    a = np.asarray(a, dtype=np.int64)
    b = np.asarray(b, dtype=np.int64)
    for _ in range(500):
        pa, pb = parent[a], parent[b]
        diff = pa != pb
        if not diff.any():
            break
        pa, pb = pa[diff], pb[diff]
        lo = np.minimum(pa, pb)
        np.minimum.at(parent, pa, lo)
        np.minimum.at(parent, pb, lo)
        while True:
            pp = parent[parent]
            if np.array_equal(pp, parent):
                break
            parent = pp
    _, comp = np.unique(parent, return_inverse=True)
    return comp.reshape(-1)


# ------------------------------------------------------------------------------------------------- labeling

def data_cost(colors, centers, sigma=0.06):
    """Per face and palette color: 0 (this color) .. 1 (clearly another color), robust (capped)."""
    d = ((colors[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
    return np.minimum(d / (sigma * sigma), 1.0).astype(np.float32)


def smooth_labels(cost, g, fidelity, iters=4, steps=2, beta=0.6, init=None, progress=None):
    """MBO-style smoothing (diffuse the label indicators, add the color fit, take the best) on the face graph.
    cost (n, k) from data_cost; w: edge weights (length x how flat); fidelity: per face (or one number), how much
    the face's own color counts against its neighbors; init: the starting labels (the nearest palette color;
    the capped cost alone can't rank colors that are all far). Returns labels (n,)."""
    n, k = cost.shape
    lab = np.argmin(cost, axis=1) if init is None else np.asarray(init)
    fid = np.broadcast_to(np.asarray(fidelity, dtype=np.float32), (n,))[:, None]
    for it in range(iters):
        u = np.zeros((n, k), dtype=np.float32)
        u[np.arange(n), lab] = 1.0
        u = diffuse(u, g, steps=steps, beta=beta)
        new = np.argmax(u - fid * cost, axis=1)
        changed = int((new != lab).sum())
        lab = new
        if progress:
            progress(it, changed)
        if changed == 0:
            break
    return lab


def region_stats(lab, comp, area, colors, fa, fb, elen, k):
    """Per component: label, area, perimeter, mean color, and the shared border length with each other label."""
    nc = int(comp.max()) + 1 if len(comp) else 0
    c_lab = np.zeros(nc, dtype=np.int64)
    c_lab[comp] = lab
    c_area = np.bincount(comp, weights=area, minlength=nc)
    c_col = np.stack([np.bincount(comp, weights=area * colors[:, j], minlength=nc) for j in range(3)], axis=1)
    c_col /= np.maximum(c_area, 1e-30)[:, None]
    border = lab[fa] != lab[fb]
    ea, eb, el = fa[border], fb[border], elen[border]
    perim = (np.bincount(comp[ea], weights=el, minlength=nc) + np.bincount(comp[eb], weights=el, minlength=nc))
    # shared length per (component, other label)
    shared = (np.bincount(comp[ea] * k + lab[eb], weights=el, minlength=nc * k) +
              np.bincount(comp[eb] * k + lab[ea], weights=el, minlength=nc * k)).reshape(nc, k)
    return {"label": c_lab, "area": c_area, "color": c_col, "perimeter": perim, "shared": shared}


def _between(c, p1, p2):
    """How far color c lies off the segment p1-p2 (relative to its length), and where along it (0..1)."""
    d = p2 - p1
    ln2 = float(d @ d)
    if ln2 < 1e-12:
        return 1e9, 0.5
    t = float((c - p1) @ d) / ln2
    off = np.linalg.norm(c - (p1 + np.clip(t, 0, 1) * d)) / np.sqrt(ln2)
    return off, t


def pick_dissolve(st, centers, crumb_area, thin_width, halo_width, shading=True, highlight=True, crease=None):
    """Components to dissolve (bool per component) and why (counts): crumbs (too small to show), thin slivers,
    halo strips (a thin band whose color lies between its two neighbors' colors), shading (a narrow or small band
    that is only a lighter / darker shade of the color next to it: painted-in shadow or AO), painted-on highlights
    (a small lighter, paler spot inside one colored region), cavities (a narrow darker line inside one region that
    runs along creases: ambient occlusion painted into a groove; crease = mean crease nearness per component)."""
    nc = len(st["area"])
    out = np.zeros(nc, dtype=bool)
    why = {"crumbs": 0, "slivers": 0, "halos": 0, "shading": 0, "highlights": 0, "cavities": 0}
    area, perim, shared = st["area"], st["perimeter"], st["shared"]
    width = 2.0 * area / np.maximum(perim, 1e-30)
    total = area.sum()
    big = area > 0.02 * total
    crumbs = (area < crumb_area) & (perim > 0)
    out |= crumbs
    why["crumbs"] = int(crumbs.sum())
    slivers = ~out & (width < thin_width) & (perim > 0) & ~big
    out |= slivers
    why["slivers"] = int(slivers.sum())
    cand = np.nonzero(~out & (width < halo_width) & (perim > 0) & ~big)[0]
    for c in cand:
        row = shared[c]
        order = np.argsort(-row)
        if row[order[1]] < 0.15 * perim[c]:
            continue
        off, t = _between(st["color"][c], centers[order[0]], centers[order[1]])
        if off < 0.35 and 0.05 < t < 0.95:
            out[c] = True
            why["halos"] += 1
    if crease is not None:
        cand = np.nonzero(~out & (perim > 0) & ~big & (width < halo_width) & (crease > 0.45))[0]
        for c in cand:
            row = shared[c]
            o = int(np.argmax(row))
            if row[o] >= 0.85 * perim[c] and st["color"][c][0] < centers[o][0] - 0.05:
                out[c] = True
                why["cavities"] += 1
    if shading:
        cand = np.nonzero(~out & (perim > 0) & ~big & ((width < 2.0 * halo_width) | (area < 0.003 * total)))[0]
        for c in cand:
            row = shared[c]
            o = int(np.argmax(row))
            if row[o] < 0.5 * perim[c]:
                continue
            col, sur = st["color"][c], centers[o]
            d_ab = float(np.hypot(col[1] - sur[1], col[2] - sur[2]))
            d_l = abs(float(col[0] - sur[0]))
            if d_ab < 0.03 and 0.015 < d_l < 0.12:
                out[c] = True
                why["shading"] += 1
    if highlight:
        # a lighter, paler spot on a colored region (a highlight painted into the AI texture; it may touch the
        # region's rim, so mostly surrounded is enough)
        cand = np.nonzero(~out & (perim > 0) & ~big)[0]
        for c in cand:
            row = shared[c]
            o = int(np.argmax(row))
            if row[o] < 0.5 * perim[c]:
                continue
            sur = centers[o]
            col = st["color"][c]
            chroma_s = float(np.hypot(sur[1], sur[2]))
            chroma_c = float(np.hypot(col[1], col[2]))
            if chroma_s < 0.06 or col[0] - sur[0] < 0.08 or chroma_c > chroma_s + 0.02:
                continue
            hue_ok = chroma_c < 0.03 or float(sur[1:] @ col[1:]) / max(chroma_s * chroma_c, 1e-9) > 0.85
            sur_area = area[st["label"] == o].sum()
            if hue_ok and area[c] < 0.3 * sur_area:
                out[c] = True
                why["highlights"] += 1
    return out, why


def fill(lab, unknown, fa, fb, w, k, family=None, max_rounds=400):
    """Labels for the `unknown` faces from their known neighbors, ring by ring (longest shared border wins).
    family (k,): when given, an unknown face only takes labels of its own label's family (a dark-grey bit inside a
    black ring becomes black, never the colors on either side of the ring)."""
    lab = lab.copy()
    own = lab.copy()
    unknown = unknown.copy()
    src, dst, ww = directed(fa, fb, w)
    m0 = unknown[src]
    src, dst, ww = src[m0], dst[m0], ww[m0]
    for _ in range(max_rounds):
        if not unknown.any():
            break
        m = unknown[src] & ~unknown[dst]
        if family is not None:
            m &= family[lab[dst]] == family[own[src]]
        if not m.any():
            break
        s_, d_, x = src[m], dst[m], ww[m] + 1e-12
        faces, inv = np.unique(s_, return_inverse=True)
        votes = np.bincount(inv * k + lab[d_], weights=x, minlength=len(faces) * k).reshape(len(faces), k)
        lab[faces] = np.argmax(votes, axis=1)
        unknown[faces] = False
    return lab, unknown


def families(centers, shares, merge=0.1):
    """Groups palette colors that are shades of one color (single linkage under `merge` in Oklab): (family id per
    color (k,), family colors (f, 3) as area-weighted means)."""
    k = len(centers)
    fam = np.arange(k)
    d = np.sqrt(((centers[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2))
    for i in range(k):
        for j in range(i + 1, k):
            if d[i, j] < merge:
                fam[fam == fam[j]] = fam[i]
    _, fam = np.unique(fam, return_inverse=True)
    nf = int(fam.max()) + 1 if k else 0
    w = np.asarray(shares, dtype=np.float64) + 1e-12
    fc = np.stack([np.bincount(fam, weights=w * centers[:, j], minlength=nf) for j in range(3)], axis=1)
    fc /= np.bincount(fam, weights=w, minlength=nf)[:, None]
    return fam, fc


def pick_within(st, fam, fam_area_of, halo_width):
    """Palette-color components to dissolve INSIDE their family (shades of one color): small or narrow bits whose
    border is mostly with other shades of the same family (the AI's darker / lighter patches, halos on the same
    color, the fragments of a ring painted in two near-black shades)."""
    nc = len(st["area"])
    area, perim, shared = st["area"], st["perimeter"], st["shared"]
    width = 2.0 * area / np.maximum(perim, 1e-30)
    same = fam[None, :] == fam[st["label"]][:, None]
    same_len = (shared * same).sum(axis=1)
    small = (area < 0.25 * fam_area_of) | (width < halo_width)
    return (perim > 0) & small & (same_len >= 0.4 * perim) & (area < 0.5 * fam_area_of)


def vertex_shares(lab, area, loop_face, loop_vert, nverts, k):
    """Per vertex and label: the share of the area around the vertex with that label (n_verts, k)."""
    a = area[loop_face]
    tot = np.bincount(loop_vert, weights=a, minlength=nverts)
    out = np.zeros((nverts, k), dtype=np.float32)
    lf = lab[loop_face]
    for j in range(k):
        out[:, j] = np.bincount(loop_vert, weights=a * (lf == j), minlength=nverts)
    out /= np.maximum(tot, 1e-30)[:, None]
    return out


def taubin_band(u, g, iters, lam=0.5, mu=-0.53, rings=None):
    """Taubin (lambda / mu) smoothing of the label shares u (n, k) along the surface, only near borders (the rest
    is one region and stays as it is). Alternating a blur step and a slightly stronger un-blur step removes the
    wobble of the borders but keeps the size of the regions: a plain blur shrinks small dots and rounds them away,
    this makes a blobby dot round and a wavy edge straight. g: the vertex graph (crease edges nearly cut, so borders
    that lie on a real crease stay on it). Returns the smoothed shares (float32)."""
    u = np.asarray(u, dtype=np.float32).copy()
    if iters <= 0 or len(u) == 0 or g.table is not None:
        return u
    n = len(u)
    band = u.max(axis=1) < 0.999
    rings = min(2 * int(iters) + 2, 8) if rings is None else rings   # farther off the borders nothing moves
    src, dst = g.src, g.dst
    for _ in range(rings):          # every vertex the smoothing can reach
        grow = np.bincount(src, weights=band[dst].astype(np.float64), minlength=n) > 0
        if not (grow & ~band).any():
            break
        band |= grow
    m = band[src]                    # directed edges out of the band (sorted by source, like g's)
    s_src, s_dst, s_w = src[m], dst[m], g.w[m]
    if len(s_src) == 0:
        return u
    rows, start = np.unique(s_src, return_index=True)
    deg = np.maximum(np.add.reduceat(s_w, start), 1e-12)
    # work on the band only: neighbors outside it never change, their part of each sum is computed once
    local = np.full(n, -1, np.int64)
    local[rows] = np.arange(len(rows))
    inner = local[s_dst] >= 0
    seg = np.repeat(np.arange(len(rows)), np.diff(np.append(start, len(s_src))))
    k = u.shape[1]
    const = np.zeros((len(rows), k), np.float32)
    if (~inner).any():
        for j in range(k):
            const[:, j] = np.bincount(seg[~inner], weights=s_w[~inner] * u[s_dst[~inner], j], minlength=len(rows))
    i_seg, i_dst, i_w = seg[inner], local[s_dst[inner]], s_w[inner].astype(np.float32)
    order = np.argsort(i_seg, kind="stable")
    i_seg, i_dst, i_w = i_seg[order], i_dst[order], i_w[order]
    i_rows, i_start = np.unique(i_seg, return_index=True)
    ub = u[rows].copy()
    inv_deg = (1.0 / deg).astype(np.float32)[:, None]
    for _ in range(int(iters)):
        for f in (lam, mu):
            acc = const.copy()
            if len(i_rows):
                acc[i_rows] += np.add.reduceat(ub[i_dst] * i_w[:, None], i_start, axis=0)
            ub += f * (acc * inv_deg - ub)
    u[rows] = ub
    return u
