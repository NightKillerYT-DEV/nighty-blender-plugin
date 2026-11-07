# SPDX-License-Identifier: GPL-3.0-or-later
# A small PNG reader / writer (plain Python + numpy, no Pillow in Blender's Python). Reads 8-bit gray / RGB / RGBA
# files (no interlace), writes 8-bit RGB / RGBA. Meant for small pictures (probes and thumbnails): rows with the
# Average / Paeth filters are undone in plain Python.

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}       # color type -> channels


class PNGError(ValueError):
    pass


def _chunks(data):
    if not data.startswith(SIGNATURE):
        raise PNGError("not a PNG file")
    at = len(SIGNATURE)
    while at + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        yield kind, data[at + 8:at + 8 + length]
        at += 12 + length
        if kind == b"IEND":
            return


def read(path_or_bytes):
    """(width, height, channels, numpy uint8 array of shape (h, w, channels))."""
    import numpy as np
    data = path_or_bytes
    if not isinstance(data, (bytes, bytearray)):
        with open(path_or_bytes, "rb") as f:
            data = f.read()
    header, idat = None, []
    for kind, body in _chunks(data):
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
    if header is None:
        raise PNGError("PNG without a header")
    w, h, depth, ctype, _comp, _filt, interlace = header
    if depth != 8 or ctype not in _CHANNELS or interlace:
        raise PNGError(f"unsupported PNG (bit depth {depth}, color type {ctype}, interlace {interlace})")
    ch = _CHANNELS[ctype]
    raw = zlib.decompress(b"".join(idat))
    stride = w * ch
    if len(raw) < h * (stride + 1):
        raise PNGError("PNG data is cut short")
    out = np.zeros((h, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.int32)
    for y in range(h):
        start = y * (stride + 1)
        ftype = raw[start]
        line = np.frombuffer(raw, dtype=np.uint8, count=stride, offset=start + 1).astype(np.int32)
        if ftype == 0:
            cur = line
        elif ftype == 1:                       # Sub: running sum per channel
            cur = np.cumsum(line.reshape(w, ch), axis=0).reshape(-1) & 255
        elif ftype == 2:                       # Up
            cur = (line + prev) & 255
        elif ftype in (3, 4):
            cur = _slow_row(ftype, line.tolist(), prev.tolist(), ch)
            cur = np.array(cur, dtype=np.int32)
        else:
            raise PNGError(f"unknown PNG filter {ftype}")
        out[y] = cur
        prev = cur.astype(np.int32)
    return w, h, ch, out.reshape(h, w, ch)


def _slow_row(ftype, line, prev, bpp):
    cur = [0] * len(line)
    for i, x in enumerate(line):
        a = cur[i - bpp] if i >= bpp else 0
        b = prev[i]
        if ftype == 3:
            cur[i] = (x + ((a + b) >> 1)) & 255
        else:
            c = prev[i - bpp] if i >= bpp else 0
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
            cur[i] = (x + pred) & 255
    return cur


def write(path, pixels):
    """pixels: numpy uint8 (h, w, 3 or 4). No filters (fine for small pictures)."""
    import numpy as np
    px = np.ascontiguousarray(pixels, dtype=np.uint8)
    h, w, ch = px.shape
    ctype = {1: 0, 3: 2, 4: 6}[ch]
    rows = np.zeros((h, w * ch + 1), dtype=np.uint8)
    rows[:, 1:] = px.reshape(h, -1)

    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))
    blob = (SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows.tobytes(), 6)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(blob)
    return path
