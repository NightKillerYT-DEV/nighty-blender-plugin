# SPDX-License-Identifier: GPL-3.0-or-later
"""Quick mesh numbers used before / after every topology step: face kinds, manifoldness, loose parts, normals,
sharp edges, size, surface error against another mesh. (verify_mesh in nighty proper is the full gate.)"""

import numpy as np
from mathutils.bvhtree import BVHTree
from mathutils import Vector

from . import _util as U


def analyze(obj, sharp_angle=30.0, uv=False):
    """Numbers for one mesh object (object space, scaled by the object's scale for sizes)."""
    me = obj.data
    start, total, lv, le = U.polys(me)
    nf = len(start)
    count = np.bincount(le, minlength=len(me.edges)) if len(le) else np.zeros(len(me.edges), dtype=np.int64)
    ids, ang, _concave = U.dihedral(me, start, total, le)
    co = U.world_verts(obj)
    t, _tp = U.tris(me)
    area, vol = U.tri_area_volume(co, t)
    lo, hi = U.bbox(co)
    comps = int(U.face_components(me).max() + 1) if nf else 0
    out = {
        "faces": nf,
        "tris": int((total == 3).sum()),
        "quads": int((total == 4).sum()),
        "ngons": int((total > 4).sum()),
        "triangles": int(len(t)),  # after triangulation (what a game engine counts)
        "verts": len(me.vertices),
        "edges": len(me.edges),
        "boundary_edges": int((count == 1).sum()),
        "non_manifold_edges": int((count > 2).sum()),
        "loose_edges": int((count == 0).sum()),
        "loose_verts": int(len(me.vertices) - len(np.unique(lv))) if len(lv) else len(me.vertices),
        "flipped_edges": _inconsistent(start, total, lv, le, count),
        "parts": comps,
        "sharp_edges": int((ang > sharp_angle).sum()),
        "marked_sharp": int(U.edge_flags(me, "use_edge_sharp").sum()),
        "seams": int(U.edge_flags(me, "use_seam").sum()),
        "area": round(area, 6),
        "volume": round(vol, 6),
        "size": [round(float(x), 5) for x in (hi - lo)],
        "min": [round(float(x), 5) for x in lo],
    }
    out["manifold"] = out["boundary_edges"] == 0 and out["non_manifold_edges"] == 0 and out["flipped_edges"] == 0
    out["normals_inward"] = bool(out["manifold"] and vol < 0)
    out["quad_ratio"] = round(out["quads"] / nf, 4) if nf else 0.0
    if uv:
        from . import uv as _uv
        out["uv"] = _uv.uv_report([obj])
    return out


def _inconsistent(start, total, lv, le, count):
    """Edges whose two faces walk it in the same direction (normals disagree there)."""
    if len(lv) == 0:
        return 0
    lf = U.loop_face(start, total)
    nxt = np.arange(len(lv)) + 1
    last = start + total - 1
    nxt[last] = start
    a, b = lv, lv[nxt]
    fwd = a < b
    two = count[le] == 2
    e2 = le[two]
    f2 = fwd[two]
    s = np.bincount(e2, weights=f2.astype(np.float64), minlength=len(count))
    # a consistent edge has exactly one forward and one backward walk (sum == 1)
    bad = (count == 2) & (s != 1)
    del lf
    return int(bad.sum())


def short(st):
    """A one-line summary for reports."""
    bits = [f"{st['faces']:,} faces"]
    if st["faces"]:
        if st["quads"] and st["quad_ratio"] > 0.5:
            bits.append(f"{round(st['quad_ratio'] * 100)}% quads")
        elif st["tris"] == st["faces"]:
            bits.append("all triangles")
    bits.append("manifold" if st["manifold"] else
                f"not manifold ({st['boundary_edges']} open, {st['non_manifold_edges']} bad edges)")
    if st["parts"] > 1:
        bits.append(f"{st['parts']} loose parts")
    return ", ".join(bits)


# ---------------------------------------------------------------- surface distance

def bvh(obj):
    """BVH of an object's mesh in world space."""
    co = U.world_verts(obj)
    t, _ = U.tris(obj.data)
    return BVHTree.FromPolygons([Vector(v) for v in co], t.tolist(), all_triangles=True, epsilon=0.0)


def sample_points(obj, n=4000, seed=1):
    """Area-uniform random points on an object's surface (world space)."""
    co = U.world_verts(obj)
    t, _ = U.tris(obj.data)
    if len(t) == 0:
        return np.zeros((0, 3))
    a, b, c = co[t[:, 0]], co[t[:, 1]], co[t[:, 2]]
    ar = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    if ar.sum() <= 0:
        return a[:n]
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(t), size=n, p=ar / ar.sum())
    r1 = np.sqrt(rng.random(n))[:, None]
    r2 = rng.random(n)[:, None]
    return (1 - r1) * a[pick] + r1 * (1 - r2) * b[pick] + r1 * r2 * c[pick]


def _dist_to(tree, pts):
    d = np.empty(len(pts))
    for i, p in enumerate(pts):
        hit = tree.find_nearest(Vector(p))
        d[i] = hit[3] if hit[0] is not None else np.inf
    return d


def surface_error(a, b, n=3000):
    """Two-sided distance between two objects' surfaces, as fractions of b's size: {mean, max}."""
    size = U.diag(U.world_verts(b)) or 1.0
    ta, tb = bvh(a), bvh(b)
    d1 = _dist_to(tb, sample_points(a, n, 1))
    d2 = _dist_to(ta, sample_points(b, n, 2))
    d = np.concatenate([d1, d2])
    d = d[np.isfinite(d)]
    if len(d) == 0:
        return {"mean": 1.0, "max": 1.0}
    return {"mean": round(float(d.mean()) / size, 5), "max": round(float(np.percentile(d, 99.5)) / size, 5)}


# ---------------------------------------------------------------- sharp edges kept

def sharp_segments(obj, angle=35.0, min_chain=0.0):
    """World-space segments (k, 2, 3) of the edges sharper than `angle` (or marked sharp).
    min_chain: drop sharp edges that are not part of a connected line at least this long (a fraction of the size;
    0.03 keeps real creases and drops the lone sharp edges noise makes on generated meshes)."""
    me = obj.data
    start, total, lv, le = U.polys(me)
    ids, ang, _ = U.dihedral(me, start, total, le)
    sel = ids[ang > angle]
    marked = np.nonzero(U.edge_flags(me, "use_edge_sharp"))[0]
    count = np.bincount(le, minlength=len(me.edges)) if len(le) else np.zeros(0, dtype=np.int64)
    marked = marked[count[marked] == 2] if len(marked) else marked
    sel = np.union1d(sel, marked)
    co = U.world_verts(obj)
    e = U.edges(me)[sel]
    if len(e) and min_chain > 0:
        length = np.linalg.norm(co[e[:, 0]] - co[e[:, 1]], axis=1)
        used, inv = np.unique(e.ravel(), return_inverse=True)
        lab = U.components(len(used), inv.reshape(-1, 2))[inv.reshape(-1, 2)[:, 0]]
        chain = np.bincount(lab, weights=length)
        keep = chain[lab] >= min_chain * (U.diag(co) or 1.0)
        e = e[keep]
    return np.stack([co[e[:, 0]], co[e[:, 1]]], axis=1) if len(e) else np.zeros((0, 2, 3))


def _sample_segments(seg, step):
    pts = []
    for p, q in seg:
        L = np.linalg.norm(q - p)
        k = max(1, int(L / step))
        tt = (np.arange(k) + 0.5) / k
        pts.append(p + (q - p) * tt[:, None])
    return np.concatenate(pts) if pts else np.zeros((0, 3))


def sharp_kept(source_segments, result_obj, angle=35.0, tol=None):
    """Fraction of the source's sharp-edge length that has a sharp edge of the result within `tol` (default 1.5%
    of the size). source_segments comes from sharp_segments() of the original."""
    if len(source_segments) == 0:
        return 1.0
    res = sharp_segments(result_obj, angle * 0.8)
    size = U.diag(U.world_verts(result_obj)) or 1.0
    tol = tol or 0.015 * size
    pts = _sample_segments(source_segments, tol * 0.5)
    if len(res) == 0:
        return 0.0
    rp = _sample_segments(res, tol * 0.25)
    from mathutils.kdtree import KDTree
    kd = KDTree(len(rp))
    for i, p in enumerate(rp):
        kd.insert(Vector(p), i)
    kd.balance()
    ok = 0
    for p in pts:
        _co, _i, dist = kd.find(Vector(p))
        if dist is not None and dist <= tol:
            ok += 1
    return round(ok / len(pts), 4)
