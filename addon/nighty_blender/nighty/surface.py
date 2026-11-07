# SPDX-License-Identifier: GPL-3.0-or-later
"""Named materials from the smart-material library, for building in code (the assign_materials tool uses the same
library per part). Realistic: worn edges and cavity dirt from the real geometry, metallic exactly 0 or 1, ready to
bake. Stylized (game look, like Fortnite): clean and saturated, metals stay metal, a soft top-down gradient and
painted edge highlights. Painted (hand-painted look): light and shadow painted into the colors, matte.

    body = n.surface("Rifle Body", "anodized", color="#1d1e21")       # anodized aluminum, worn silver edges
    wood = n.surface("Crate Pine", "wood", color="#a77d50", grain="X") # planks along X, each a bit different
    gold = n.surface("Chest Gold", "gold", style="stylized")           # painted highlights, soft gradient
    n.paint([lid, body], wood)

Kinds: n.surfaces() (steel, gunmetal, painted_metal, aluminum, anodized_aluminum, brass, gold, chrome, iron,
polymer, plastic, rubber, carbon_fiber, wood, painted_wood, leather, fabric, stone, concrete, ceramic, glass,
emissive...; plain words work too: "metal", "paint", "anodized", "glow", "rock"). Wear and dirt show in Cycles
renders and in bakes.
"""

import bpy

from . import core

__all__ = ["surface", "surfaces"]

STYLES = {"realistic": "pbr", "pbr": "pbr", "stylized": "stylized", "stylised": "stylized", "toon": "stylized",
          "painted": "painted", "hand_painted": "painted", "handpainted": "painted"}
GAME_LOOK = {"gradient": 0.42, "light": 0.0, "steps": 0, "edges": 0.6, "ao": 0.35, "cavity": 0.45,
             "saturation": 1.15, "roughness": 0.5, "light_dir": (-0.45, -0.35, 0.82), "edge_width": 0.004}


def surfaces():
    """The material kinds: [(key, label, metal or not, takes a color)]."""
    from .materials import library
    return [(k, v["label"], bool(v["metallic"]), bool(v.get("paintable"))) for k, v in sorted(library.MATERIALS.items())]


def surface(name, kind="steel", color=None, style="realistic", wear=0.35, dirt=0.25, roughness=None, grain=None,
            glow=None, size=None):
    """A material named name (made or rebuilt in place) of a library kind, shared by every part you paint with it.

    color: the paint / plastic / anodizing / glow color, or a wood / leather / stone tone ('#rrggbb'); metals keep
    their real color (stylized: tinted too). style: "realistic", "stylized" (game look) or "painted" (hand-painted).
    wear 0.1 new .. 0.7 battered; dirt 0.1 clean .. 0.6 grimy (stylized keeps both low).
    roughness: overrides the clean roughness. grain: "X" / "Y" / "Z", the direction wood grain and brushing run
    (default X). glow: emission strength for "emissive" (default 8). size: the asset size in meters (default
    n.settings size): wear width and dirt reach follow it.

        steel = n.surface("Bolts", "steel")
        neon = n.surface("Core", "emissive", color="#2fe0ff", glow=12)
    """
    from .materials import build as mbuild, compat as mcompat, library, stylize as mstyle
    key = library.resolve(kind)
    if key is None:
        raise ValueError(f"unknown kind {kind!r}; kinds: {', '.join(library.names())}")
    mode = STYLES.get(str(style).lower())
    if mode is None:
        raise ValueError('style must be "realistic", "stylized" or "painted"')
    mat = bpy.data.materials.get(name) or mcompat.new_material(name)
    axis = None if grain is None else "XYZ".index(str(grain).upper()[0])
    if axis is None:
        axis = 0
    size = float(size or core.settings()["size"]) * 1.2   # the asset's diagonal, roughly
    tint = color if (color is None or isinstance(color, str)) else _hex(color)
    if mode == "painted":
        mstyle.build_stylized(mat, key, None, tint=tint, wear=wear, dirt=dirt, asset_size=size, axis=axis,
                              force_tint=tint is not None, glow=glow)
    elif mode == "stylized":
        spec = library.MATERIALS[key]
        mbuild.build(mat, key, None, wear=min(wear, 0.2), dirt=min(dirt, 0.12), tint=tint, roughness=roughness,
                     asset_size=size, axis=axis, force_tint=tint is not None and not spec["metallic"], glow=glow)
        if tint is not None and spec["metallic"]:
            _tint_metal(mat, tint)
        if not spec.get("emission") and not spec.get("transmission"):
            _game_look(mat, mstyle, size)
    else:
        mbuild.build(mat, key, None, wear=wear, dirt=dirt, tint=tint, roughness=roughness, asset_size=size,
                     axis=axis, force_tint=tint is not None, glow=glow)
    mat.name = name
    mat["nighty_surface"] = key
    return mat


def _game_look(mat, mstyle, size):
    """The stylize group in front of the base color only: gradient, painted edge highlights, richer cavities;
    metallic and roughness stay as built (metal 0 / 1 for the bake)."""
    from .materials.compat import principled_of, socket
    p = principled_of(mat)
    if p is None:
        return
    tree = mat.node_tree
    node = tree.nodes.new("ShaderNodeGroup")
    node.node_tree = mstyle.group()
    mstyle._set_inputs(node, mstyle.make_options(GAME_LOOK), size)
    bc = socket(p.inputs, "Base Color")
    if bc.is_linked:
        tree.links.new(bc.links[0].from_socket, socket(node.inputs, "Color"))
    else:
        socket(node.inputs, "Color").default_value = bc.default_value
    tree.links.new(socket(node.outputs, "Color"), bc)
    node.location = (p.location.x - 260, p.location.y - 300)


def _tint_metal(mat, tint):
    """Stylized metals take the asked color (a brighter gold, a blue steel): multiply the base color by it."""
    from .materials.compat import color, principled_of, socket
    p = principled_of(mat)
    if p is None:
        return
    tree = mat.node_tree
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MIX"
    mix.inputs[0].default_value = 0.75
    bc = socket(p.inputs, "Base Color")
    if bc.is_linked:
        tree.links.new(bc.links[0].from_socket, mix.inputs[6])
    else:
        mix.inputs[6].default_value = bc.default_value
    mix.inputs[7].default_value = color(tint)
    tree.links.new(mix.outputs[2], bc)
    mat.diffuse_color = color(tint)


def _hex(rgb):
    """A linear RGB(A) tuple -> '#rrggbb' (sRGB)."""
    out = []
    for v in tuple(rgb)[:3]:
        v = max(0.0, min(1.0, float(v)))
        s = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
        out.append(max(0, min(255, int(round(s * 255)))))
    return "#%02x%02x%02x" % tuple(out)
