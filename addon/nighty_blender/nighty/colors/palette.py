# SPDX-License-Identifier: GPL-3.0-or-later
"""Colors in a perceptual space and the palette of an AI texture (pure numpy, no bpy).

Oklab (Bjorn Ottosson's, public domain): distances there match how different two colors look; 0.02 is about the
smallest difference people notice, 0.1 is clearly another color. The palette is k-means on the surface's colors
(each face weighted by its area), near colors merged, rare ones dropped.
"""

import numpy as np


def srgb_to_linear(c):
    c = np.clip(np.asarray(c, dtype=np.float64), 0.0, 1.0)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.clip(np.asarray(c, dtype=np.float64), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005]])
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]])
_M1I = np.linalg.inv(_M1)
_M2I = np.linalg.inv(_M2)


def srgb_to_oklab(rgb):
    """(..., 3) sRGB 0..1 -> (..., 3) Oklab (L 0..1, a, b about -0.4..0.4)."""
    lin = srgb_to_linear(rgb)
    lms = np.cbrt(lin @ _M1.T)
    return lms @ _M2.T


def oklab_to_srgb(lab):
    lms = np.asarray(lab, dtype=np.float64) @ _M2I.T
    return linear_to_srgb(np.clip((lms ** 3) @ _M1I.T, 0.0, 1.0))


def hex_of(rgb):
    return "#" + "".join(f"{int(round(max(0.0, min(1.0, float(c))) * 255)):02x}" for c in list(rgb)[:3])


def _sqdist(x, c):
    """(n, k) squared distances between rows of x (n, 3) and c (k, 3)."""
    d = (x * x).sum(axis=1)[:, None] - 2.0 * (x @ c.T) + (c * c).sum(axis=1)[None, :]
    return np.maximum(d, 0.0)


def nearest(x, centers, chunk=1 << 18):
    """(label, squared distance) of the nearest center for every row of x."""
    n = len(x)
    lab = np.empty(n, dtype=np.int32)
    d = np.empty(n, dtype=np.float64)
    for i in range(0, n, chunk):
        dd = _sqdist(x[i:i + chunk], centers)
        lab[i:i + chunk] = np.argmin(dd, axis=1)
        d[i:i + chunk] = dd[np.arange(len(dd)), lab[i:i + chunk]]
    return lab, d


def kmeans(x, w, k, iters=15, seed=0):
    """Weighted k-means++ (x (n, 3), weights (n,)) -> centers (k', 3), k' <= k."""
    rng = np.random.default_rng(seed)
    w = np.asarray(w, dtype=np.float64)
    p = w / w.sum()
    centers = [x[rng.choice(len(x), p=p)]]
    d = _sqdist(x, np.array(centers))[:, 0]
    for _ in range(1, k):
        q = d * w
        if q.sum() <= 1e-12:
            break
        centers.append(x[rng.choice(len(x), p=q / q.sum())])
        d = np.minimum(d, ((x - centers[-1]) ** 2).sum(axis=1))
    c = np.array(centers)
    for _ in range(iters):
        lab, _d = nearest(x, c)
        ws = np.bincount(lab, weights=w, minlength=len(c))
        new = np.stack([np.bincount(lab, weights=w * x[:, j], minlength=len(c)) for j in range(3)], axis=1)
        keep = ws > 0
        new[keep] /= ws[keep, None]
        new[~keep] = c[~keep]
        if np.abs(new - c).max() < 1e-5:
            c = new
            break
        c = new
    lab, _d = nearest(x, c)
    used = np.bincount(lab, minlength=len(c)) > 0
    return c[used]


def merge_close(centers, shares, merge):
    """Merges the closest pair of centers while they are nearer than `merge` (Oklab). Returns (centers, shares)."""
    c = [np.asarray(v, dtype=np.float64) for v in centers]
    s = [float(v) for v in shares]
    while len(c) > 1:
        arr = np.array(c)
        d = np.sqrt(_sqdist(arr, arr))
        np.fill_diagonal(d, np.inf)
        i, j = np.unravel_index(np.argmin(d), d.shape)
        if d[i, j] >= merge:
            break
        tot = s[i] + s[j]
        c[i] = (c[i] * s[i] + c[j] * s[j]) / max(tot, 1e-12)
        s[i] = tot
        del c[j], s[j]
    return np.array(c), np.array(s)


def fit(lab_colors, weights, k=12, merge=0.05, min_share=0.002, sample=60000, seed=0):
    """The palette of a surface: (centers (k', 3) Oklab, shares (k',)). lab_colors: per-face Oklab, weights: areas.
    k-means on an area-weighted sample, near colors merged, colors under min_share of the area folded into the
    nearest other, then refined on every face."""
    x = np.asarray(lab_colors, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    rng = np.random.default_rng(seed)
    if len(x) > sample:
        idx = rng.choice(len(x), size=sample, replace=False, p=w / w.sum())
        xs, ws = x[idx], np.ones(len(idx))
    else:
        xs, ws = x, w
    c = kmeans(xs, ws, k, seed=seed)
    if len(x) > 3 * sample:      # the refining below on a bigger sample (every face of a 500k mesh costs seconds)
        idx = rng.choice(len(x), size=3 * sample, replace=False)
        x, w = x[idx], w[idx]
    for _ in range(3):
        lab, _d = nearest(x, c)
        sh = np.bincount(lab, weights=w, minlength=len(c)) / w.sum()
        c, sh = merge_close(c, sh, merge)
        keep = sh >= min_share
        if keep.all() or keep.sum() == 0:
            break
        c = c[keep]
    # refine on every face (a few weighted Lloyd steps), merging again if two drifted together
    for _ in range(4):
        lab, _d = nearest(x, c)
        ws_ = np.bincount(lab, weights=w, minlength=len(c))
        new = np.stack([np.bincount(lab, weights=w * x[:, j], minlength=len(c)) for j in range(3)], axis=1)
        ok = ws_ > 0
        new[ok] /= ws_[ok, None]
        new[~ok] = c[~ok]
        c = new[ok]
    lab, _d = nearest(x, c)
    sh = np.bincount(lab, weights=w, minlength=len(c)) / w.sum()
    c, sh = merge_close(c, sh, merge)
    order = np.argsort(-sh)
    return c[order], sh[order]


def flatness(lab_colors, weights, centers, tol=0.045):
    """How flat-colored the surface is: the share of its area whose color lies within `tol` (Oklab) of a palette
    color, and the area-weighted median distance. Painted / plastic models (a few flat colors) score high; wood
    grain, photo textures score low."""
    _lab, d = nearest(np.asarray(lab_colors, dtype=np.float64), centers)
    d = np.sqrt(d)
    w = np.asarray(weights, dtype=np.float64)
    share = float(w[d < tol].sum() / max(w.sum(), 1e-12))
    order = np.argsort(d)
    cw = np.cumsum(w[order])
    med = float(d[order][np.searchsorted(cw, cw[-1] / 2)]) if len(d) else 0.0
    return share, med


def transitions(centers, shares, max_share=0.02, tol=0.03, t_range=(0.2, 0.8)):
    """Palette colors that are only the blend where two other colors meet (an AI texture's soft or haloed borders:
    orange next to black gives a brown band, grey next to black a mid grey). A minor color (under max_share of
    the area) that a mix of two bigger colors matches within tol (Oklab), somewhere in the middle of the blend
    (t_range: a real dark grey sits close to black, not halfway), is a transition: drop it and its faces go to the
    nearest real color, so the border lands in the middle of the blend. Returns a bool per color."""
    c = np.asarray(centers, dtype=np.float64)
    sh = np.asarray(shares, dtype=np.float64)
    srgb = oklab_to_srgb(c)
    lin = srgb_to_linear(srgb)
    out = np.zeros(len(c), dtype=bool)
    ts = np.linspace(t_range[0], t_range[1], 25)[:, None]
    for i in np.argsort(sh):
        if sh[i] >= max_share:
            continue
        for a in range(len(c)):
            for b in range(a + 1, len(c)):
                if i in (a, b) or out[a] or out[b] or sh[a] <= sh[i] or sh[b] <= sh[i]:
                    continue
                for space, conv in ((srgb, srgb_to_oklab), (lin, lambda x: srgb_to_oklab(linear_to_srgb(x)))):
                    mix = space[a] * (1 - ts) + space[b] * ts
                    d = np.sqrt(((conv(mix) - c[i]) ** 2).sum(axis=1)).min()
                    if d < tol:
                        out[i] = True
                        break
                if out[i]:
                    break
            if out[i]:
                break
    return out


def picture_palette(px, sample=60000, seed=0):
    """The colors of the object in its source picture (h, w, 3|4 sRGB 0..1; the generation's input picture):
    alpha when the picture has a cut-out, else everything that is not the background (the corners' color).
    Returns (centers (k, 3) Oklab, shares (k,)), or None when too little of the object shows."""
    px = np.asarray(px, dtype=np.float64)
    rgb = px[..., :3].reshape(-1, 3)
    if px.shape[-1] == 4 and (px[..., 3] < 0.5).mean() > 0.05:
        fg = px[..., 3].ravel() > 0.5
    else:
        h, w = px.shape[:2]
        k = max(2, min(h, w) // 50)
        corners = np.concatenate([px[:k, :k, :3].reshape(-1, 3), px[:k, -k:, :3].reshape(-1, 3),
                                  px[-k:, :k, :3].reshape(-1, 3), px[-k:, -k:, :3].reshape(-1, 3)])
        bg = srgb_to_oklab(np.median(corners, axis=0))
        lab_all = srgb_to_oklab(rgb)
        fg = np.sqrt(((lab_all - bg) ** 2).sum(axis=1)) > 0.03
    if fg.sum() < 500:
        return None
    lab = srgb_to_oklab(rgb[fg])
    c, sh = fit(lab, np.ones(len(lab)), k=10, merge=0.05, min_share=0.003, sample=sample, seed=seed)
    return c, sh


def toward_picture(c, pic, tol=0.13):
    """The region color c (Oklab) with its hue and saturation taken from the closest color of the picture's palette
    (pic: centers, shares), its lightness kept: fixes an AI texture's color drift (white gone lavender, orange gone
    salmon) without changing how light or dark the part is. None when no picture color is close enough."""
    if pic is None:
        return None
    centers, shares = pic
    d = np.sqrt((0.5 * (centers[:, 0] - c[0])) ** 2 + (centers[:, 1] - c[1]) ** 2 + (centers[:, 2] - c[2]) ** 2)
    d = np.where(shares >= 0.003, d, np.inf)
    i = int(np.argmin(d))
    if not np.isfinite(d[i]) or d[i] > tol:
        return None
    p = centers[i]
    if c[0] < 0.35 or np.hypot(p[1] - c[1], p[2] - c[2]) < 0.03:
        return None                     # near-black (a tint barely shows, the picture's shadows tint it) or no drift
    return np.array([c[0], p[1], p[2]])
