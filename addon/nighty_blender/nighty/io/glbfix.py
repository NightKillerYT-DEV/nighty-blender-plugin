# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional fixes for an imported model (numpy; used by import_file.py inside a background Blender, only when asked).

- level_rotation(normals, areas): a model that comes in tilted or turned a little (scanned, or exported from a
  camera's frame) is stood upright and squared up: the rotation (up to 45 degrees each way) that lines the model's
  flat sides up with the axes, when it has clear flat sides. The smallest such turn keeps the front (-Y). Models
  already square are left alone.
- clean_metal(base, metal): a guessed metal map (wood painted as metal) is made exact. Pixels are grouped by color; a
  color group is metal (1) only when the map says so and its color can be metal (looks.metal_ok), otherwise 0. So
  metallic is exactly 0 / 1 and wood never comes out metal.
"""

import math

import numpy as np

try:
    from . import looks
except ImportError:         # run as a plain module next to import_file.py
    import looks


def _rot(rx, ry, rz):
    """Rotation matrices (n, 3, 3) for Euler angles in radians (arrays), R = Rz @ Ry @ Rx."""
    cx, sx, cy, sy, cz, sz = np.cos(rx), np.sin(rx), np.cos(ry), np.sin(ry), np.cos(rz), np.sin(rz)
    R = np.empty((len(rx), 3, 3))
    R[:, 0, 0] = cz * cy
    R[:, 0, 1] = cz * sy * sx - sz * cx
    R[:, 0, 2] = cz * sy * cx + sz * sx
    R[:, 1, 0] = sz * cy
    R[:, 1, 1] = sz * sy * sx + cz * cx
    R[:, 1, 2] = sz * sy * cx - cz * sx
    R[:, 2, 0] = -sy
    R[:, 2, 1] = cy * sx
    R[:, 2, 2] = cy * cx
    return R


def _scores(n, R):
    """How well normals n (m, 3) line up with the axes after each rotation in R (k, 3, 3): mean of x^8 + y^8 + z^8."""
    out = np.empty(len(R))
    for i in range(0, len(R), 64):
        x = np.einsum("kij,mj->kmi", R[i:i + 64], n)
        out[i:i + 64] = (x ** 8).sum(axis=2).mean(axis=1)
    return out


def _boxiness(n, R, deg=10.0):
    """Share of the surface whose normal is within `deg` of an axis after rotation R."""
    x = np.abs(n @ R.T)
    return float((x.max(axis=1) > math.cos(math.radians(deg))).mean())


def level_rotation(normals, areas, max_deg=45.0, min_deg=2.5, sample=20000, seed=0):
    """(R 3x3 list or None, info). normals (n, 3) unit face normals, areas (n,)."""
    normals = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
    areas = np.asarray(areas, dtype=np.float64).ravel()
    ok = np.isfinite(normals).all(axis=1) & (areas > 0)
    normals, areas = normals[ok], areas[ok]
    if len(normals) < 12:
        return None, {"rotated_deg": 0.0, "why": "too few faces"}
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(normals), size=min(sample, len(normals)), p=areas / areas.sum())
    n = normals[idx]
    best = np.zeros(3)
    for span, step in ((max_deg, 9.0), (9.0, 3.0), (3.0, 1.0), (1.0, 0.25)):
        g = np.radians(np.arange(-span, span + 1e-9, step))
        gx, gy, gz = np.meshgrid(g, g, g, indexing="ij")
        cand = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1) + best
        lim = math.radians(max_deg)
        cand = cand[(np.abs(cand) <= lim + 1e-9).all(axis=1)]
        s = _scores(n, _rot(cand[:, 0], cand[:, 1], cand[:, 2]))
        best = cand[int(np.argmax(s))]
    R = _rot(best[:1], best[1:2], best[2:3])[0]
    angle = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2))))
    box0, box1 = _boxiness(n, np.eye(3)), _boxiness(n, R)
    up = R.T @ np.array([0.0, 0.0, 1.0])            # the model's old direction that becomes up
    info = {"rotated_deg": round(angle, 1), "flat_share_before": round(box0, 3), "flat_share_after": round(box1, 3),
            "tilt_deg": round(math.degrees(math.acos(max(-1.0, min(1.0, up[2])))), 1)}
    if angle < min_deg:
        info.update(rotated_deg=0.0, why="already square")
        return None, info
    if box1 < 0.2 or box1 - box0 < 0.05:
        info.update(rotated_deg=0.0, why="no clear flat sides to square up (left as it came)")
        return None, info
    info["why"] = "stood upright and squared to the axes (its flat sides)"
    return R.tolist(), info


def _kmeans(x, k, iters=12, seed=0):
    rng = np.random.default_rng(seed)
    centers = [x[rng.integers(len(x))]]
    for _ in range(1, k):                           # k-means++ start
        d = np.min(((x[:, None, :] - np.array(centers)[None]) ** 2).sum(axis=2), axis=1)
        if d.sum() <= 0:
            break
        centers.append(x[rng.choice(len(x), p=d / d.sum())])
    c = np.array(centers)
    for _ in range(iters):
        lab = np.argmin(((x[:, None, :] - c[None]) ** 2).sum(axis=2), axis=1)
        for j in range(len(c)):
            m = lab == j
            if m.any():
                c[j] = x[m].mean(axis=0)
    return c


def _labels(px, centers, chunk=1 << 20):
    out = np.empty(len(px), dtype=np.int32)
    for i in range(0, len(px), chunk):
        p = px[i:i + chunk]
        out[i:i + chunk] = np.argmin(((p[:, None, :] - centers[None]) ** 2).sum(axis=2), axis=1)
    return out


def clean_metal(base, metal, k=8, sample=60000, seed=0):
    """base (h, w, 3) sRGB 0..1, metal (h, w) 0..1 (same size) -> (metal 0 / 1 (h, w) float32, info)."""
    base = np.asarray(base, dtype=np.float32)
    metal = np.asarray(metal, dtype=np.float32)
    px = base.reshape(-1, 3)
    mv = metal.ravel()
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(px), size=min(sample, len(px)), replace=False)
    centers = _kmeans(px[pick].astype(np.float64), k, seed=seed)
    lab = _labels(px, centers.astype(np.float32))
    out = np.zeros(len(px), dtype=np.float32)
    rows = []
    for j, c in enumerate(centers):
        m = lab == j
        share = float(m.mean())
        if share == 0:
            continue
        ai = float((mv[m] > 0.5).mean())
        is_metal = looks.metal_ok(tuple(c), ai)
        if is_metal:
            out[m] = 1.0
        rows.append({"color": looks.rgb_hex(tuple(c)), "share": round(share, 3), "ai_metal": round(ai, 2),
                     "metal": is_metal})
    before = mv > 0.5
    info = {"groups": sorted(rows, key=lambda r: -r["share"]),
            "metal_before": round(float(before.mean()), 3), "metal_after": round(float(out.mean()), 3),
            "changed": round(float((before != (out > 0.5)).mean()), 3)}
    return out.reshape(metal.shape), info
