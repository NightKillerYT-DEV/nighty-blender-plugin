# SPDX-License-Identifier: GPL-3.0-or-later
"""UV layouts as pixels (numpy): islands, coverage, overlaps between islands and objects, seam edges.
Used to decide whether parts need one shared atlas, and by verify_textures (coverage, seams)."""

import numpy as np


def mesh_arrays(me, layer=None):
    """(uv per loop L x 2, triangles T x 3 loop indices, polygon of each triangle, loop vertex index) of a mesh."""
    lay = me.uv_layers.get(layer) if layer else me.uv_layers.active
    if lay is None:
        return None
    nl = len(me.loops)
    uv = np.empty(nl * 2, np.float32)
    lay.data.foreach_get("uv", uv)
    uv = uv.reshape(nl, 2)
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    tl = np.empty(nt * 3, np.int64)
    me.loop_triangles.foreach_get("loops", tl)
    tp = np.empty(nt, np.int64)
    me.loop_triangles.foreach_get("polygon_index", tp)
    lv = np.empty(nl, np.int64)
    me.loops.foreach_get("vertex_index", lv)
    return uv, tl.reshape(nt, 3), tp, lv


def islands(me, uv, lv):
    """An island id per polygon (faces joined where they share a vertex with the same UV)."""
    npoly = len(me.polygons)
    if npoly == 0:
        return np.zeros(0, np.int64)
    totals = np.empty(npoly, np.int64)
    me.polygons.foreach_get("loop_total", totals)
    face_of_loop = np.repeat(np.arange(npoly), totals)
    q = np.round(uv * 65536.0).astype(np.int64)
    keys = (lv * 1_000_003 + q[:, 0]) * 1_000_033 + q[:, 1]
    _, uvv = np.unique(keys, return_inverse=True)
    uvv = uvv.reshape(-1)
    labels = np.arange(npoly)
    big = npoly + 1
    for _ in range(10000):
        m = np.full(uvv.max() + 1, big, np.int64)
        np.minimum.at(m, uvv, labels[face_of_loop])
        new = labels.copy()
        np.minimum.at(new, face_of_loop, m[uvv])
        for _j in range(4):          # pointer jumping: converges in a few rounds
            new = new[new]
        if np.array_equal(new, labels):
            break
        labels = new
    _, compact = np.unique(labels, return_inverse=True)
    return compact.reshape(-1)


def rasterize(tri_uv, n, ids=None, win=8, id_map=False):
    """Pixel-center coverage of UV triangles (T x 3 x 2, 0..1) on an n x n grid (row 0 = v 0).
    Returns (covered n x n bool, overlap n x n bool: pixels claimed by two or more different ids), plus an
    n x n map of ids (-1 = empty) when id_map is true."""
    t = np.asarray(tri_uv, np.float64) * n - 0.5
    if len(t) == 0:
        z = np.zeros((n, n), bool)
        return (z, z.copy(), np.full((n, n), -1, np.int64)) if id_map else (z, z.copy())
    if ids is None:
        ids = np.zeros(len(t), np.int64)
    ids = np.asarray(ids, np.int64)
    a, b, c = t[:, 0], t[:, 1], t[:, 2]
    area = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    keep = np.abs(area) > 1e-12
    t, ids, area = t[keep], ids[keep], area[keep]
    sgn = np.sign(area)
    lo = np.ceil(t.min(axis=1)).astype(np.int64)
    hi = np.floor(t.max(axis=1)).astype(np.int64)
    lo = np.clip(lo, 0, n - 1)
    hi = np.clip(hi, -1, n - 1)
    size = hi - lo + 1
    valid = (size[:, 0] > 0) & (size[:, 1] > 0)
    pix_parts, id_parts = [], []

    def test(tt, s, px, py):
        # px, py: candidate pixel centers (k x m); tt: k x 3 x 2; s: k signs
        res = np.ones(px.shape, bool)
        for i in range(3):
            p0 = tt[:, i]
            p1 = tt[:, (i + 1) % 3]
            e = (p1[:, 0:1] - p0[:, 0:1]) * (py - p0[:, 1:2]) - (p1[:, 1:2] - p0[:, 1:2]) * (px - p0[:, 0:1])
            res &= e * s[:, None] >= -1e-9
        return res

    small = valid & (size[:, 0] <= win) & (size[:, 1] <= win)
    if small.any():
        tt, s, l0, ii = t[small], sgn[small], lo[small], ids[small]
        ox, oy = np.meshgrid(np.arange(win), np.arange(win))
        ox, oy = ox.reshape(-1), oy.reshape(-1)
        for start in range(0, len(tt), 20000):
            sl = slice(start, start + 20000)
            px = l0[sl, 0:1] + ox[None, :]
            py = l0[sl, 1:2] + oy[None, :]
            inside = test(tt[sl], s[sl], px.astype(np.float64), py.astype(np.float64)) & (px < n) & (py < n)
            k, m = np.nonzero(inside)
            pix_parts.append(py[k, m] * n + px[k, m])
            id_parts.append(ii[sl][k])
    for idx in np.nonzero(valid & ~small)[0]:
        x0, y0 = lo[idx]
        x1, y1 = hi[idx]
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        px = gx.reshape(1, -1).astype(np.float64)
        py = gy.reshape(1, -1).astype(np.float64)
        inside = test(t[idx:idx + 1], sgn[idx:idx + 1], px, py)[0]
        pix_parts.append((gy.reshape(-1) * n + gx.reshape(-1))[inside])
        id_parts.append(np.full(int(inside.sum()), ids[idx], np.int64))
    covered = np.zeros(n * n, bool)
    overlap = np.zeros(n * n, bool)
    idm = np.full(n * n, -1, np.int64)
    if pix_parts:
        pix = np.concatenate(pix_parts)
        pid = np.concatenate(id_parts)
        covered[pix] = True
        idm[pix] = pid
        if len(pix):
            pairs = np.unique(pix * (int(pid.max()) + 1) + pid)
            per_pixel = pairs // (int(pid.max()) + 1)
            cnt = np.bincount(per_pixel, minlength=n * n)
            overlap = cnt >= 2
    if id_map:
        return covered.reshape(n, n), overlap.reshape(n, n), idm.reshape(n, n)
    return covered.reshape(n, n), overlap.reshape(n, n)


def layout_report(objects, n=256, layer_of=None):
    """How the objects' UV layouts sit together: {'covered', 'overlap', 'outside', 'missing': [names]}.
    overlap counts pixels where different islands (of one object or of several) land on each other."""
    tris, ids, missing, outside = [], [], [], 0
    base = 0
    for obj in objects:
        me = obj.data
        arr = mesh_arrays(me, layer_of(obj) if layer_of else None)
        if arr is None:
            missing.append(obj.name)
            continue
        uv, tl, tp, lv = arr
        isl = islands(me, uv, lv)
        if len(tl) == 0:
            continue
        tri = uv[tl]
        outside += int(((tri < -1e-4) | (tri > 1 + 1e-4)).any(axis=(1, 2)).sum())
        tris.append(tri)
        ids.append(isl[tp] + base)
        base += int(isl.max()) + 1 if len(isl) else 0
    if not tris:
        return {"covered": 0.0, "overlap": 0.0, "outside": 0, "missing": missing}
    cov, ov = rasterize(np.concatenate(tris), n, np.concatenate(ids))
    c = int(cov.sum())
    return {"covered": c / float(n * n), "overlap": (int(ov.sum()) / float(max(c, 1))), "outside": outside,
            "missing": missing}


def seam_samples(me, layer, count=3, size=1024, inset=1.0, step=2.0, max_angle=0.6):
    """Points on both sides of every UV seam that runs along a smooth edge (a hard edge creases, so its two sides
    may differ for real): (a, b, a_in, b_in). a and b sit `inset` pixels into the two faces (about 2 texels apart
    on the surface, across the seam); a_in / b_in are `step` pixels further into each face (the same distance on
    the surface, no seam in between): the texture's own variation to compare with."""
    lay = me.uv_layers.get(layer) if layer else me.uv_layers.active
    empty = np.zeros((0, 2), np.float32)
    if lay is None:
        return empty, empty, empty, empty
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    uvl = bm.loops.layers.uv.get(lay.name)
    out = ([], [], [], [])
    d = inset / float(size)
    d2 = (inset + step) / float(size)
    for e in bm.edges:
        if len(e.link_loops) != 2:
            continue
        l1, l2 = e.link_loops
        if not e.smooth or l1.face.normal.angle(l2.face.normal, 0.0) > max_angle:
            continue
        u1a, u1b = l1[uvl].uv.copy(), l1.link_loop_next[uvl].uv.copy()
        u2a, u2b = l2[uvl].uv.copy(), l2.link_loop_next[uvl].uv.copy()
        if (u1a - u2b).length < 1e-6 and (u1b - u2a).length < 1e-6:
            continue   # not a seam
        if (u1b - u1a).length * size < 2.0:
            continue   # shorter than two pixels
        fc1 = sum((lp[uvl].uv for lp in l1.face.loops), u1a * 0) / len(l1.face.loops)
        fc2 = sum((lp[uvl].uv for lp in l2.face.loops), u1a * 0) / len(l2.face.loops)
        for k in range(count):
            t = (k + 0.5) / count
            p1 = u1a.lerp(u1b, t)
            p2 = u2b.lerp(u2a, t)   # the other face runs the edge the other way
            v1, v2 = fc1 - p1, fc2 - p2
            if v1.length < 1.5 * d2 or v2.length < 1.5 * d2:
                continue
            v1.normalize()
            v2.normalize()
            out[0].append(tuple(p1 + v1 * d))
            out[1].append(tuple(p2 + v2 * d))
            out[2].append(tuple(p1 + v1 * d2))
            out[3].append(tuple(p2 + v2 * d2))
    bm.free()
    return tuple(np.array(x, np.float32).reshape(-1, 2) for x in out)
