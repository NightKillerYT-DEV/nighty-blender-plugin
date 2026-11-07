# SPDX-License-Identifier: GPL-3.0-or-later
"""A small PNG writer (numpy + zlib, no bpy), so every map is saved exactly as computed: true grayscale for data maps,
8 or 16 bits, no color management in the way."""

import struct
import zlib

import numpy as np

_TYPES = {1: 0, 2: 4, 3: 2, 4: 6}  # channels -> PNG color type (gray, gray+alpha, RGB, RGBA)


def _chunk(tag, data):
    c = struct.pack(">I", len(data)) + tag + data
    return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def encode(arr, level=6):
    """arr: H x W (gray) or H x W x C (C = 1..4), dtype uint8 or uint16, first row = top of the picture."""
    a = np.asarray(arr)
    if a.ndim == 2:
        a = a[:, :, None]
    h, w, c = a.shape
    if c not in _TYPES:
        raise ValueError("1 to 4 channels")
    if a.dtype == np.uint16:
        depth = 16
        rows = a.astype(">u2").view(np.uint8).reshape(h, w * c * 2)
    else:
        depth = 8
        rows = a.astype(np.uint8).reshape(h, w * c)
    # filter 2 ("Up") for every row: smooth maps compress much better than unfiltered
    up = rows.copy()
    up[1:] = (rows[1:].astype(np.int16) - rows[:-1].astype(np.int16)).astype(np.uint8)
    raw = np.concatenate([np.full((h, 1), 2, np.uint8), up], axis=1).tobytes()
    ihdr = struct.pack(">IIBBBBB", w, h, depth, _TYPES[c], 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw, level)) + \
        _chunk(b"IEND", b"")


def write(path, arr, level=6):
    data = encode(arr, level)
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


def to_uint(x, bits=8):
    """Floats 0..1 -> uint8 / uint16 with rounding."""
    top = 255 if bits == 8 else 65535
    return (np.clip(x, 0.0, 1.0) * top + 0.5).astype(np.uint8 if bits == 8 else np.uint16)


def read_header(path):
    """(width, height, bit depth, channels) of a PNG file."""
    with open(path, "rb") as f:
        head = f.read(33)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    w, h, depth, ctype = struct.unpack(">IIBB", head[16:26])
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    return w, h, depth, channels


def decode(data):
    """Decodes PNGs this module writes (and any 8/16-bit non-interlaced, non-palette PNG; slow for filters 1/3/4)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat = 8, []
    w = h = depth = ctype = None
    while pos < len(data):
        (n,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            w, h, depth, ctype, _, _, inter = struct.unpack(">IIBBBBB", body)
            if inter or ctype == 3:
                raise ValueError("interlaced / palette PNGs are not supported here")
        elif tag == b"IDAT":
            idat.append(body)
        pos += 12 + n
    c = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    bpp = c * (depth // 8)
    stride = w * bpp
    raw = np.frombuffer(zlib.decompress(b"".join(idat)), np.uint8).reshape(h, stride + 1)
    out = np.zeros((h, stride), np.uint8)
    prev = np.zeros(stride, np.int32)
    for y in range(h):
        ft = raw[y, 0]
        line = raw[y, 1:].astype(np.int32)
        if ft == 0:
            cur = line
        elif ft == 2:
            cur = (line + prev) & 255
        elif ft == 1:
            cur = line.copy()
            for i in range(bpp, stride):
                cur[i] = (cur[i] + cur[i - bpp]) & 255
        elif ft == 3:
            cur = line.copy()
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((left + prev[i]) >> 1)) & 255
        else:
            cur = line.copy()
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                b = prev[i]
                cc = prev[i - bpp] if i >= bpp else 0
                p = a + b - cc
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - cc)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else cc)
                cur[i] = (cur[i] + pr) & 255
        out[y] = cur
        prev = cur
    if depth == 16:
        return out.view(">u2").reshape(h, w, c).astype(np.uint16)
    return out.reshape(h, w, c)


def read(path):
    with open(path, "rb") as f:
        return decode(f.read())
