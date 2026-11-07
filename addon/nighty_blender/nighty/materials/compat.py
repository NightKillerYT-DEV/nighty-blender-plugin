# SPDX-License-Identifier: GPL-3.0-or-later
"""Node helpers that behave the same on Blender 4.2 LTS up to 5.x.

Socket names drift between versions (4.2 says "Fac", 5.x says "Factor"), `Material.use_nodes` is going away, and
nodes are looked up by type (their names are localized). Everything in materials/, bake/ and export/ builds node
trees through this module so those differences live in one place.
"""

import warnings

import bpy

VERSION = bpy.app.version


def new_material(name):
    """A new material with a node tree (Principled BSDF + Material Output)."""
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None or VERSION < (5, 0, 0):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            mat.use_nodes = True
    return mat


def ensure_nodes(mat):
    if mat.node_tree is None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            mat.use_nodes = True
    return mat.node_tree


def socket(sockets, *names, kind=None):
    """The first socket whose identifier or name is one of `names` (several names cover renames).
    kind: a socket type ('VALUE', 'RGBA', 'VECTOR', 'SHADER') to pick among same-named sockets (the Mix node)."""
    for name in names:
        for s in sockets:
            if (s.identifier == name or s.name == name) and (kind is None or s.type == kind):
                return s
    raise KeyError(f"no socket {names} among {[s.identifier for s in sockets]}")


def find(tree, node_type):
    """Nodes of a type ('BSDF_PRINCIPLED', 'OUTPUT_MATERIAL', ...)."""
    return [n for n in tree.nodes if n.type == node_type]


def output_node(tree):
    """The active material output (or the first one)."""
    outs = find(tree, "OUTPUT_MATERIAL")
    for n in outs:
        if getattr(n, "is_active_output", False):
            return n
    return outs[0] if outs else None


def principled_of(mat):
    """The Principled BSDF that feeds the material output directly (None if the tree is something else)."""
    tree = mat.node_tree
    out = output_node(tree) if tree else None
    if out is None:
        return None
    surf = socket(out.inputs, "Surface")
    if surf.is_linked and surf.links[0].from_node.type == "BSDF_PRINCIPLED":
        return surf.links[0].from_node
    found = find(tree, "BSDF_PRINCIPLED")
    return found[0] if len(found) == 1 else None


def srgb_to_linear(c):
    c = max(0.0, min(1.0, float(c)))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def color(value):
    """'#rrggbb', (r, g, b) in sRGB 0..1, or a gray number -> linear RGBA for node inputs."""
    if isinstance(value, str):
        h = value.lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        rgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    elif isinstance(value, (int, float)):
        rgb = [float(value)] * 3
    else:
        rgb = [float(v) for v in list(value)[:3]]
    return tuple(srgb_to_linear(v) for v in rgb) + (1.0,)


class Graph:
    """A tiny builder for shader node trees: values or sockets go in, sockets come out.

        g = Graph(tree)
        n = g.noise(g.coords(), scale=40)          # -> (factor, color) sockets
        r = g.map_range(n[0], 0.4, 0.6)            # -> socket
        g.set(principled.inputs["Roughness"], r)   # link or set a value
    """

    def __init__(self, tree):
        self.tree = tree
        self.nodes = tree.nodes
        self.links = tree.links

    # -- plumbing
    def node(self, bl_idname, label=None, **props):
        n = self.nodes.new(bl_idname)
        if label:
            n.label = label
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def set(self, inp, value):
        """Link a socket into `inp`, or set its value (numbers, colors, vectors)."""
        if isinstance(value, bpy.types.NodeSocket):
            self.links.new(value, inp)
            return
        if inp.type == "RGBA":
            if isinstance(value, (int, float)):
                value = (value, value, value, 1.0)
            value = tuple(value)
            if len(value) == 3:
                value = value + (1.0,)
        elif inp.type == "VECTOR" and isinstance(value, (int, float)):
            value = (value, value, value)
        inp.default_value = value

    def value(self, v, label=None):
        n = self.node("ShaderNodeValue", label)
        n.outputs[0].default_value = v
        return n.outputs[0]

    def rgb(self, c, label=None):
        n = self.node("ShaderNodeRGB", label)
        n.outputs[0].default_value = c if len(c) == 4 else tuple(c) + (1.0,)
        return n.outputs[0]

    # -- coordinates
    def coords(self, kind="Object", obj=None, offset=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0), rotation=(0.0, 0.0, 0.0)):
        """Texture coordinates (Object = 3D meters in the object's space: no UVs needed, no seams)."""
        tc = self.node("ShaderNodeTexCoord")
        if obj is not None:
            tc.object = obj
        out = socket(tc.outputs, kind)
        if tuple(offset) == (0, 0, 0) and tuple(scale) == (1, 1, 1) and tuple(rotation) == (0, 0, 0):
            return out
        m = self.node("ShaderNodeMapping")
        self.links.new(out, socket(m.inputs, "Vector"))
        socket(m.inputs, "Location").default_value = offset
        socket(m.inputs, "Scale").default_value = scale
        socket(m.inputs, "Rotation").default_value = rotation
        return m.outputs[0]

    def geometry(self, name):
        g = self.node("ShaderNodeNewGeometry")
        return socket(g.outputs, name)

    # -- math
    def math(self, op, a, b=None, c=None, clamp=False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.set(n.inputs[0], a)
        if b is not None:
            self.set(n.inputs[1], b)
        if c is not None:
            self.set(n.inputs[2], c)
        return n.outputs[0]

    def vmath(self, op, a, b=None, scale=None):
        n = self.node("ShaderNodeVectorMath", operation=op)
        self.set(n.inputs[0], a)
        if b is not None:
            self.set(n.inputs[1], b)
        if scale is not None:
            self.set(socket(n.inputs, "Scale"), scale)
        return socket(n.outputs, "Value") if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else n.outputs[0]

    def map_range(self, v, from_min, from_max, to_min=0.0, to_max=1.0, interp="LINEAR", clamp=True):
        n = self.node("ShaderNodeMapRange", interpolation_type=interp, clamp=clamp)
        self.set(socket(n.inputs, "Value"), v)
        self.set(socket(n.inputs, "From Min", kind="VALUE"), from_min)
        self.set(socket(n.inputs, "From Max", kind="VALUE"), from_max)
        self.set(socket(n.inputs, "To Min", kind="VALUE"), to_min)
        self.set(socket(n.inputs, "To Max", kind="VALUE"), to_max)
        return socket(n.outputs, "Result")

    def mix(self, fac, a, b, kind="RGBA", blend="MIX", clamp=True):
        """Mix node: kind 'RGBA' (colors) or 'FLOAT'."""
        n = self.node("ShaderNodeMix", data_type=kind, blend_type=blend, clamp_result=clamp)
        stype = "RGBA" if kind == "RGBA" else "VALUE"
        self.set(socket(n.inputs, "Factor", kind="VALUE"), fac)
        self.set(socket(n.inputs, "A", kind=stype), a)
        self.set(socket(n.inputs, "B", kind=stype), b)
        return socket(n.outputs, "Result", kind=stype)

    def ramp(self, fac, stops, interp="LINEAR"):
        """Color Ramp: stops = [(position, color_rgba), ...] -> color socket."""
        n = self.node("ShaderNodeValToRGB")
        cr = n.color_ramp
        cr.interpolation = interp
        while len(cr.elements) > 1:
            cr.elements.remove(cr.elements[-1])
        cr.elements[0].position = stops[0][0]
        cr.elements[0].color = stops[0][1]
        for pos, col in stops[1:]:
            e = cr.elements.new(pos)
            e.color = col
        self.set(n.inputs[0], fac)
        return n.outputs[0]

    def to_bw(self, col):
        n = self.node("ShaderNodeRGBToBW")
        self.set(n.inputs[0], col)
        return n.outputs[0]

    # -- textures
    def noise(self, vec, scale, detail=4.0, roughness=0.5, distortion=0.0, lacunarity=2.0, dims="3D"):
        n = self.node("ShaderNodeTexNoise", noise_dimensions=dims)
        self.set(socket(n.inputs, "Vector"), vec)
        socket(n.inputs, "Scale").default_value = scale
        socket(n.inputs, "Detail").default_value = detail
        socket(n.inputs, "Roughness").default_value = roughness
        socket(n.inputs, "Distortion").default_value = distortion
        socket(n.inputs, "Lacunarity").default_value = lacunarity
        return n.outputs[0], n.outputs[1]

    def voronoi(self, vec, scale, feature="F1", distance="EUCLIDEAN", randomness=1.0):
        n = self.node("ShaderNodeTexVoronoi", feature=feature, distance=distance)
        self.set(socket(n.inputs, "Vector"), vec)
        socket(n.inputs, "Scale").default_value = scale
        socket(n.inputs, "Randomness").default_value = randomness
        return socket(n.outputs, "Distance"), socket(n.outputs, "Color")

    def wave(self, vec, scale, distortion=0.0, detail=2.0, kind="BANDS", direction="X", profile="SIN", detail_scale=1.0):
        n = self.node("ShaderNodeTexWave", wave_type=kind, wave_profile=profile)
        if kind == "BANDS":
            n.bands_direction = direction
        else:
            n.rings_direction = direction
        self.set(socket(n.inputs, "Vector"), vec)
        socket(n.inputs, "Scale").default_value = scale
        socket(n.inputs, "Distortion").default_value = distortion
        socket(n.inputs, "Detail").default_value = detail
        socket(n.inputs, "Detail Scale").default_value = detail_scale
        return n.outputs[1], n.outputs[0]  # factor, color

    def image(self, img, vec=None, projection="FLAT", blend=0.2, extension="REPEAT", interpolation="Linear"):
        n = self.node("ShaderNodeTexImage", image=img, projection=projection, extension=extension,
                      interpolation=interpolation)
        n.projection_blend = blend
        if vec is not None:
            self.set(socket(n.inputs, "Vector"), vec)
        return n

    def bump(self, height, strength, distance, normal=None):
        n = self.node("ShaderNodeBump")
        self.set(socket(n.inputs, "Height"), height)
        socket(n.inputs, "Strength").default_value = strength
        socket(n.inputs, "Distance").default_value = distance
        if normal is not None:
            self.set(socket(n.inputs, "Normal"), normal)
        return n.outputs[0]

    def bevel(self, radius, samples=8):
        n = self.node("ShaderNodeBevel", samples=samples)
        self.set(socket(n.inputs, "Radius"), radius)
        return n.outputs[0]

    def ao(self, distance, samples=16, only_local=True, inside=False):
        n = self.node("ShaderNodeAmbientOcclusion", samples=samples, only_local=only_local, inside=inside)
        self.set(socket(n.inputs, "Distance"), distance)
        return socket(n.outputs, "AO")

    def group(self, tree):
        n = self.node("ShaderNodeGroup")
        n.node_tree = tree
        return n


def layout(tree, dx=230, dy=190):
    """Lays nodes out in columns by their distance from the output, so a person can read the tree."""
    nodes = list(tree.nodes)
    consumers = {n: [] for n in nodes}
    for link in tree.links:
        if link.from_node in consumers:
            consumers[link.from_node].append(link.to_node)
    depth = {}

    def d(n, seen=()):
        if n in depth:
            return depth[n]
        if n in seen:
            return 0
        outs = [c for c in consumers[n] if c is not n]
        depth[n] = 0 if not outs else 1 + max(d(c, seen + (n,)) for c in outs)
        return depth[n]

    columns = {}
    for n in nodes:
        if n.type == "FRAME":
            continue
        columns.setdefault(d(n), []).append(n)
    for col, items in columns.items():
        for i, n in enumerate(items):
            n.location = (-col * dx, (len(items) / 2 - i) * dy)


def new_group(name, inputs, outputs):
    """A shader node group with interface sockets: inputs/outputs = [(name, 'NodeSocketFloat', default), ...]."""
    ng = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for nm, kind, default in inputs:
        s = ng.interface.new_socket(nm, in_out="INPUT", socket_type=kind)
        if default is not None:
            s.default_value = default
    for nm, kind, _ in outputs:
        ng.interface.new_socket(nm, in_out="OUTPUT", socket_type=kind)
    gin = ng.nodes.new("NodeGroupInput")
    gout = ng.nodes.new("NodeGroupOutput")
    return ng, gin, gout
