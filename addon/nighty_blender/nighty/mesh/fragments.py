# SPDX-License-Identifier: GPL-3.0-or-later
"""Smooths the small ragged bits an image -> 3D generator leaves inside narrow grooves and slits (lumps, pits and
spikes on the walls of a panel line or of the seam where a floating part was joined): only spots that are rough
(faces whose neighbours turn sharply away on two or more sides, which a real crease never does) AND sit in a
narrow groove (the face looks at another wall close by) are touched, with a shrink-free smoothing that stops
short of the groove's own size; anything that would make faces cross is put back.

    from nighty.mesh.fragments import smooth_fragments
    spots = smooth_fragments(obj)   # [{"vertices": n, "width_mm": w, "moved_mm": m}]
"""

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import _util as U
from .untangle import crossing_pairs

ROUGH_DOT = 0.5      # a neighbour turned more than 60 degrees away counts as a sharp turn
GROOVE = 0.012       # a groove / slit: another wall facing this one within this share of the size
SPIKE = 0.004        # a spike / pit: rough faces spanning at most this share of the size


def _edge_neighbours(nv, ev):
    """Neighbour sums helper: (a, b) edge vertex arrays and the vertex degree."""
    a, b = ev[:, 0], ev[:, 1]
    deg = np.bincount(a, minlength=nv) + np.bincount(b, minlength=nv)
    return a, b, np.maximum(deg, 1)


def smooth_fragments(obj, groove=GROOVE, iterations=20):
    """See the module doc. Returns one entry per spot smoothed."""
    me = obj.data
    nf = len(me.polygons)
    if nf == 0:
        return []
    co = U.verts(me).astype(np.float64)
    nv = len(co)
    size = U.diag(co) or 1.0
    start, total, lv, le = U.polys(me)
    lf = U.loop_face(start, total)
    n = U.face_normals(me).astype(np.float64)
    c = U.face_centers(me)
    _ids, fa, fb, _count = U.edge_faces(me, start, total, le)
    ev = U.edges(me)
    a, b, deg = _edge_neighbours(nv, ev)
    free = np.zeros(nv, dtype=bool)
    limit = np.zeros(nv)
    out = []
    boxes = []

    def inner(mask):
        """Vertices of `mask` whose neighbours are all in it (the outline stays put)."""
        edge_out = mask[a] != mask[b]
        border = np.zeros(nv, dtype=bool)
        border[a[edge_out]] = True
        border[b[edge_out]] = True
        return mask & ~border
    # tiny spikes and pits: a few faces that turn sharply on two or more sides
    sharp = np.einsum("ij,ij->i", n[fa], n[fb]) < ROUGH_DOT
    turns = np.bincount(fa[sharp], minlength=nf) + np.bincount(fb[sharp], minlength=nf)
    rough = turns >= 2
    if rough.any():
        both = rough[fa] & rough[fb]
        lab = U.components(nf, np.stack([fa[both], fb[both]], axis=1))
        t, tp = U.tris(me)
        tree = BVHTree.FromPolygons([Vector(v) for v in co], t.tolist(), all_triangles=True)
        eps = 1e-5 * size
        edge = float(np.median(np.linalg.norm(co[a] - co[b], axis=1)))
        for L in np.unique(lab[rough]):
            f = np.nonzero((lab == L) & rough)[0]
            ext = float(np.ptp(c[f], axis=0).max()) if len(f) > 1 else 0.0
            if ext > SPIKE * size:
                continue
            # the faces around it: does the spot sit in a narrow groove?
            vs = np.unique(lv[np.isin(lf, f)])
            ring = np.zeros(nv, dtype=bool)
            ring[vs] = True
            ring[b[ring[a]]] = True
            ring[a[ring[b]]] = True
            rf = np.unique(lf[ring[lv]])
            widths = []
            sample = rf[:: max(1, len(rf) // 40)]
            for i in sample:
                h = tree.ray_cast(Vector(c[i] + n[i] * eps), Vector(n[i]), groove * size)
                if h[0] is not None and float(np.dot(n[i], n[tp[h[2]]])) < -0.85:   # walls facing each other
                    widths.append(h[3])
            if len(widths) < max(2, 0.25 * len(sample)):
                continue
            width = float(np.percentile(widths, 90))
            if width < 2.5 * edge:   # a voxel step's own faces, an inside corner: not a groove
                continue
            if ext > 0.5 * width:   # only bits far smaller than the groove
                continue
            fr = inner(ring)
            if not fr.any():
                continue
            free |= fr
            limit[fr] = np.maximum(limit[fr], 0.3 * width)
            boxes.append((co[fr].min(axis=0) - 1.5 * width, co[fr].max(axis=0) + 1.5 * width))
            out.append({"vertices": int(fr.sum()), "width_mm": round(width * 1000, 1)})
    if not free.any():
        return []
    # all spots at once, only over the edges that touch them (Taubin: smooths without shrinking)
    sub = free[a] | free[b]
    sa, sb = a[sub], b[sub]
    p = co.copy()
    for _ in range(iterations):
        for k in (0.5, -0.53):
            s_ = np.zeros_like(p)
            np.add.at(s_, sa, p[sb])
            np.add.at(s_, sb, p[sa])
            p[free] += k * (s_[free] / deg[free][:, None] - p[free])
    disp = p - co
    ln = np.linalg.norm(disp, axis=1)
    over = ln > limit
    disp[over] *= (limit[over] / np.maximum(ln[over], 1e-30))[:, None]
    U.set_verts(me, co + disp)
    if not _put_back_crossings(obj, co, free, boxes, size):
        return []
    moved = np.linalg.norm(U.verts(me) - co, axis=1)
    for o in out:
        o["moved_mm"] = round(float(moved.max()) * 1000, 2)
    return out


def _put_back_crossings(obj, old, moved, boxes, size):
    """Faces the smoothing made cross: their moved vertices (and neighbours) go back, until nothing crosses."""
    bm = U.bm_from(obj)
    bm.verts.ensure_lookup_table()
    idx = np.nonzero(moved)[0]
    mv = {bm.verts[i] for i in idx}
    near = {f for v in mv for f in v.link_faces}
    for _ in range(2):
        near |= {g for f in list(near) for v in f.verts for g in v.link_faces}
    # anything else close in space (the other wall of the groove): faces with a vertex in a spot's box
    inbox = np.zeros(len(old), dtype=bool)
    for lo, hi in boxes:
        inbox |= np.all((old >= lo) & (old <= hi), axis=1)
    for i in np.nonzero(inbox)[0]:
        near.update(bm.verts[i].link_faces)
    region = list(near)
    tol = 1e-6 * size
    now = {v: v.co.copy() for v in mv}
    for v in mv:
        v.co = Vector(old[v.index])
    there = {frozenset(p) for p in crossing_pairs(region, tol)}   # crossings that were there before (left alone)
    for v, p in now.items():
        v.co = p

    def new_pairs():
        return [p for p in crossing_pairs(region, tol) if frozenset(p) not in there]
    for _ in range(12):
        bad = new_pairs()
        if not bad:
            break
        back = set()
        for f1, f2 in bad:
            for v in (*f1.verts, *f2.verts):
                for w in [v] + [e.other_vert(v) for e in v.link_edges]:
                    if w in mv and (w.co - Vector(old[w.index])).length > 0:
                        back.add(w)
        if not back:
            break
        for w in back:
            w.co = Vector(old[w.index])
    else:
        for w in mv:
            w.co = Vector(old[w.index])
    if new_pairs():   # still crossing: leave it all as it was
        for w in mv:
            w.co = Vector(old[w.index])
    kept = any((w.co - Vector(old[w.index])).length > 0 for w in mv)
    U.bm_to(bm, obj)
    return kept
