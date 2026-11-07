# SPDX-License-Identifier: GPL-3.0-or-later
"""Quick materials for building and previews (one Principled BSDF). Full texturing lives in nighty's
texture helpers (smart materials, wear, bakes); these keep a model readable while you build it."""

import bpy

from . import compat
from .core import get, to_list

__all__ = ["material", "paint", "hex_color"]


def hex_color(value):
    """"#ff8800" / "ff8800" -> linear RGBA (what node colors want)."""
    s = str(value).lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    rgb = [int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return (lin[0], lin[1], lin[2], 1.0)


def _rgba(color):
    if isinstance(color, str):
        return hex_color(color)
    c = tuple(float(x) for x in color)
    return c + (1.0,) * (4 - len(c)) if len(c) < 4 else c[:4]


def material(name, color=(0.8, 0.8, 0.8), metallic=0.0, roughness=0.5, emission=None, strength=1.0, alpha=1.0,
             transmission=0.0, coat=0.0, variation=0.0, scale=None):
    """A Principled material (made or updated by name). color: linear RGB(A) or "#hex".

    emission: a color for glowing parts (strength in W/m2-ish units, 1-20). transmission 1 = glass.
    variation 0..1: soft noise in color and roughness so surfaces don't look flat (scale: noise size, meters).

        steel = n.material("Steel", "#9aa3ad", metallic=1, roughness=0.35)
        glow = n.material("Glow", "#33ccff", emission="#33ccff", strength=8)
    """
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    tree = compat.ensure_nodes(mat)
    bsdf = compat.node(tree, "BSDF_PRINCIPLED")
    out = compat.node(tree, "OUTPUT_MATERIAL")
    if bsdf is None:
        bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    if out is None:
        out = tree.nodes.new("ShaderNodeOutputMaterial")
    if not out.inputs["Surface"].is_linked:
        tree.links.new(bsdf.outputs[0], out.inputs["Surface"])
    rgba = _rgba(color)
    compat.set_input(bsdf, "Base Color", rgba)
    compat.set_input(bsdf, "Metallic", float(metallic))
    compat.set_input(bsdf, "Roughness", float(roughness))
    compat.set_input(bsdf, "Alpha", float(alpha))
    compat.set_input(bsdf, "Transmission Weight", float(transmission))
    compat.set_input(bsdf, "Coat Weight", float(coat))
    if emission is not None:
        compat.set_input(bsdf, "Emission Color", _rgba(emission))
        compat.set_input(bsdf, "Emission Strength", float(strength))
    else:
        compat.set_input(bsdf, "Emission Strength", 0.0)
    for n_ in [n_ for n_ in tree.nodes if n_.get("nighty_variation")]:
        tree.nodes.remove(n_)
    if variation > 0:
        _add_variation(tree, bsdf, rgba, float(roughness), float(variation), scale)
    if alpha < 1.0 or transmission > 0.5:
        compat.set_transparent(mat, blended=alpha < 1.0)
    mat.diffuse_color = rgba  # the viewport / Solid view color
    mat.metallic = float(metallic)
    mat.roughness = float(roughness)
    return mat


def _add_variation(tree, bsdf, rgba, rough, amount, scale):
    from . import core
    size = scale or core.settings()["size"] * 0.08
    coord = tree.nodes.new("ShaderNodeTexCoord")
    noise = tree.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 1.0 / max(1e-4, size)
    compat.set_input(noise, "Detail", 4.0)
    dark = tuple(max(0.0, c * (1.0 - 0.6 * amount)) for c in rgba[:3]) + (1.0,)
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs[6].default_value = rgba
    mix.inputs[7].default_value = dark
    tree.links.new(coord.outputs["Object"], noise.inputs["Vector"])
    tree.links.new(noise.outputs["Fac"], mix.inputs[0])
    tree.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    rmap = tree.nodes.new("ShaderNodeMapRange")
    rmap.inputs["To Min"].default_value = max(0.0, rough - 0.15 * amount)
    rmap.inputs["To Max"].default_value = min(1.0, rough + 0.15 * amount)
    tree.links.new(noise.outputs["Fac"], rmap.inputs["Value"])
    tree.links.new(rmap.outputs["Result"], bsdf.inputs["Roughness"])
    for n_ in (coord, noise, mix, rmap):
        n_["nighty_variation"] = True
        n_.location = (bsdf.location.x - 400, bsdf.location.y)


def paint(objs, mat, faces=None):
    """Gives objects a material (a material, its name, or a color). faces: indices that get it (others keep theirs).

        n.paint([body, lid], wood)
        n.paint(body, "#202020")
    """
    if isinstance(mat, (tuple, list)) or (isinstance(mat, str) and mat.startswith("#")):
        mat = material("Color " + (mat if isinstance(mat, str) else ",".join(f"{c:.2f}" for c in mat)), mat)
    elif isinstance(mat, str):
        found = bpy.data.materials.get(mat)
        if found is None:
            raise KeyError(f"no material named {mat!r}")
        mat = found
    for o in to_list(objs):
        if o.data is None or not hasattr(o.data, "materials"):
            continue
        mats = o.data.materials
        if faces is None:
            mats.clear()
            mats.append(mat)
        else:
            if mat.name not in [m.name for m in mats if m]:
                mats.append(mat)
            idx = [m.name if m else "" for m in mats].index(mat.name)
            for i in faces:
                o.data.polygons[i].material_index = idx
    return mat
