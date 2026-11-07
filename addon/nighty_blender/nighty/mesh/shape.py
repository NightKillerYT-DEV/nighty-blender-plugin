# SPDX-License-Identifier: GPL-3.0-or-later
"""What kind of shape is this? Hard-surface (flat sides, crisp edges: guns, crates, buildings) or organic (smooth,
rounded: characters, rocks, plants). Also: is it mirror-symmetric, and on which axis."""

import numpy as np
from mathutils import Vector

from . import _util as U


def _cube_bins(n, res=12):
    """Bin unit normals on a cube map (6 * res * res bins)."""
    a = np.abs(n)
    axis = a.argmax(axis=1)
    sign = (n[np.arange(len(n)), axis] < 0).astype(np.int64)
    face = axis * 2 + sign
    m = a[np.arange(len(n)), axis][:, None] + 1e-12
    uv = n / m
    u = np.where(axis == 0, uv[:, 1], uv[:, 0])
    v = np.where(axis == 2, uv[:, 1], uv[:, 2])
    iu = np.clip(((u + 1) * 0.5 * res).astype(np.int64), 0, res - 1)
    iv = np.clip(((v + 1) * 0.5 * res).astype(np.int64), 0, res - 1)
    return (face * res + iu) * res + iv


def _smooth_normals(me, n, area, rounds):
    """Face normals averaged over their neighbourhood `rounds` times (removes generator noise, keeps the overall
    facing of flat sides and the bend of round ones)."""
    start, total, lv, _le = U.polys(me)
    lf = U.loop_face(start, total)
    nv = len(me.vertices)
    sn = n
    for _ in range(rounds):
        w = (sn * area[:, None])[lf]
        vn = np.stack([np.bincount(lv, weights=w[:, i], minlength=nv) for i in range(3)], axis=1)
        vn /= np.maximum(np.linalg.norm(vn, axis=1), 1e-30)[:, None]
        fn = np.stack([np.bincount(lf, weights=vn[lv, i], minlength=len(n)) for i in range(3)], axis=1)
        sn = fn / np.maximum(np.linalg.norm(fn, axis=1), 1e-30)[:, None]
    return sn


def features(obj, sharp_angle=40.0):
    """Shape numbers: flat (surface share facing 8 directions), spread (share of all normal directions that 80% of
    the surface faces), sharp (sharp-edge length per size), sharp_length (meters)."""
    me = obj.data
    if len(me.polygons) == 0:
        return {"flat": 0.0, "spread": 1.0, "sharp": 0.0, "sharp_length": 0.0}
    n = U.face_normals(me)
    area = U.face_areas(me)
    total = area.sum() or 1.0
    dense = len(me.polygons) > 20000
    if dense:  # generator noise would spread the normals: look at them a little blurred
        n = _smooth_normals(me, n, area, 3)
    bins = _cube_bins(n)
    hist = np.bincount(bins, weights=area, minlength=6 * 12 * 12)
    srt = np.sort(hist)[::-1]
    flat = float(srt[:8].sum() / total)
    # how many normal directions hold 80% of the surface (flat / cylindrical shapes need few, round ones many)
    k80 = int(np.searchsorted(np.cumsum(srt), 0.8 * total) + 1)
    spread = k80 / len(hist)
    start, tot, _lv, le = U.polys(me)
    ids, fa, fb, _c = U.edge_faces(me, start, tot, le)
    ang = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", n[fa], n[fb]), -1, 1)))
    co = U.verts(me)
    e = U.edges(me)[ids]
    length = np.linalg.norm(co[e[:, 0]] - co[e[:, 1]], axis=1) if len(e) else np.zeros(0)
    # smoothed normals turn one sharp edge into a few bent rows: count bends over half the angle, then halve
    sharp_len = float(length[ang > (sharp_angle / 3 if dense else sharp_angle)].sum()) / (3.0 if dense else 1.0)
    return {"flat": round(flat, 3), "spread": round(spread, 3), "sharp": round(float(sharp_len / np.sqrt(total)), 3),
            "sharp_length": round(sharp_len, 4)}


def classify(obj):
    """{'kind': 'hard_surface' | 'organic', 'why': short reason, 'features': {...}}"""
    f = features(obj)
    # flat or straight-curved sides (boxes, cylinders, guns) point their surface in few directions; rounded shapes
    # (characters, rocks) spread it over many. Measured area-weighted, so it works for dense and low-poly meshes.
    # (a stylized gun with soft bevels everywhere still keeps a good share of truly flat sides)
    kind = "hard_surface" if f["spread"] < 0.15 or (f["spread"] < 0.3 and f["flat"] > 0.15) else "organic"
    pct = max(1, round(f["spread"] * 100))
    if kind == "hard_surface":
        why = (f"hard-surface: flat or straight-curved sides (80% of the surface faces {pct}% of directions), "
               f"{U.fmt_len(f['sharp_length'])} of sharp edges")
    else:
        why = f"organic: rounded every way (80% of the surface faces {pct}% of directions)"
    return {"kind": kind, "why": why, "features": f}


def symmetry(obj, tol=0.004):
    """Mirror axes (in the object's own space, through its origin) the shape is symmetric on: e.g. ['x']."""
    from .stats import sample_points
    me = obj.data
    if len(me.polygons) == 0:
        return []
    mw = np.array(obj.matrix_world)
    inv = np.linalg.inv(mw)
    pts_w = sample_points(obj, 1500, 7)
    pts = pts_w @ inv[:3, :3].T + inv[:3, 3]  # back to object space
    co = U.verts(me)
    size = U.diag(co) or 1.0
    from mathutils.bvhtree import BVHTree
    t, _ = U.tris(me)
    tree = BVHTree.FromPolygons([Vector(v) for v in co], t.tolist(), all_triangles=True)
    axes = []
    for i, name in enumerate("xyz"):
        m = pts.copy()
        m[:, i] = -m[:, i]
        d = []
        for p in m:
            hit = tree.find_nearest(Vector(p))
            d.append(hit[3] if hit[0] is not None else size)
        if float(np.mean(d)) / size < tol:
            axes.append(name)
    return axes
