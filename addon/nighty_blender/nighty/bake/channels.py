# SPDX-License-Identifier: GPL-3.0-or-later
"""The emission-rewire trick: Blender cannot bake metallic (and a diffuse bake of a metal comes out black), so each
channel is baked by replacing every shader (BSDF) with an Emission shader that emits that channel's input.
Mix shaders stay, so mixed materials blend their channels exactly. Works on throw-away material copies."""

import bpy

from ..materials.compat import socket

# for each BSDF type: channel -> input name (str), a constant (number / color), or None (= keep the default)
_TABLE = {
    "BSDF_PRINCIPLED": {"base_color": "Base Color", "roughness": "Roughness", "metallic": "Metallic",
                        "opacity": "Alpha"},
    "BSDF_DIFFUSE": {"base_color": "Color", "roughness": 1.0, "metallic": 0.0, "opacity": 1.0},
    "BSDF_GLOSSY": {"base_color": "Color", "roughness": "Roughness", "metallic": 1.0, "opacity": 1.0},
    "BSDF_ANISOTROPIC": {"base_color": "Color", "roughness": "Roughness", "metallic": 1.0, "opacity": 1.0},
    "BSDF_GLASS": {"base_color": "Color", "roughness": "Roughness", "metallic": 0.0, "opacity": 0.3},
    "BSDF_REFRACTION": {"base_color": "Color", "roughness": "Roughness", "metallic": 0.0, "opacity": 0.3},
    "BSDF_TRANSLUCENT": {"base_color": "Color", "roughness": 1.0, "metallic": 0.0, "opacity": 1.0},
    "BSDF_SHEEN": {"base_color": "Color", "roughness": 1.0, "metallic": 0.0, "opacity": 1.0},
    "SUBSURFACE_SCATTERING": {"base_color": "Color", "roughness": 0.5, "metallic": 0.0, "opacity": 1.0},
    "BSDF_TOON": {"base_color": "Color", "roughness": 0.5, "metallic": 0.0, "opacity": 1.0},
    "EMISSION": {"base_color": 0.0, "roughness": 1.0, "metallic": 0.0, "opacity": 1.0},
    "BSDF_TRANSPARENT": {"base_color": 0.0, "roughness": 1.0, "metallic": 0.0, "opacity": 0.0},
    "HOLDOUT": {"base_color": 0.0, "roughness": 1.0, "metallic": 0.0, "opacity": 0.0},
}


def _source(tree, node, inp_name):
    """(linked socket or None, default value) of an input."""
    try:
        inp = socket(node.inputs, inp_name)
    except KeyError:
        return None, 0.0
    if inp.is_linked:
        return inp.links[0].from_socket, None
    return None, inp.default_value


def _emit_value(tree, em, src, value):
    if src is not None:
        tree.links.new(src, socket(em.inputs, "Color"))
        return
    if isinstance(value, (int, float)):
        socket(em.inputs, "Color").default_value = (value, value, value, 1.0)
    else:
        v = tuple(value)
        socket(em.inputs, "Color").default_value = v if len(v) == 4 else v + (1.0,)


def _emission_channel(tree, node, em):
    """Emission map: Principled Emission Color (on where Emission Strength > 0); an Emission shader's color."""
    if node.type == "BSDF_PRINCIPLED":
        src, val = _source(tree, node, "Emission Color")
        _emit_value(tree, em, src, val)
        s_src, s_val = _source(tree, node, "Emission Strength")
        if s_src is not None:
            gt = tree.nodes.new("ShaderNodeMath")
            gt.operation = "GREATER_THAN"
            gt.inputs[1].default_value = 0.0
            tree.links.new(s_src, gt.inputs[0])
            tree.links.new(gt.outputs[0], socket(em.inputs, "Strength"))
        else:
            socket(em.inputs, "Strength").default_value = 1.0 if s_val > 0 else 0.0
    elif node.type == "EMISSION":
        src, val = _source(tree, node, "Color")
        _emit_value(tree, em, src, val)
        s_src, s_val = _source(tree, node, "Strength")
        socket(em.inputs, "Strength").default_value = 1.0 if (s_src is not None or s_val > 0) else 0.0
    else:
        socket(em.inputs, "Color").default_value = (0, 0, 0, 1)


def rewire(tree, channel, _seen=None):
    """Turns every shader node in `tree` (and in node groups, copied first) into an Emission of `channel`.
    channel: base_color | roughness | metallic | emission | opacity | white (coverage) | normal (diffuse with the
    shader's bump, for normal bakes) | plain (diffuse, for AO)."""
    _seen = _seen if _seen is not None else set()
    for node in list(tree.nodes):
        if node.type == "GROUP" and node.node_tree is not None:
            if any(o.type == "SHADER" for o in node.outputs):
                if node.node_tree.name not in _seen:
                    node.node_tree = node.node_tree.copy()
                    _seen.add(node.node_tree.name)
                    rewire(node.node_tree, channel, _seen)
            continue
        if node.type not in _TABLE and not (node.outputs and node.outputs[0].type == "SHADER"
                                            and node.type.startswith("BSDF")):
            continue
        if channel in ("normal", "plain"):
            # normal / AO bakes: one opaque diffuse surface that keeps the shader's bump (normal) or not (plain)
            df = tree.nodes.new("ShaderNodeBsdfDiffuse")
            df.location = node.location
            if channel == "normal":
                try:
                    n_in = socket(node.inputs, "Normal")
                    if n_in.is_linked:
                        tree.links.new(n_in.links[0].from_socket, socket(df.inputs, "Normal"))
                except KeyError:
                    pass
            for out in node.outputs:
                if out.type == "SHADER":
                    for link in list(out.links):
                        tree.links.new(df.outputs[0], link.to_socket)
            tree.nodes.remove(node)
            continue
        em = tree.nodes.new("ShaderNodeEmission")
        em.location = node.location
        socket(em.inputs, "Strength").default_value = 1.0
        if channel == "white":
            socket(em.inputs, "Color").default_value = (1, 1, 1, 1)
        elif channel == "emission":
            _emission_channel(tree, node, em)
        else:
            what = _TABLE.get(node.type, {}).get(channel, 0.0)
            if isinstance(what, str):
                src, val = _source(tree, node, what)
                _emit_value(tree, em, src, val)
            else:
                _emit_value(tree, em, None, what)
        for out in node.outputs:
            if out.type == "SHADER":
                for link in list(out.links):
                    tree.links.new(em.outputs[0], link.to_socket)
        tree.nodes.remove(node)
    # displacement would move the surface during a color bake: off
    for out in [n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"]:
        for name in ("Displacement",):
            try:
                d = socket(out.inputs, name)
            except KeyError:
                continue
            for link in list(d.links):
                tree.links.remove(link)


def emission_strength(materials):
    """The largest emission strength among the materials (for the rebuilt material)."""
    best = 0.0
    for mat in materials:
        if mat is None or mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            try:
                if node.type == "BSDF_PRINCIPLED":
                    s = socket(node.inputs, "Emission Strength")
                    c = socket(node.inputs, "Emission Color")
                    lit = c.is_linked or max(c.default_value[:3]) > 0
                    if lit:
                        best = max(best, 1.0 if s.is_linked else float(s.default_value))
                elif node.type == "EMISSION":
                    s = socket(node.inputs, "Strength")
                    best = max(best, 1.0 if s.is_linked else float(s.default_value))
            except KeyError:
                pass
    return best


def has_alpha(materials):
    for mat in materials:
        if mat is None or mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            if node.type in ("BSDF_TRANSPARENT", "BSDF_GLASS"):
                return True
            if node.type == "BSDF_PRINCIPLED":
                a = socket(node.inputs, "Alpha")
                if a.is_linked or a.default_value < 0.999:
                    return True
    return False
