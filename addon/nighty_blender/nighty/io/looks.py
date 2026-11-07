# SPDX-License-Identifier: GPL-3.0-or-later
"""What a model's own colors say about its surfaces (plain Python, no bpy / numpy).

- metal_ok(rgb, ai_metal): a model's metal map can be a guess; a color region is metal only when the map says so AND the
  color can be a metal (wood never comes out metal; strong paint colors are paint, not metal).
- pick_material(rgb, metal, candidates): the library material that fits a part's own color: wood for brown
  non-metal, brass / gold / copper / steel / gunmetal for metals by hue and lightness, polymer / plastic (painted
  in the part's own color) for the rest. With the person's own list, the closest one from that list.

Colors are sRGB 0..1 as stored in the texture (what the picture shows).
"""

import colorsys

# reference colors (sRGB) and metal flags of the library materials this picks from
REFERENCE = {
    "wood": ("#7a4f2a", 0), "painted_wood": ("#3f6f8f", 0), "leather": ("#5c3421", 0), "fabric": ("#4b5662", 0),
    "polymer": ("#2a2b2d", 0), "plastic": ("#c63a30", 0), "rubber": ("#1f1f20", 0), "carbon_fiber": ("#1b1c1e", 0),
    "stone": ("#8b877f", 0), "concrete": ("#9b9991", 0), "ceramic": ("#e6e2da", 0), "glass": ("#e9f1f1", 0),
    "painted_metal": ("#4d5a35", 0), "emissive": ("#36c8ff", 0), "skin": ("#c79076", 0),
    "steel": ("#b9bbbe", 1), "gunmetal": ("#55585d", 1), "brushed_metal": ("#bfc1c4", 1), "aluminum": ("#d5d7d9", 1),
    "anodized_aluminum": ("#4a5f86", 1), "brass": ("#b8964f", 1), "copper": ("#dc9a78", 1), "gold": ("#f0cb6c", 1),
    "chrome": ("#e3e5e7", 1), "iron": ("#717376", 1), "rusty_metal": ("#8e9093", 1),
}
PAINTABLE = {"plastic", "painted_metal", "painted_wood", "fabric", "anodized_aluminum", "emissive"}


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def rgb_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb[:3])


def hsv(rgb):
    """(hue in degrees, saturation, value)."""
    h, s, v = colorsys.rgb_to_hsv(*[max(0.0, min(1.0, c)) for c in rgb[:3]])
    return h * 360.0, s, v


def wood_like(rgb):
    """Brown: orange-ish hue, clearly colored, not bright (wood, leather, dark varnish)."""
    h, s, v = hsv(rgb)
    return 5.0 <= h <= 38.0 and s >= 0.35 and v <= 0.65


def gold_like(rgb):
    h, s, v = hsv(rgb)
    return 38.0 < h <= 65.0 and s >= 0.25 and v >= 0.3


def metal_ok(rgb, ai_metal):
    """Metal or not for one color region: ai_metal is the AI's metal share there (0..1)."""
    if ai_metal < 0.5 or wood_like(rgb):
        return False
    h, s, v = hsv(rgb)
    if s > 0.45 and not (15.0 <= h <= 65.0):
        return False                      # a strong blue / green / red / purple: paint or plastic
    return True


def guess(rgb, metal):
    """The library material for a part of this color: (name, paint color or None)."""
    h, s, v = hsv(rgb)
    if metal:
        if gold_like(rgb):
            return min(("brass", "gold"), key=lambda k: _distance(rgb, hex_rgb(REFERENCE[k][0]))), None
        if 10.0 <= h <= 38.0 and s >= 0.3:
            return "copper", None
        if s > 0.25:
            return "anodized_aluminum", rgb_hex(rgb)
        return ("steel" if v > 0.55 else "gunmetal"), None
    if wood_like(rgb):
        return "wood", None
    if v < 0.2 and s < 0.35:
        return "polymer", None            # near black: hard dark plastic (grips, rails)
    return "plastic", rgb_hex(rgb)        # anything else keeps its own color


def _distance(a, b):
    """A rough perceptual distance between two sRGB colors (weighted RGB, 0..~1.7)."""
    r = (a[0] + b[0]) / 2
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return ((2 + r) * dr * dr + 4 * dg * dg + (3 - r) * db * db) ** 0.5 / 3 ** 0.5


def pick_material(rgb, metal, candidates=None, metal_flags=None):
    """The material for one part: (name, paint color or None, why).
    candidates: the person's list (names); metal_flags: {name: 0/1} for names not in REFERENCE."""
    if not candidates:
        name, paint = guess(rgb, metal)
        return name, paint, "from its own color"
    best = None
    for name in dict.fromkeys(candidates):
        ref, is_metal = REFERENCE.get(name, (None, (metal_flags or {}).get(name, 0)))
        score = 0.0 if bool(is_metal) == bool(metal) else 2.0       # metal must match first
        if ref is not None and name not in PAINTABLE:
            score += _distance(rgb, hex_rgb(ref))
        elif ref is None:
            score += 0.6                                            # unknown look: neutral
        if wood_like(rgb) and name in ("wood", "painted_wood", "leather"):
            score -= 0.3
        if best is None or score < best[0]:
            best = (score, name)
    name = best[1]
    return name, (rgb_hex(rgb) if name in PAINTABLE else None), "closest of the given materials to its own color"
