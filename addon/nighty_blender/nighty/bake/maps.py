# SPDX-License-Identifier: GPL-3.0-or-later
"""Map definitions and the numpy image work after a bake (no bpy): margins, filling, sRGB, binary metallic,
normal-map format, channel packing, resizing. Arrays are H x W x C float32, row 0 = top of the picture."""

import numpy as np

# key: (file suffix, channels written, color space, what it is)
MAPS = {
    "base_color": ("BaseColor", 3, "sRGB", "albedo, no lighting"),
    "roughness": ("Roughness", 1, "Non-Color", "0 smooth .. 1 rough"),
    "metallic": ("Metallic", 1, "Non-Color", "exactly 0 or 1"),
    "normal": ("Normal", 3, "Non-Color", "tangent space"),
    "ao": ("AO", 1, "Non-Color", "ambient occlusion"),
    "emission": ("Emission", 3, "sRGB", "emitted color"),
    "opacity": ("Opacity", 1, "Non-Color", "1 opaque .. 0 clear"),
}
ORDER = ["base_color", "roughness", "metallic", "normal", "ao", "emission", "opacity"]
SIZES = (64, 128, 256, 512, 1024, 2048, 4096)  # the tools offer 1K / 2K / 4K
EMIT_MAPS = ("base_color", "roughness", "metallic", "emission", "opacity")


def size_of(value):
    """'1K' / '2k' / 2048 -> pixels (512..4096)."""
    if isinstance(value, str):
        v = value.strip().lower()
        table = {"512": 512, "0.5k": 512, "1k": 1024, "2k": 2048, "4k": 4096}
        if v in table:
            return table[v]
        value = int(v)
    value = int(value)
    if value not in SIZES:
        raise ValueError(f"texture size must be 1K, 2K or 4K; got {value}")
    return value


def linear_to_srgb(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1.0 / 2.4) - 0.055).astype(np.float32)


def srgb_to_linear(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92, np.power((x + 0.055) / 1.055, 2.4)).astype(np.float32)


def luminance(rgb):
    return (rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722).astype(np.float32)


def snap_binary(x, threshold=0.5):
    """Metallic: every pixel becomes exactly 0 or 1."""
    return (x >= threshold).astype(np.float32)


def flip_green(normal):
    """OpenGL (+Y up) <-> DirectX (-Y): the same operation both ways."""
    n = normal.copy()
    n[..., 1] = 1.0 - n[..., 1]
    return n


def _shift(a, dy, dx):
    out = np.zeros_like(a)
    h, w = a.shape[:2]
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    out[yd, xd] = a[ys, xs]
    return out


def dilate(img, filled, steps):
    """Grows the baked area outward by `steps` pixels (each new pixel = mean of its filled neighbors): the margin
    that keeps mipmaps and filtering from pulling in the empty color."""
    img = img.copy()
    filled = filled.copy()
    for _ in range(int(steps)):
        acc = np.zeros_like(img)
        cnt = np.zeros(filled.shape, np.float32)
        f = filled.astype(np.float32)
        masked = img * f[..., None]
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            acc += _shift(masked, dy, dx)
            cnt += _shift(f, dy, dx)
        new = (~filled) & (cnt > 0)
        if not new.any():
            break
        img[new] = acc[new] / cnt[new][:, None]
        filled |= new
    return img, filled


def fill_rest(img, filled):
    """Fills every pixel not baked or dilated with a smooth extension (push-pull over a pyramid)."""
    if filled.all():
        return img
    h, w, c = img.shape
    levels = [(img * filled[..., None], filled.astype(np.float32))]
    while levels[-1][1].shape[0] > 1 and levels[-1][1].shape[1] > 1:
        col, wt = levels[-1]
        hh, ww = (col.shape[0] // 2) * 2, (col.shape[1] // 2) * 2
        col, wt = col[:hh, :ww], wt[:hh, :ww]
        col2 = col.reshape(hh // 2, 2, ww // 2, 2, c).sum(axis=(1, 3))
        wt2 = wt.reshape(hh // 2, 2, ww // 2, 2).sum(axis=(1, 3))
        levels.append((col2, wt2))
    # pull: from coarse to fine, empty pixels take the coarser average
    col, wt = levels[-1]
    cur = np.where(wt[..., None] > 0, col / np.maximum(wt, 1e-8)[..., None], 0.5)
    for col, wt in reversed(levels[:-1]):
        up = np.repeat(np.repeat(cur, 2, axis=0), 2, axis=1)
        up = np.pad(up, ((0, col.shape[0] - up.shape[0]), (0, col.shape[1] - up.shape[1]), (0, 0)), mode="edge")
        avg = col / np.maximum(wt, 1e-8)[..., None]
        cur = np.where(wt[..., None] > 0, avg, up)
    out = img.copy()
    out[~filled] = cur[~filled]
    return out


def blur_masked(img, mask, passes=2):
    """A light blur that stays inside the baked area (smooths AO sampling noise without bleeding across islands)."""
    img = img.copy()
    f = mask.astype(np.float32)
    for _ in range(passes):
        acc = img * f[..., None]
        cnt = f.copy()
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            acc += _shift(img * f[..., None], dy, dx)
            cnt += _shift(f, dy, dx)
        sm = acc / np.maximum(cnt, 1e-8)[..., None]
        img = np.where(mask[..., None], sm, img)
    return img


def resize(img, size):
    """Box-filter down to `size` (power-of-two steps) or nearest up."""
    h = img.shape[0]
    if size == h:
        return img
    if size < h:
        k = h // size
        c = img.shape[2]
        return img[:size * k, :size * k].reshape(size, k, size, k, c).mean(axis=(1, 3)).astype(np.float32)
    k = size // h
    return np.repeat(np.repeat(img, k, axis=0), k, axis=1)


def gray(a):
    return a[..., :1] if a.ndim == 3 else a[..., None]


def pack(r=None, g=None, b=None, a=None, shape=None, fill=(0.0, 0.0, 0.0, 1.0)):
    """Channel packing: single-channel arrays (H x W or H x W x 1) into RGB(A)."""
    srcs = [r, g, b, a]
    for s in srcs:
        if s is not None:
            shape = s.shape[:2]
            break
    chans = []
    for i, s in enumerate(srcs[:3] if a is None else srcs):
        if s is None:
            chans.append(np.full(shape, fill[i], np.float32))
        else:
            chans.append(np.asarray(s, np.float32).reshape(shape))
    return np.stack(chans, axis=-1)
