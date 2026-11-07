# SPDX-License-Identifier: GPL-3.0-or-later
"""The smart material library: plain data, no bpy.

Colors are sRGB hex (what a person would pick). Metallic is exactly 0 or 1 for every layer (a material is a metal or
it is not; values in between are not physical and engines read them badly). Every material has a clean layer, a worn
layer (what edge wear uncovers) and a dirt layer (what collects in cavities). Patterns are procedural and work in
3D object space, so they need no UVs and have no seams; sizes are real-world meters.
"""

# pattern: none | scratches | brushed | cast | paint | stipple | plastic | rubber | wood | leather | weave | stone |
#          concrete | carbon | skin
MATERIALS = {
    # metals
    "steel": dict(label="Steel", metallic=1, color="#b9bbbe", rough=0.32, rough_var=0.10, pattern="scratches",
                  bump=0.25, worn=dict(color="#d9dbdd", metallic=1, rough=0.18),
                  dirt=dict(color="#4a4038", rough=0.75)),
    "gunmetal": dict(label="Gunmetal", metallic=1, color="#55585d", rough=0.40, rough_var=0.10, pattern="cast",
                     bump=0.3, worn=dict(color="#c3c6c9", metallic=1, rough=0.22),
                     dirt=dict(color="#3a3430", rough=0.8)),
    "brushed_metal": dict(label="Brushed metal", metallic=1, color="#bfc1c4", rough=0.30, rough_var=0.12,
                          pattern="brushed", bump=0.2, anisotropic=0.6,
                          worn=dict(color="#dcdee0", metallic=1, rough=0.18), dirt=dict(color="#4a4540", rough=0.7)),
    "painted_metal": dict(label="Painted metal", metallic=0, color="#4d5a35", rough=0.55, rough_var=0.08,
                          pattern="paint", bump=0.2, paintable=True, chip_depth=1.0,
                          worn=dict(color="#b5b8bb", metallic=1, rough=0.30), dirt=dict(color="#3d342a", rough=0.85)),
    "aluminum": dict(label="Aluminum", metallic=1, color="#d5d7d9", rough=0.38, rough_var=0.10, pattern="cast",
                     bump=0.2, worn=dict(color="#eceef0", metallic=1, rough=0.22), dirt=dict(color="#55504a", rough=0.8)),
    "anodized_aluminum": dict(label="Anodized aluminum", metallic=1, color="#4a5f86", rough=0.34, rough_var=0.06,
                              pattern="cast", bump=0.15, paintable=True,
                              worn=dict(color="#d9dbdd", metallic=1, rough=0.25), dirt=dict(color="#3a3632", rough=0.8)),
    "brass": dict(label="Brass", metallic=1, color="#d8bb72", rough=0.30, rough_var=0.12, pattern="scratches",
                  bump=0.2, worn=dict(color="#f2dc98", metallic=1, rough=0.15), dirt=dict(color="#3e3a24", rough=0.85)),
    "copper": dict(label="Copper", metallic=1, color="#dc9a78", rough=0.32, rough_var=0.12, pattern="scratches",
                   bump=0.2, worn=dict(color="#f4c0a4", metallic=1, rough=0.16), dirt=dict(color="#2f4a3c", rough=0.85)),
    "gold": dict(label="Gold", metallic=1, color="#f0cb6c", rough=0.22, rough_var=0.08, pattern="scratches",
                 bump=0.15, worn=dict(color="#fbe39c", metallic=1, rough=0.12), dirt=dict(color="#4a3c20", rough=0.8)),
    "chrome": dict(label="Chrome", metallic=1, color="#e3e5e7", rough=0.06, rough_var=0.05, pattern="none",
                   bump=0.0, worn=dict(color="#e3e5e7", metallic=1, rough=0.2), dirt=dict(color="#5a554e", rough=0.6)),
    "iron": dict(label="Cast iron", metallic=1, color="#717376", rough=0.62, rough_var=0.12, pattern="cast",
                 bump=0.5, worn=dict(color="#a9abae", metallic=1, rough=0.35), dirt=dict(color="#3a3028", rough=0.9)),
    "rusty_metal": dict(label="Rusty metal", metallic=1, color="#8e9093", rough=0.5, rough_var=0.15,
                        pattern="cast", bump=0.4, worn=dict(color="#b0b2b5", metallic=1, rough=0.3),
                        dirt=dict(color="#7a3e1c", rough=0.92, metallic=0, rust=True)),
    # plastics and rubber
    "polymer": dict(label="Polymer", metallic=0, color="#2a2b2d", rough=0.62, rough_var=0.08, pattern="stipple",
                    bump=0.35, worn=dict(color="#45464a", metallic=0, rough=0.42), dirt=dict(color="#2b2622", rough=0.8)),
    "plastic": dict(label="Plastic", metallic=0, color="#c63a30", rough=0.42, rough_var=0.06, pattern="plastic",
                    bump=0.15, paintable=True, worn=dict(color="lighter", metallic=0, rough=0.58),
                    dirt=dict(color="#3a332c", rough=0.7)),
    "rubber": dict(label="Rubber", metallic=0, color="#1f1f20", rough=0.86, rough_var=0.06, pattern="rubber",
                   bump=0.4, worn=dict(color="#323234", metallic=0, rough=0.72), dirt=dict(color="#2e2924", rough=0.9)),
    "carbon_fiber": dict(label="Carbon fiber", metallic=0, color="#1b1c1e", color2="#34373b", rough=0.28,
                         rough_var=0.05, pattern="carbon", bump=0.2, coat=1.0,
                         worn=dict(color="#4a4c50", metallic=0, rough=0.5), dirt=dict(color="#2a2622", rough=0.7)),
    # natural
    "wood": dict(label="Wood", metallic=0, color="#93683f", color2="#55361c", rough=0.58, rough_var=0.1,
                 pattern="wood", bump=0.5, worn=dict(color="#b98754", metallic=0, rough=0.4),
                 dirt=dict(color="#2e2216", rough=0.8)),
    "painted_wood": dict(label="Painted wood", metallic=0, color="#3f6f8f", rough=0.6, rough_var=0.08,
                         pattern="paint", bump=0.25, paintable=True, chip_depth=1.0,
                         worn=dict(color="#8f5e34", metallic=0, rough=0.62), dirt=dict(color="#33291f", rough=0.85)),
    "leather": dict(label="Leather", metallic=0, color="#5c3421", rough=0.55, rough_var=0.12, pattern="leather",
                    bump=0.5, worn=dict(color="#7e4d31", metallic=0, rough=0.38), dirt=dict(color="#24180f", rough=0.8)),
    "fabric": dict(label="Fabric", metallic=0, color="#4b5662", rough=0.92, rough_var=0.04, pattern="weave",
                   bump=0.5, sheen=0.6, paintable=True, worn=dict(color="lighter", metallic=0, rough=0.95),
                   dirt=dict(color="#3a3228", rough=0.95)),
    "stone": dict(label="Stone", metallic=0, color="#8b877f", color2="#5e5a52", rough=0.84, rough_var=0.1,
                  pattern="stone", bump=0.8, worn=dict(color="#a8a49b", metallic=0, rough=0.7),
                  dirt=dict(color="#3e3a2e", rough=0.95)),
    "concrete": dict(label="Concrete", metallic=0, color="#9b9991", rough=0.9, rough_var=0.06, pattern="concrete",
                     bump=0.6, worn=dict(color="#b4b2aa", metallic=0, rough=0.85), dirt=dict(color="#45403a", rough=0.95)),
    "ceramic": dict(label="Ceramic", metallic=0, color="#e6e2da", rough=0.12, rough_var=0.04, pattern="none",
                    bump=0.0, worn=dict(color="#c9c0b0", metallic=0, rough=0.75), dirt=dict(color="#5a5045", rough=0.6)),
    "skin": dict(label="Skin", metallic=0, color="#c79076", rough=0.5, rough_var=0.08, pattern="skin", bump=0.3,
                 subsurface=0.12, worn=dict(color="#d4a088", metallic=0, rough=0.45), dirt=dict(color="#7a5040", rough=0.6)),
    # special
    "glass": dict(label="Glass", metallic=0, color="#e9f1f1", rough=0.03, rough_var=0.02, pattern="none",
                  bump=0.0, transmission=1.0, alpha=0.3, ior=1.5, wearable=False,
                  worn=dict(color="#e9f1f1", metallic=0, rough=0.2), dirt=dict(color="#8a8478", rough=0.6)),
    "emissive": dict(label="Glowing emissive", metallic=0, color="#36c8ff", rough=0.3, rough_var=0.04,
                     pattern="none", bump=0.0, emission=8.0, paintable=True, wearable=False,
                     worn=dict(color="#36c8ff", metallic=0, rough=0.3), dirt=dict(color="#202020", rough=0.6)),
}

# Words people (and AIs) use for the same thing.
ALIASES = {
    "metal": "steel", "iron_metal": "iron", "dark_metal": "gunmetal", "gun_metal": "gunmetal", "blued_steel": "gunmetal",
    "brushed": "brushed_metal", "brushed_steel": "brushed_metal", "paint": "painted_metal", "painted": "painted_metal",
    "painted_steel": "painted_metal", "aluminium": "aluminum", "anodized": "anodized_aluminum", "bronze": "brass",
    "rust": "rusty_metal", "rusty": "rusty_metal", "plastic_black": "polymer", "black_plastic": "polymer",
    "polymer_plastic": "polymer", "carbon": "carbon_fiber", "cloth": "fabric", "canvas": "fabric", "rock": "stone",
    "marble": "ceramic", "porcelain": "ceramic", "glow": "emissive", "light": "emissive", "neon": "emissive",
    "glowing": "emissive", "emission": "emissive", "lens": "glass", "flesh": "skin",
}

# Per-material CC0 texture sets (Poly Haven ids); used only when the person agreed to downloads (see cc0.py).
CC0 = {
    "wood": ("polyhaven", "wood_table_001"),
    "leather": ("polyhaven", "brown_leather"),
    "fabric": ("polyhaven", "denim_fabric"),
    "stone": ("polyhaven", "rock_wall_10"),
    "concrete": ("polyhaven", "concrete_floor_02"),
    "rusty_metal": ("polyhaven", "rusty_metal_02"),
}


def resolve(kind):
    """A material key from what was asked ('Gun Metal' -> 'gunmetal'); None when unknown."""
    if not isinstance(kind, str):
        return None
    k = kind.strip().lower().replace("-", "_").replace(" ", "_")
    if k in MATERIALS:
        return k
    if k in ALIASES:
        return ALIASES[k]
    k2 = k.replace("_", "")
    for name in MATERIALS:
        if name.replace("_", "") == k2:
            return name
    return None


def names():
    return sorted(MATERIALS)


def describe():
    """A short list for the AI: key, label, metal or not, and whether a color can be given."""
    rows = []
    for k in names():
        m = MATERIALS[k]
        rows.append({"material": k, "label": m["label"], "metallic": m["metallic"],
                     "color": bool(m.get("paintable"))})
    return rows
