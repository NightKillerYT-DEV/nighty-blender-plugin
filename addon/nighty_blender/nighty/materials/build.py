# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds smart materials (node trees) from the library: a clean layer, a worn layer at real convex edges, dirt in
real cavities, procedural surface detail in 3D object space (no UVs, no seams), and an optional CC0 texture set.

Everything ends in ONE Principled BSDF whose inputs are mixed (never mixed shaders), so baking each channel through
an Emission shader is exact, and metallic stays strictly 0 or 1: where a worn or dirty layer has a different
metallic value, the switch is a hard step, never a blend.
"""

import json
import math
import zlib

import bpy

from . import compat
from .compat import Graph, color, socket
from . import library

VERSION = 1
TEXEL_NODE = "NB Texel Size"   # meters per texel; the bake sets it so micro detail fades before it aliases
EDGE_GROUP = "NB Edge Wear v6"
CAVITY_GROUP = "NB Cavity Dirt v4"


# ----------------------------------------------------------------------------------------------- shared groups

def edge_group():
    """Convex edge mask from real geometry, resolution independent (works on low poly and on beveled meshes):
    - sharp edges: the Bevel-node normal against the true normal (concave corners removed with a local AO test);
    - rounded / beveled edges: ambient occlusion from INSIDE the mesh (rays cast inward hit the nearby faces of
      a convex edge quickly, never at a concave one).
    Then broken up by noise. Output "Mask" is the continuous wear amount; the material cuts it with a narrow
    threshold (chips with crisp borders, not smears). The bake replaces the group by a clean baked copy of
    "Mask" first, so every map uses exactly the same wear."""
    ng = bpy.data.node_groups.get(EDGE_GROUP)
    if ng:
        return ng
    ng, gin, gout = compat.new_group(EDGE_GROUP, [
        ("Vector", "NodeSocketVector", None), ("Radius", "NodeSocketFloat", 0.003),
        ("Breakup Scale", "NodeSocketFloat", 30.0), ("Breakup", "NodeSocketFloat", 1.0),
    ], [("Mask", "NodeSocketFloat", None), ("Edge", "NodeSocketFloat", None)])
    g = Graph(ng)
    P, radius, bscale, bamount = (socket(gin.outputs, n) for n in ("Vector", "Radius", "Breakup Scale", "Breakup"))
    # sharp edges
    bev = g.node("ShaderNodeBevel", samples=8)
    g.set(socket(bev.inputs, "Radius"), radius)
    d = g.vmath("DOT_PRODUCT", bev.outputs[0], g.geometry("Normal"))
    e = g.map_range(g.math("SUBTRACT", 1.0, d), 0.002, 0.10)
    occl = g.node("ShaderNodeAmbientOcclusion", samples=8, only_local=True, inside=False)
    g.set(socket(occl.inputs, "Distance"), g.math("MULTIPLY", radius, 4.0))
    sharp = g.math("MULTIPLY", e, g.map_range(socket(occl.outputs, "AO"), 0.72, 0.93))
    # rounded edges
    ins = g.node("ShaderNodeAmbientOcclusion", samples=24, only_local=True, inside=True)
    g.set(socket(ins.inputs, "Distance"), g.math("MULTIPLY", radius, 0.9))
    rounded = g.map_range(g.math("SUBTRACT", 1.0, socket(ins.outputs, "AO")), 0.03, 0.13)
    edge = g.math("MAXIMUM", sharp, rounded)
    # breakup: large blotches decide where wear happens, fine noise makes the chip outline
    big = g.noise(P, 1.0, detail=6.0, roughness=0.6)[0]
    g.links.new(bscale, socket(big.node.inputs, "Scale"))
    fine = g.noise(P, 1.0, detail=10.0, roughness=0.7)[0]
    g.links.new(g.math("MULTIPLY", bscale, 6.0), socket(fine.node.inputs, "Scale"))
    br = g.math("ADD", g.math("MULTIPLY", big, 0.75), g.math("MULTIPLY", fine, 0.45))
    # Breakup 1 = chips (paint), lower = a more continuous polished edge (bare metal, plastic, wood)
    brk = g.mix(bamount, 1.05, g.map_range(br, 0.25, 0.85, 0.0, 1.6), kind="FLOAT")
    m = g.math("MULTIPLY", edge, brk)
    g.links.new(m, socket(gout.inputs, "Mask"))
    g.links.new(edge, socket(gout.inputs, "Edge"))
    compat.layout(ng)
    return ng


def cavity_group():
    """Cavity / contact dirt from real geometry: ambient occlusion (other parts count too) broken up by noise."""
    ng = bpy.data.node_groups.get(CAVITY_GROUP)
    if ng:
        return ng
    ng, gin, gout = compat.new_group(CAVITY_GROUP, [
        ("Vector", "NodeSocketVector", None), ("Distance", "NodeSocketFloat", 0.05),
        ("Dirt", "NodeSocketFloat", 0.3), ("Breakup Scale", "NodeSocketFloat", 8.0),
    ], [("Dirt", "NodeSocketFloat", None), ("Cavity", "NodeSocketFloat", None)])
    g = Graph(ng)
    P, dist, dirt, bscale = (socket(gin.outputs, n) for n in ("Vector", "Distance", "Dirt", "Breakup Scale"))
    occl = g.node("ShaderNodeAmbientOcclusion", samples=16, only_local=False, inside=False)
    g.set(socket(occl.inputs, "Distance"), dist)
    cav = g.map_range(g.math("SUBTRACT", 1.0, socket(occl.outputs, "AO")), 0.03, 0.4)
    n1 = g.noise(P, 1.0, detail=8.0, roughness=0.62)[0]
    g.links.new(bscale, socket(n1.node.inputs, "Scale"))
    br = g.map_range(n1, 0.42, 0.7, 0.0, 1.4)    # patchy: dirt collects in some cavities, not all of them
    m = g.math("MULTIPLY", cav, br)
    grime = g.math("MULTIPLY", g.map_range(n1, 0.5, 0.85, 0.0, 0.07), dirt)
    out = g.math("ADD", g.math("MULTIPLY", m, g.math("MULTIPLY", dirt, 1.6)), grime, clamp=True)
    g.links.new(out, socket(gout.inputs, "Dirt"))
    g.links.new(cav, socket(gout.inputs, "Cavity"))
    compat.layout(ng)
    return ng


# ----------------------------------------------------------------------------------------------- helpers

def seed_of(text):
    return zlib.crc32(str(text).encode("utf-8")) % 1000


def object_size(obj):
    """Bounding box diagonal in meters (world scale), at least 1 cm."""
    if obj is None:
        return 1.0
    d = obj.dimensions
    return max(0.01, math.sqrt(d.x * d.x + d.y * d.y + d.z * d.z))


def long_axis(obj):
    if obj is None:
        return 0
    d = obj.dimensions
    vals = [d.x, d.y, d.z]
    return vals.index(max(vals))


def _scaled(second, first, new):
    """second color moved the way first -> new moved (per channel ratio), as '#rrggbb'."""
    a, b, c = color(second), color(first), color(new)
    out = [min(1.0, a[i] * (c[i] / max(b[i], 1e-4))) for i in range(3)]
    srgb = [(12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055) for v in out]
    return "#" + "".join(f"{max(0, min(255, int(round(v * 255)))):02x}" for v in srgb)


def _lighter(c, k=0.35):
    lin = color(c)
    return tuple(v + (1.0 - v) * k for v in lin[:3]) + (1.0,)


def _texel_fade(g, texel, feature_size):
    """1 when a feature is several texels big, 0 when it is smaller than ~1.5 texels (it would alias)."""
    ratio = g.math("DIVIDE", feature_size, texel)
    return g.map_range(ratio, 1.5, 4.0)


def _planar(g, P):
    """2D coordinates for flat patterns (weave, carbon): the projection along the dominant object-space normal."""
    n = g.node("ShaderNodeTexCoord")
    N = socket(n.outputs, "Normal")
    sep = g.node("ShaderNodeSeparateXYZ")
    g.set(sep.inputs[0], N)
    ax, ay, az = (g.math("ABSOLUTE", sep.outputs[i]) for i in range(3))
    sp = g.node("ShaderNodeSeparateXYZ")
    g.set(sp.inputs[0], P)
    x, y, z = sp.outputs[0], sp.outputs[1], sp.outputs[2]
    use_x = g.math("MULTIPLY", g.math("GREATER_THAN", ax, ay), g.math("GREATER_THAN", ax, az))
    use_y = g.math("MULTIPLY", g.math("SUBTRACT", 1.0, use_x), g.math("GREATER_THAN", ay, az))
    # u: x unless the normal points along x (then y); v: z unless the normal points along z (then y)
    u = g.mix(use_x, x, y, kind="FLOAT")
    v = g.mix(g.math("MAXIMUM", use_x, use_y), y, z, kind="FLOAT")
    comb = g.node("ShaderNodeCombineXYZ")
    g.set(comb.inputs[0], u)
    g.set(comb.inputs[1], v)
    return comb.outputs[0]


def _map(g, P, rotation=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0)):
    m = g.node("ShaderNodeMapping")
    g.set(socket(m.inputs, "Vector"), P)
    socket(m.inputs, "Rotation").default_value = rotation
    socket(m.inputs, "Scale").default_value = scale
    return m.outputs[0]


def _stretch(g, P, axis, along, across):
    s = [across, across, across]
    s[axis] = along
    m = g.node("ShaderNodeMapping")
    g.set(socket(m.inputs, "Vector"), P)
    socket(m.inputs, "Scale").default_value = s
    return m.outputs[0]


# ----------------------------------------------------------------------------------------------- patterns

def _pattern(g, P, spec, base, axis, texel):
    """Surface detail per pattern -> (color socket, roughness offset socket or None, height socket in meters or None).
    base: the clean color (linear RGBA)."""
    kind = spec.get("pattern", "none")
    bump = float(spec.get("bump", 0.0))
    col = base
    rough = None
    height = None

    def h(sock, depth, feature):
        nonlocal height
        part = g.math("MULTIPLY", g.math("MULTIPLY", sock, depth * bump), _texel_fade(g, texel, feature))
        height = part if height is None else g.math("ADD", height, part)

    if kind == "scratches":
        # thin directional scratches in two directions: slightly brighter and shinier
        s1 = g.noise(_stretch(g, P, axis, 3.0, 220.0), 1.0, detail=2.0)[0]
        s2 = g.noise(_map(g, P, rotation=(0.6, 0.9, 0.3), scale=(160, 3, 160)), 1.0, detail=2.0)[0]
        lines = g.math("MAXIMUM", g.map_range(s1, 0.66, 0.70), g.map_range(s2, 0.67, 0.71))
        lines = g.math("MULTIPLY", lines, _texel_fade(g, texel, 0.0006))
        col = g.mix(g.math("MULTIPLY", lines, 0.25), col, (1, 1, 1, 1))
        rough = g.math("MULTIPLY", lines, -0.08)
        grain = g.noise(P, 900.0, detail=2.0)[0]
        h(grain, 0.00004, 0.0011)
    elif kind == "brushed":
        streak = g.noise(_stretch(g, P, axis, 2.0, 900.0), 1.0, detail=4.0, roughness=0.55)[0]
        col = g.mix(0.12, col, g.math("MULTIPLY", streak, 2.0), blend="MULTIPLY")
        rough = g.map_range(streak, 0.3, 0.7, -0.07, 0.07)
        h(streak, 0.00003, 0.0011)
    elif kind == "cast":
        f = g.noise(P, 420.0, detail=3.0, roughness=0.55)[0]
        mottle = g.noise(P, 22.0, detail=4.0)[0]
        rough = g.map_range(mottle, 0.3, 0.7, -0.05, 0.05)
        h(f, 0.00006, 0.0024)
    elif kind == "paint":
        peel = g.noise(P, 180.0, detail=2.0, roughness=0.4)[0]
        rough = g.map_range(peel, 0.35, 0.65, -0.03, 0.03)
        h(peel, 0.00005, 0.0055)
    elif kind == "stipple":
        d, _ = g.voronoi(P, 520.0)
        stip = g.map_range(d, 0.0, 0.7, 1.0, 0.0, interp="SMOOTHSTEP")
        h(stip, 0.00022, 0.0019)
        rough = g.math("MULTIPLY", stip, 0.05)
    elif kind == "plastic":
        f = g.noise(P, 260.0, detail=2.0)[0]
        h(f, 0.00002, 0.0038)
    elif kind == "rubber":
        f = g.noise(P, 650.0, detail=3.0, roughness=0.6)[0]
        f2 = g.noise(P, 70.0, detail=2.0)[0]
        h(f, 0.00008, 0.0015)
        h(f2, 0.00012, 0.014)
    elif kind == "wood":
        # a plank cut from a tree: growth rings around a pith that runs along the long axis, outside the part and
        # slightly tilted (long stripes with gentle arches), ring width varying, thin dark late-wood lines of
        # varying strength, long color streaks (board figure), soft pores along the grain
        rot = [0.0, 0.0, 0.0]
        rot[(axis + 1) % 3] = 0.04
        rot[(axis + 2) % 3] = -0.025
        loc = [0.0, 0.0, 0.0]
        loc[(axis + 1) % 3] = 0.55
        loc[(axis + 2) % 3] = 0.31
        m = g.node("ShaderNodeMapping")
        g.set(socket(m.inputs, "Vector"), P)
        socket(m.inputs, "Location").default_value = loc
        socket(m.inputs, "Rotation").default_value = rot
        cross = [1.0, 1.0, 1.0]
        cross[axis] = 0.0
        r = g.vmath("LENGTH", g.vmath("MULTIPLY", m.outputs[0], tuple(cross)))
        wob = g.noise(_stretch(g, P, axis, 1.5, 5.0), 1.0, detail=3.0)[0]
        r = g.math("ADD", r, g.math("MULTIPLY", g.math("SUBTRACT", wob, 0.5), 0.02))
        width = g.noise(_stretch(g, P, axis, 0.6, 40.0), 1.0, detail=2.0)[0]   # ring width varies
        phase = g.math("ADD", g.math("MULTIPLY", r, 170.0), g.math("MULTIPLY", width, 2.5))
        ring = g.math("FRACT", phase)
        late = g.math("MULTIPLY", g.map_range(ring, 0.55, 0.88, 0.0, 1.0, interp="SMOOTHSTEP"),
                      g.map_range(ring, 0.9, 1.0, 1.0, 0.25))
        strength = g.map_range(g.noise(_stretch(g, P, axis, 0.8, 60.0), 1.0, detail=2.0)[0], 0.3, 0.7, 0.35, 1.0)
        late = g.math("MULTIPLY", g.math("MULTIPLY", late, strength), _texel_fade(g, texel, 0.004))
        figure = g.noise(_stretch(g, P, axis, 1.5, 28.0), 1.0, detail=4.0)[0]
        pores = g.map_range(g.noise(_stretch(g, P, axis, 3.0, 1300.0), 1.0, detail=2.0)[0], 0.55, 0.8)
        pores = g.math("MULTIPLY", pores, g.math("MULTIPLY", _texel_fade(g, texel, 0.0008), 0.25))
        dark = color(spec.get("color2", "#4f2d15"))
        col = g.mix(g.math("MULTIPLY", late, 0.75), base, dark)
        col = g.mix(1.0, col, g.map_range(figure, 0.25, 0.75, 0.74, 1.2), blend="MULTIPLY")
        boards = g.noise(P, 2.2, detail=2.0)[0]   # one board lighter, the next darker
        col = g.mix(1.0, col, g.map_range(boards, 0.3, 0.7, 0.86, 1.1), blend="MULTIPLY")
        col = g.mix(pores, col, dark)
        rough = g.math("ADD", g.math("MULTIPLY", late, 0.08), g.math("MULTIPLY", pores, 0.1))
        h(g.math("SUBTRACT", 1.0, late), 0.00005, 0.0024)
        h(g.math("SUBTRACT", 1.0, pores), 0.00003, 0.0008)
    elif kind == "leather":
        d, _ = g.voronoi(P, 230.0, feature="DISTANCE_TO_EDGE")
        crease = g.map_range(d, 0.0, 0.16, 1.0, 0.0, interp="SMOOTHSTEP")
        col = g.mix(g.math("MULTIPLY", crease, 0.35), col, (0, 0, 0, 1), blend="MIX")
        rough = g.math("MULTIPLY", crease, 0.1)
        h(g.math("SUBTRACT", 1.0, crease), 0.00018, 0.0043)
    elif kind == "weave":
        uv = _planar(g, P)
        wx, _ = g.wave(uv, 380.0, kind="BANDS", direction="X", profile="SIN", distortion=0.6, detail=1.0)
        wy, _ = g.wave(uv, 380.0, kind="BANDS", direction="Y", profile="SIN", distortion=0.6, detail=1.0)
        th = g.math("MAXIMUM", wx, wy)
        col = g.mix(0.25, col, g.math("MULTIPLY", g.math("ADD", wx, 0.6), 1.0), blend="MULTIPLY")
        h(th, 0.0002, 0.0017)
    elif kind == "carbon":
        uv = _planar(g, P)
        rot = g.node("ShaderNodeMapping")
        g.set(socket(rot.inputs, "Vector"), uv)
        socket(rot.inputs, "Rotation").default_value = (0, 0, math.radians(45))
        a, _ = g.wave(rot.outputs[0], 160.0, kind="BANDS", direction="X", profile="TRI")
        b, _ = g.wave(rot.outputs[0], 160.0, kind="BANDS", direction="Y", profile="TRI")
        chk = g.math("GREATER_THAN", g.math("MULTIPLY", g.math("SUBTRACT", a, 0.5), g.math("SUBTRACT", b, 0.5)), 0.0)
        col = g.mix(g.math("MULTIPLY", chk, _texel_fade(g, texel, 0.004)), base,
                    color(spec.get("color2", "#34373b")))
        h(chk, 0.00005, 0.004)
    elif kind == "stone":
        d, vc = g.voronoi(P, 7.0, feature="F1")
        n1 = g.noise(P, 18.0, detail=8.0, roughness=0.6)[0]
        mixf = g.math("ADD", g.math("MULTIPLY", g.to_bw(vc), 0.6), g.math("MULTIPLY", n1, 0.6), clamp=True)
        col = g.mix(g.map_range(mixf, 0.2, 0.9), base, color(spec.get("color2", "#5e5a52")))
        e, _ = g.voronoi(P, 7.0, feature="DISTANCE_TO_EDGE")
        crack = g.map_range(e, 0.0, 0.035, 1.0, 0.0)
        col = g.mix(g.math("MULTIPLY", crack, 0.5), col, (0.02, 0.02, 0.02, 1))
        h(n1, 0.0025, 0.05)
        h(g.math("SUBTRACT", 1.0, crack), 0.0015, 0.02)
        h(g.noise(P, 160.0, detail=3.0)[0], 0.0002, 0.006)
    elif kind == "concrete":
        n1 = g.noise(P, 9.0, detail=6.0, roughness=0.6)[0]
        col = g.mix(0.35, col, g.math("MULTIPLY", n1, 2.0), blend="MULTIPLY")
        d, _ = g.voronoi(P, 140.0)
        pits = g.map_range(d, 0.0, 0.18, 1.0, 0.0)
        col = g.mix(g.math("MULTIPLY", pits, 0.4), col, (0.03, 0.03, 0.03, 1))
        h(g.math("SUBTRACT", 1.0, pits), 0.0004, 0.007)
        h(g.noise(P, 300.0, detail=3.0)[0], 0.00015, 0.003)
    elif kind == "skin":
        d, _ = g.voronoi(P, 900.0)
        h(g.map_range(d, 0.0, 0.5, 0.0, 1.0), 0.00005, 0.0011)
        red = g.noise(P, 12.0, detail=3.0)[0]
        col = g.mix(g.map_range(red, 0.4, 0.7, 0.0, 0.3), col, color("#c4705e"))
    return col, rough, height


# ----------------------------------------------------------------------------------------------- the builder

def params_of(mat):
    try:
        return json.loads(mat.get("nighty", "{}"))
    except (TypeError, ValueError):
        return {}


def build(mat, kind, obj=None, wear=0.3, dirt=0.25, tint=None, seed=None, cc0_set=None, roughness=None,
          asset_size=None, axis=None, force_tint=False, glow=None):
    """(Re)builds `mat` as the smart material `kind` (a library key) in place. Returns the stored parameters.

    wear 0..1: edge wear amount; dirt 0..1: cavity dirt; tint: a color for paintable materials ('#rrggbb');
    cc0_set: {'color': path, 'roughness': path, 'height': path, 'normal': path} of a downloaded CC0 texture set,
    applied with box projection (no UVs needed); roughness: optional override of the clean roughness;
    asset_size: the whole asset's size in meters (wear width and dirt reach follow it, not the part's size).
    axis: 0 / 1 / 2 the grain / pattern direction (default the part's long axis); force_tint: use tint as the
    base color even for natural materials (a wood or leather tone; metals stay real); glow: emission strength."""
    key = library.resolve(kind)
    if key is None:
        raise ValueError(f"unknown material {kind!r}")
    spec = dict(library.MATERIALS[key])
    if tint and (spec.get("paintable") or (force_tint and not spec["metallic"])):
        if force_tint and spec.get("color2"):   # keep the pattern's second tone in step with the new base
            spec["color2"] = _scaled(spec["color2"], spec["color"], tint)
        spec["color"] = tint
    if glow is not None and spec.get("emission"):
        spec["emission"] = float(glow)
    if roughness is not None:
        spec["rough"] = max(0.0, min(1.0, float(roughness)))
    wear = max(0.0, min(1.0, float(wear))) if spec.get("wearable", True) else 0.0
    dirt = max(0.0, min(1.0, float(dirt)))
    size = asset_size or object_size(obj)
    axis = long_axis(obj) if axis is None else int(axis)
    if seed is None:
        seed = seed_of((obj.name if obj else "") + key)

    tree = compat.ensure_nodes(mat)
    tree.nodes.clear()
    g = Graph(tree)
    out = g.node("ShaderNodeOutputMaterial")
    bsdf = g.node("ShaderNodeBsdfPrincipled")
    g.links.new(bsdf.outputs[0], socket(out.inputs, "Surface"))

    texel_n = g.node("ShaderNodeValue", label=TEXEL_NODE)
    texel_n.name = TEXEL_NODE
    texel_n.outputs[0].default_value = 0.0003
    texel = texel_n.outputs[0]

    off = ((seed * 7.31) % 97.0, (seed * 3.17) % 89.0, (seed * 5.73) % 83.0)
    P = g.coords("Object", offset=off)

    # --- clean layer
    base = color(spec["color"])
    clean_col, rough_off, height = _pattern(g, P, spec, base, axis, texel)
    macro = g.noise(P, 4.0, detail=6.0, roughness=0.6)[0]
    clean_col = g.mix(0.08, clean_col, g.math("MULTIPLY", macro, 2.0), blend="MULTIPLY")
    rmac = g.noise(P, 7.0, detail=6.0, roughness=0.6)[0]
    r = g.map_range(rmac, 0.25, 0.75, -spec.get("rough_var", 0.1), spec.get("rough_var", 0.1))
    clean_rough = g.math("ADD", spec["rough"], r)
    if spec["metallic"] or spec["rough"] < 0.5:
        # smudges and handling marks: patches a little rougher, the kind of breakup light catches
        sm = g.noise(P, 30.0, detail=8.0, roughness=0.7)[0]
        clean_rough = g.math("ADD", clean_rough, g.map_range(sm, 0.55, 0.75, 0.0, 0.06))
    if rough_off is not None:
        clean_rough = g.math("ADD", clean_rough, rough_off)

    if cc0_set:
        if tint and spec.get("paintable"):   # the person's color wins over the photo's
            cc0_set = {k: v for k, v in cc0_set.items() if k != "color"}
        clean_col, clean_rough, h2 = _cc0_layer(g, P, cc0_set, clean_col, clean_rough, size)
        if h2 is not None:
            height = h2 if height is None else g.math("ADD", height, h2)

    # --- masks from real geometry
    scale = max(0.3, min(3.0, size)) ** 0.5
    edge_n = g.group(edge_group())
    g.set(socket(edge_n.inputs, "Vector"), P)
    socket(edge_n.inputs, "Radius").default_value = (0.0022 + 0.0042 * wear) * scale
    socket(edge_n.inputs, "Breakup Scale").default_value = 26.0 / scale
    socket(edge_n.inputs, "Breakup").default_value = float(spec.get("breakup", 1.0 if spec.get("chip_depth") else
                                                                         (0.7 if spec["metallic"] else 0.8)))
    # wear 0 -> nothing, 1 -> most edges; a narrow threshold keeps the chip borders sharp
    if wear > 0.001:
        t = 1.02 - 0.85 * wear
        wear_m = g.map_range(socket(edge_n.outputs, "Mask"), t - 0.05, t + 0.05)
        wear_m.node.label = "NB Wear Threshold"
    else:
        wear_m = g.value(0.0, "No wear")

    dirt_n = g.group(cavity_group())
    g.set(socket(dirt_n.inputs, "Vector"), P)
    socket(dirt_n.inputs, "Distance").default_value = 0.035 * max(0.2, min(5.0, size)) ** 0.7
    socket(dirt_n.inputs, "Dirt").default_value = dirt
    socket(dirt_n.inputs, "Breakup Scale").default_value = 7.0 / scale
    dirt_m = socket(dirt_n.outputs, "Dirt")

    # --- worn layer (what the edges show)
    worn = spec["worn"]
    worn_col = _lighter(spec["color"]) if worn["color"] == "lighter" else color(worn["color"])
    wn = g.noise(P, 60.0, detail=4.0)[0]
    worn_col = g.mix(0.25, worn_col, g.math("MULTIPLY", wn, 2.0), blend="MULTIPLY")
    if spec.get("chip_depth") and wear > 0.001:
        # a darker rim of primer / thinned paint around each chip
        rim = g.math("MULTIPLY", g.map_range(socket(edge_n.outputs, "Mask"), t - 0.2, t - 0.05),
                     g.math("SUBTRACT", 1.0, wear_m))
        clean_col = g.mix(g.math("MULTIPLY", rim, 0.55), clean_col,
                          g.mix(0.6, clean_col, color(spec.get("primer", "#4a4640")), blend="MULTIPLY"))
    col = g.mix(wear_m, clean_col, worn_col)
    rough = g.mix(wear_m, clean_rough, worn["rough"], kind="FLOAT")
    metal_clean = 1.0 if spec["metallic"] else 0.0
    metal = metal_clean
    if worn["metallic"] != spec["metallic"]:
        step = g.math("GREATER_THAN", wear_m, 0.5)
        metal = g.mix(step, metal_clean, float(worn["metallic"]), kind="FLOAT")

    # --- dirt / rust in cavities
    d = spec["dirt"]
    dn = g.noise(P, 45.0, detail=5.0)[0]
    dirt_col = g.mix(0.3, color(d["color"]), g.math("MULTIPLY", dn, 2.0), blend="MULTIPLY")
    if d.get("rust"):
        col = g.mix(g.map_range(dirt_m, 0.35, 0.55), col, dirt_col)
        rough = g.mix(g.map_range(dirt_m, 0.35, 0.55), rough, d["rough"], kind="FLOAT")
        step = g.math("GREATER_THAN", dirt_m, 0.45)
        metal = g.mix(step, metal, float(d.get("metallic", 0)), kind="FLOAT")
    else:
        col = g.mix(g.math("MULTIPLY", dirt_m, 0.8), col, g.mix(0.7, col, dirt_col, blend="MULTIPLY"))
        rough = g.mix(g.math("MULTIPLY", dirt_m, 0.8), rough, d["rough"], kind="FLOAT")

    # --- chipped paint is a step down to the bare layer
    if spec.get("chip_depth") and wear > 0:
        chip = g.math("MULTIPLY", wear_m, -0.00012 * spec["chip_depth"])
        height = chip if height is None else g.math("ADD", height, chip)

    # --- normal: rounded edges (bevel normal) + surface detail
    normal = g.bevel((0.0009 + 0.0006 * scale), samples=6)
    if height is not None:
        normal = g.bump(height, 1.0, 1.0, normal=normal)
    g.set(socket(bsdf.inputs, "Base Color"), col)
    g.set(socket(bsdf.inputs, "Roughness"), g.math("ADD", rough, 0.0, clamp=True))
    g.set(socket(bsdf.inputs, "Metallic"), metal)
    g.set(socket(bsdf.inputs, "Normal"), normal)

    # --- extras
    if spec.get("transmission"):
        socket(bsdf.inputs, "Transmission Weight", "Transmission").default_value = spec["transmission"]
    if spec.get("ior"):
        socket(bsdf.inputs, "IOR").default_value = spec["ior"]
    if spec.get("alpha") is not None:
        socket(bsdf.inputs, "Alpha").default_value = spec["alpha"]
        for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
            try:
                setattr(mat, attr, val)
            except (AttributeError, TypeError):
                pass
    if spec.get("emission"):
        socket(bsdf.inputs, "Emission Color").default_value = color(spec["color"])
        socket(bsdf.inputs, "Emission Strength").default_value = spec["emission"]
        g.set(socket(bsdf.inputs, "Base Color"), tuple(v * 0.35 for v in color(spec["color"])[:3]) + (1.0,))
    if spec.get("coat"):
        socket(bsdf.inputs, "Coat Weight").default_value = spec["coat"]
        socket(bsdf.inputs, "Coat Roughness").default_value = 0.05
    if spec.get("sheen"):
        socket(bsdf.inputs, "Sheen Weight").default_value = spec["sheen"]
    if spec.get("subsurface"):
        socket(bsdf.inputs, "Subsurface Weight").default_value = spec["subsurface"]
    if spec.get("anisotropic"):
        socket(bsdf.inputs, "Anisotropic").default_value = spec["anisotropic"]

    compat.layout(tree)
    # the Solid view shows something close
    lin = color(spec["color"])
    mat.diffuse_color = lin
    mat.metallic = metal_clean
    mat.roughness = spec["rough"]
    params = {"v": VERSION, "kind": key, "style": "pbr", "wear": round(wear, 3), "dirt": round(dirt, 3),
              "tint": tint if spec.get("paintable") else None, "seed": seed, "metallic": spec["metallic"],
              "cc0": bool(cc0_set), "roughness": roughness}
    mat["nighty"] = json.dumps(params)
    return params


def _cc0_layer(g, P, files, col, rough, size):
    """A downloaded CC0 set (color / roughness / height), box-projected in object space. Metallic never comes
    from it. Tile size: ~1 m real-world per texture repeat (Poly Haven sets are made at about that scale)."""
    vec = g.vmath("SCALE", P, scale=1.0)
    out_col, out_rough, height = col, rough, None
    if files.get("color"):
        img = bpy.data.images.load(files["color"], check_existing=True)
        n = g.image(img, vec, projection="BOX", blend=0.25)
        out_col = n.outputs[0]
    if files.get("roughness"):
        img = bpy.data.images.load(files["roughness"], check_existing=True)
        img.colorspace_settings.name = "Non-Color"
        n = g.image(img, vec, projection="BOX", blend=0.25)
        out_rough = g.to_bw(n.outputs[0])
    if files.get("height"):
        img = bpy.data.images.load(files["height"], check_existing=True)
        img.colorspace_settings.name = "Non-Color"
        n = g.image(img, vec, projection="BOX", blend=0.25)
        height = g.math("MULTIPLY", g.to_bw(n.outputs[0]), 0.002)
    return out_col, out_rough, height
