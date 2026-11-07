# SPDX-License-Identifier: GPL-3.0-or-later
"""Text to a sharp decal image: Blender's own font engine makes the glyph shapes (a temporary text object turned
into triangles), numpy draws them with 4 x 4 supersampling. No renderer, no AI: letters stay exact and readable."""

import bpy
import numpy as np

from ..bake import uvraster


def _glyph_triangles(text, font_path=None, bold=False):
    cu = bpy.data.curves.new("NB Text Tmp", "FONT")
    cu.body = text
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    cu.size = 1.0
    if font_path:
        cu.font = bpy.data.fonts.load(font_path, check_existing=True)
    if bold:
        cu.offset = 0.02   # a little thicker strokes
    ob = bpy.data.objects.new("NB Text Tmp", cu)
    bpy.context.scene.collection.objects.link(ob)
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), depsgraph=dg)
        me.calc_loop_triangles()
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)[:, :2]
        tv = np.empty(len(me.loop_triangles) * 3, np.int64)
        me.loop_triangles.foreach_get("vertices", tv)
        tris = co[tv.reshape(-1, 3)]
        bpy.data.meshes.remove(me)
    finally:
        bpy.data.objects.remove(ob)
        bpy.data.curves.remove(cu)
        bpy.context.view_layer.update()
    return tris


def _lin_to_srgb(v):
    v = max(0.0, min(1.0, float(v)))
    return v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def srgb_of(c):
    """'#rrggbb' / (r, g, b) -> sRGB floats 0..1 (what goes into the PNG)."""
    from .compat import color as to_linear
    return np.array([_lin_to_srgb(v) for v in to_linear(c)[:3]], np.float32)


def text_rgba(text, height_px=256, color="#ffffff", outline=0.0, outline_color="#000000", font_path=None,
              bold=False, pad=0.12, ss=4):
    """RGBA float image (row 0 = top, straight alpha, sRGB colors) of the text, `height_px` tall for the glyphs.
    outline: stroke width as a share of the text height (0.06 = a clear outline)."""
    tris = _glyph_triangles(text, font_path, bold)
    if len(tris) == 0:
        raise ValueError("the text has no visible letters")
    flat = tris.reshape(-1, 2)
    lo, hi = flat.min(axis=0), flat.max(axis=0)
    scale = height_px / max(float(hi[1] - lo[1]), 1e-6)
    o_px = int(round(outline * height_px))
    padding = int(round(pad * height_px)) + o_px
    w = int(np.ceil((hi[0] - lo[0]) * scale)) + 2 * padding
    h = int(np.ceil((hi[1] - lo[1]) * scale)) + 2 * padding
    m = max(w, h)
    x0, y0 = (m - w) // 2, (m - h) // 2
    uv = ((tris - lo) * scale + padding + np.array([x0, y0])) / float(m)   # square canvas, v up
    cov, _ = uvraster.rasterize(uv, m * ss)
    alpha = cov.reshape(m, ss, m, ss).mean(axis=(1, 3))[::-1]               # row 0 = top
    alpha = alpha[m - y0 - h:m - y0, x0:x0 + w].astype(np.float32)
    text_c = srgb_of(color)
    rgb = np.empty((h, w, 3), np.float32)
    rgb[:] = text_c
    if o_px > 0:
        ring = alpha.copy()
        for _ in range(o_px):
            ring = np.maximum.reduce([ring, np.roll(ring, 1, 0), np.roll(ring, -1, 0), np.roll(ring, 1, 1),
                                      np.roll(ring, -1, 1)])
        rgb[:] = srgb_of(outline_color)
        rgb = rgb * (1 - alpha[..., None]) + text_c * alpha[..., None]
        alpha = np.maximum(alpha, ring)
    return np.dstack([rgb, alpha]).astype(np.float32)
