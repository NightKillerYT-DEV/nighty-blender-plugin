# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized / hand-painted look: everything a painter puts into the color map, from the real geometry, then baked.

- a soft vertical gradient (darker low, lighter high) per part,
- painted light: a fixed light direction stepped into toon bands (shadow tint cool, light warm),
- ambient occlusion baked into the albedo on purpose,
- painted edge highlights on convex edges, darker cavities,
- flat roughness, metallic 0 (metal reads as painted highlights).
It all lives in one node group ("NB Stylize v1") placed before the Principled base color, so it works on Nighty
materials and on anyone else's material."""

import json

import bpy

from . import compat, library
from .compat import Graph, color, socket

GROUP = "NB Stylize v3"
DEFAULTS = {"gradient": 0.55, "light": 0.8, "light_dir": (-0.45, -0.35, 0.82), "steps": 3, "edges": 0.75,
            "ao": 0.7, "cavity": 0.5, "roughness": 0.75, "saturation": 1.12, "edge_width": 0.004}


def group():
    ng = bpy.data.node_groups.get(GROUP)
    if ng:
        return ng
    ng, gin, gout = compat.new_group(GROUP, [
        ("Color", "NodeSocketColor", (0.5, 0.5, 0.5, 1.0)), ("Gradient", "NodeSocketFloat", 0.5),
        ("Light", "NodeSocketFloat", 0.6), ("Light Direction", "NodeSocketVector", (-0.45, -0.35, 0.82)),
        ("Steps", "NodeSocketFloat", 3.0), ("Edges", "NodeSocketFloat", 0.6), ("Edge Width", "NodeSocketFloat", 0.004),
        ("AO", "NodeSocketFloat", 0.7), ("AO Distance", "NodeSocketFloat", 0.08), ("Cavity", "NodeSocketFloat", 0.5),
        ("Saturation", "NodeSocketFloat", 1.12),
    ], [("Color", "NodeSocketColor", None)])
    g = Graph(ng)
    i = {s.name: s for s in gin.outputs}
    # richer color first (hand-painted palettes are more saturated than scans)
    hsv = g.node("ShaderNodeHueSaturation")
    g.set(socket(hsv.inputs, "Color"), i["Color"])
    g.set(socket(hsv.inputs, "Saturation"), i["Saturation"])
    col = socket(hsv.outputs, "Color")
    # vertical gradient over the part's bounding box
    gen = g.node("ShaderNodeTexCoord")
    sep = g.node("ShaderNodeSeparateXYZ")
    g.set(sep.inputs[0], socket(gen.outputs, "Generated"))
    grad = g.map_range(sep.outputs[2], 0.0, 1.0, 0.6, 1.15)
    grad = g.mix(i["Gradient"], 1.0, grad, kind="FLOAT")
    col = g.mix(1.0, col, grad, blend="MULTIPLY")
    # painted light in bands
    nrm = g.vmath("NORMALIZE", i["Light Direction"])
    ndl = g.vmath("DOT_PRODUCT", g.geometry("Normal"), nrm)
    wrap = g.math("MULTIPLY_ADD", ndl, 0.5, 0.5)
    q = g.math("DIVIDE", g.math("ROUND", g.math("MULTIPLY", wrap, i["Steps"])), g.math("MAXIMUM", i["Steps"], 1.0))
    band = g.mix(g.math("GREATER_THAN", i["Steps"], 0.5), wrap, g.mix(0.8, wrap, q, kind="FLOAT"), kind="FLOAT")
    shade = g.mix(band, color("#5b6a9a"), color("#fff1d6"))
    shade = g.mix(i["Light"], (1, 1, 1, 1), g.mix(0.22, shade, (1, 1, 1, 1)), kind="RGBA")
    col = g.mix(1.0, col, shade, blend="MULTIPLY")
    # ambient occlusion in the albedo
    occ = g.node("ShaderNodeAmbientOcclusion", samples=16, only_local=False)
    g.set(socket(occ.inputs, "Distance"), i["AO Distance"])
    ao = g.map_range(socket(occ.outputs, "AO"), 0.0, 1.0, 0.35, 1.0)
    col = g.mix(i["AO"], col, g.mix(1.0, col, ao, blend="MULTIPLY"))
    # painted edge highlights (convex edges, from inside occlusion: works on beveled and sharp edges)
    ins = g.node("ShaderNodeAmbientOcclusion", samples=16, only_local=True, inside=True)
    g.set(socket(ins.inputs, "Distance"), i["Edge Width"])
    edge = g.map_range(g.math("SUBTRACT", 1.0, socket(ins.outputs, "AO")), 0.03, 0.13)
    bev = g.node("ShaderNodeBevel", samples=6)
    g.set(socket(bev.inputs, "Radius"), i["Edge Width"])
    sharp = g.map_range(g.math("SUBTRACT", 1.0, g.vmath("DOT_PRODUCT", bev.outputs[0], g.geometry("Normal"))),
                        0.01, 0.08)
    edge = g.math("MAXIMUM", edge, sharp)
    light_col = g.mix(0.7, col, (1.0, 0.97, 0.9, 1.0), blend="SCREEN")
    col = g.mix(g.math("MULTIPLY", edge, i["Edges"]), col, light_col)
    # darker, richer cavities
    cav = g.node("ShaderNodeAmbientOcclusion", samples=16, only_local=True)
    g.set(socket(cav.inputs, "Distance"), g.math("MULTIPLY", i["Edge Width"], 4.0))
    cm = g.map_range(g.math("SUBTRACT", 1.0, socket(cav.outputs, "AO")), 0.1, 0.5)
    col = g.mix(g.math("MULTIPLY", cm, i["Cavity"]), col, g.mix(1.0, col, (0.35, 0.3, 0.4, 1), blend="MULTIPLY"))
    g.links.new(col, socket(gout.inputs, "Color"))
    compat.layout(ng)
    return ng


def _set_inputs(node, opts, size):
    for key, name in (("gradient", "Gradient"), ("light", "Light"), ("steps", "Steps"), ("edges", "Edges"),
                      ("ao", "AO"), ("cavity", "Cavity"), ("saturation", "Saturation")):
        socket(node.inputs, name).default_value = float(opts[key])
    socket(node.inputs, "Light Direction").default_value = tuple(opts["light_dir"])
    scale = max(0.3, min(3.0, size)) ** 0.5
    socket(node.inputs, "Edge Width").default_value = float(opts.get("edge_width", 0.004)) * scale
    socket(node.inputs, "AO Distance").default_value = 0.06 * max(0.2, min(5.0, size)) ** 0.7


def make_options(given=None):
    o = dict(DEFAULTS)
    for k, v in (given or {}).items():
        if k in o and v is not None:
            o[k] = v
    o["steps"] = max(0, min(6, int(round(float(o["steps"])))))
    for k in ("gradient", "light", "edges", "ao", "cavity", "roughness"):
        o[k] = max(0.0, min(1.0, float(o[k])))
    return o


def build_stylized(mat, kind, obj=None, tint=None, wear=0.3, dirt=0.25, options=None, asset_size=None, axis=None,
                   force_tint=False, glow=None):
    """A hand-painted version of library material `kind`: base color (+ big painterly shapes) through the
    stylize group, flat roughness, metallic 0, rounded edges in the normal."""
    from .build import object_size, seed_of
    opts = make_options(options)
    key = library.resolve(kind)
    spec = dict(library.MATERIALS[key])
    if tint and (spec.get("paintable") or force_tint):
        if force_tint and spec.get("color2"):
            from .build import _scaled
            spec["color2"] = _scaled(spec["color2"], spec["color"], tint)
        spec["color"] = tint
    if glow is not None and spec.get("emission"):
        spec["emission"] = float(glow)
    size = asset_size or object_size(obj)
    tree = compat.ensure_nodes(mat)
    tree.nodes.clear()
    g = Graph(tree)
    out = g.node("ShaderNodeOutputMaterial")
    bsdf = g.node("ShaderNodeBsdfPrincipled")
    g.links.new(bsdf.outputs[0], socket(out.inputs, "Surface"))
    seed = seed_of((obj.name if obj else "") + key)
    P = g.coords("Object", offset=((seed * 7.31) % 97.0, (seed * 3.17) % 89.0, 0.0))
    base = color(spec["color"])
    # big painterly brush shapes (no fine noise: hand-painted textures read at a distance)
    strokes = g.noise(P, 9.0 / max(0.3, min(3.0, size)) ** 0.5, detail=1.0, roughness=0.3, distortion=0.4)[0]
    col = g.mix(0.12, base, g.math("MULTIPLY", strokes, 2.0), blend="MULTIPLY")
    if spec.get("pattern") == "wood":
        # painted planks: long clean grain strokes along the part, a few darker lines
        from .build import long_axis, _stretch
        ax = long_axis(obj) if axis is None else int(axis)
        grain = g.noise(_stretch(g, P, ax, 1.2, 55.0), 1.0, detail=1.0, roughness=0.3)[0]
        lines = g.map_range(grain, 0.6, 0.66)
        col = g.mix(g.math("MULTIPLY", lines, 0.6), col, color(spec.get("color2", "#4f2d15")))
        streak = g.noise(_stretch(g, P, ax, 0.8, 14.0), 1.0, detail=1.0)[0]
        col = g.mix(1.0, col, g.map_range(streak, 0.3, 0.7, 0.86, 1.12), blend="MULTIPLY")
    if spec.get("metallic"):
        # painted metal: a bright, cool sheen band instead of real metal
        col = g.mix(1.0, col, 0.72, blend="MULTIPLY")      # painted metal reads darker, edges carry the shine
        col = g.mix(0.07, col, (0.85, 0.9, 1.0, 1.0), blend="SCREEN")
    st = g.group(group())
    _set_inputs(st, opts, size)
    g.set(socket(st.inputs, "Color"), col)
    col_out = socket(st.outputs, "Color")
    g.set(socket(bsdf.inputs, "Base Color"), col_out)
    socket(bsdf.inputs, "Roughness").default_value = opts["roughness"] if not spec.get("metallic") else \
        max(0.35, opts["roughness"] - 0.25)
    socket(bsdf.inputs, "Metallic").default_value = 0.0
    g.set(socket(bsdf.inputs, "Normal"), g.bevel(0.0025 * max(0.3, min(3.0, size)) ** 0.5, samples=6))
    if spec.get("emission"):
        socket(bsdf.inputs, "Emission Color").default_value = color(spec["color"])
        socket(bsdf.inputs, "Emission Strength").default_value = spec["emission"]
    if spec.get("alpha") is not None:
        socket(bsdf.inputs, "Alpha").default_value = max(0.5, spec["alpha"])
    compat.layout(tree)
    mat.diffuse_color = base
    mat.metallic = 0.0
    mat.roughness = opts["roughness"]
    params = {"v": 1, "kind": key, "style": "stylized", "wear": round(float(wear), 3), "dirt": round(float(dirt), 3),
              "tint": tint if spec.get("paintable") else None, "seed": seed, "metallic": 0, "stylize": opts}
    mat["nighty"] = json.dumps(params, default=list)
    return params


def wrap(mat, opts, size=1.0):
    """Puts the stylize group in front of any Principled material's base color (and flattens roughness /
    metallic). Returns False when the material has no single Principled BSDF."""
    p = compat.principled_of(mat)
    if p is None:
        return False
    tree = mat.node_tree
    g = Graph(tree)
    existing = [n for n in tree.nodes if n.type == "GROUP" and n.node_tree and n.node_tree.name == GROUP]
    if existing:
        _set_inputs(existing[0], opts, size)
    else:
        bc = socket(p.inputs, "Base Color")
        st = g.group(group())
        _set_inputs(st, opts, size)
        if bc.is_linked:
            g.links.new(bc.links[0].from_socket, socket(st.inputs, "Color"))
        else:
            socket(st.inputs, "Color").default_value = bc.default_value
        g.links.new(socket(st.outputs, "Color"), bc)
        st.location = (p.location.x - 250, p.location.y)
    for name, val in (("Roughness", opts["roughness"]), ("Metallic", 0.0)):
        s = socket(p.inputs, name)
        for link in list(s.links):
            tree.links.remove(link)
        s.default_value = val
    return True


def stylize(objects, opts_in=None):
    """Turns the parts' materials stylized: Nighty materials are rebuilt stylized (their kind and color kept),
    other materials get the stylize group. Returns a summary per part."""
    from . import asset_extent
    from ..bake.apply import restore_sources
    opts = make_options(opts_in)
    size = asset_extent(objects)
    out = []
    for obj in objects:
        restore_sources(obj)
        done = False
        for slot in obj.material_slots:
            m = slot.material
            if m is None:
                continue
            params = {}
            try:
                params = json.loads(m.get("nighty", "{}"))
            except ValueError:
                pass
            if params.get("kind"):
                build_stylized(m, params["kind"], obj, tint=params.get("tint"), wear=params.get("wear", 0.3),
                               dirt=params.get("dirt", 0.25), options=opts, asset_size=size)
                done = True
            elif wrap(m, opts, size):
                done = True
        out.append({"part": obj.name, "stylized": done})
    return out
