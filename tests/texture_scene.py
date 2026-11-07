# SPDX-License-Identifier: GPL-3.0-or-later
"""Test assets made from simple parts (a rifle and a crate) for the texturing tests and demo renders.

Real bevels (3 segments), smooth shading with sharp edges by angle, enough cylinder sides, per-part UVs (the bake
packs them into one atlas). No dependency on the nighty helper library (another helper builds that)."""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _finish(bm, name, location=(0, 0, 0), rotation=(0, 0, 0), sharp_deg=32.0, unwrap=True):
    me = bpy.data.meshes.new(name)
    for f in bm.faces:
        f.smooth = True
    for e in bm.edges:
        if e.is_manifold and len(e.link_faces) == 2:
            a = e.link_faces[0].normal.angle(e.link_faces[1].normal, 0.0)
            e.smooth = a < math.radians(sharp_deg)
        else:
            e.smooth = False
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = rotation
    if unwrap:
        uv_unwrap(obj)
    return obj


def uv_unwrap(obj, angle=66.0, margin=0.01):
    vl = bpy.context.view_layer
    for o in vl.objects:
        if o is not None:
            o.select_set(False)
    obj.select_set(True)
    vl.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(angle), island_margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)


def box(name, size, bevel=0.004, segments=3, location=(0, 0, 0), rotation=(0, 0, 0), taper=None):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    if taper:  # shrink the top face a little (magazines, grips)
        for v in bm.verts:
            if v.co.z > 0:
                v.co.x *= taper
    if bevel > 0:
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=bevel, segments=segments, profile=0.5, affect="EDGES",
                        clamp_overlap=True)
    return _finish(bm, name, location, rotation)


def cylinder(name, radius, depth, sides=None, bevel=0.002, segments=3, location=(0, 0, 0), rotation=(0, 0, 0)):
    if sides is None:  # enough sides for the size: never the blocky 8
        sides = max(24, min(96, int(2 * math.pi * radius / 0.004)))
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=sides, radius1=radius, radius2=radius,
                          depth=depth)
    if bevel > 0:
        caps = [e for e in bm.edges if len(e.link_faces) == 2 and
                abs(e.link_faces[0].normal.dot(e.link_faces[1].normal)) < 0.5]
        bmesh.ops.bevel(bm, geom=caps, offset=bevel, segments=segments, profile=0.5, affect="EDGES",
                        clamp_overlap=True)
    return _finish(bm, name, location, rotation)


def make_gun():
    """A rifle about 0.9 m long along +X (front view looks at its left side)."""
    rx = (0, math.radians(90), 0)
    parts = {
        "Receiver": box("Receiver", (0.30, 0.05, 0.085), bevel=0.004, location=(0.0, 0, 0.0)),
        "Barrel": cylinder("Barrel", 0.0115, 0.40, location=(0.33, 0, 0.018), rotation=rx),
        "Muzzle": cylinder("Muzzle", 0.018, 0.06, location=(0.54, 0, 0.018), rotation=rx, bevel=0.003),
        "Handguard": box("Handguard", (0.22, 0.056, 0.062), bevel=0.006, location=(0.255, 0, 0.012)),
        "Grip": box("Grip", (0.042, 0.034, 0.13), bevel=0.006, location=(-0.06, 0, -0.095),
                    rotation=(0, math.radians(-18), 0), taper=0.92),
        "Magazine": box("Magazine", (0.05, 0.028, 0.15), bevel=0.004, location=(0.06, 0, -0.105),
                        rotation=(0, math.radians(8), 0)),
        "Stock": box("Stock", (0.24, 0.04, 0.10), bevel=0.008, location=(-0.27, 0, -0.012)),
        "Scope": cylinder("Scope", 0.021, 0.17, location=(0.02, 0, 0.078), rotation=rx, bevel=0.003),
        "ScopeMount": box("ScopeMount", (0.10, 0.03, 0.025), bevel=0.003, location=(0.02, 0, 0.05)),
        "Lens": cylinder("Lens", 0.017, 0.004, location=(0.106, 0, 0.078), rotation=rx, bevel=0.0008, segments=2),
        "Light": cylinder("Light", 0.006, 0.006, location=(0.33, -0.03, 0.012), rotation=(math.radians(90), 0, 0),
                          bevel=0.0008, segments=2),
    }
    return parts


GUN_MATERIALS = {
    "Receiver": "gunmetal", "Barrel": "steel", "Muzzle": "gunmetal", "Handguard": "polymer", "Grip": "rubber",
    "Magazine": {"material": "painted_metal", "color": "#4d5a35"}, "Stock": "wood", "Scope": "anodized_aluminum",
    "ScopeMount": "aluminum", "Lens": "glass", "Light": {"material": "emissive", "color": "#ff4a2a"},
}


def make_crate():
    """A wooden crate with painted metal corners and a rubber handle, about 0.8 m."""
    parts = {"CrateBody": box("CrateBody", (0.8, 0.6, 0.6), bevel=0.012, location=(0, 0, 0.3))}
    for i, (sx, sy) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1))):
        n = f"CrateCorner{i}"
        parts[n] = box(n, (0.09, 0.09, 0.62), bevel=0.006, location=(sx * 0.37, sy * 0.27, 0.3))
    parts["CrateHandle"] = box("CrateHandle", (0.2, 0.04, 0.05), bevel=0.012, location=(0, -0.31, 0.45))
    return parts


CRATE_MATERIALS = {"CrateBody": "wood", "CrateCorner0": "painted_metal", "CrateCorner1": "painted_metal",
                   "CrateCorner2": "painted_metal", "CrateCorner3": "painted_metal", "CrateHandle": "rubber"}


def demo_render(path, objects, size=(960, 640), samples=64, view="3/4", engine="CYCLES", hdri="studio.exr",
                lens=60, device="CPU"):
    """A quick look-dev render (Cycles, a bundled studio HDRI) framed on `objects`."""
    import os
    sc = bpy.context.scene
    sc.render.engine = engine
    sc.cycles.samples = samples
    sc.cycles.device = device
    try:
        sc.cycles.use_denoising = True
    except AttributeError:
        pass
    sc.render.resolution_x, sc.render.resolution_y = size
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "AgX" if "AgX" in [i.identifier for i in
                                                        sc.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"
    world = sc.world or bpy.data.worlds.new("World")
    sc.world = world
    from nighty_blender.nighty.materials import compat
    tree = compat.ensure_nodes(world) if hasattr(world, "node_tree") else None
    tree.nodes.clear()
    env = tree.nodes.new("ShaderNodeTexEnvironment")
    hpath = os.path.join(bpy.utils.system_resource("DATAFILES"), "studiolights", "world", hdri)
    env.image = bpy.data.images.load(hpath, check_existing=True)
    bg = tree.nodes.new("ShaderNodeBackground")
    bg.inputs[1].default_value = 0.9
    plain = tree.nodes.new("ShaderNodeBackground")   # the camera sees a calm gray, the model sees the HDRI
    plain.inputs[0].default_value = (0.18, 0.19, 0.2, 1.0)
    path_n = tree.nodes.new("ShaderNodeLightPath")
    mix = tree.nodes.new("ShaderNodeMixShader")
    out = tree.nodes.new("ShaderNodeOutputWorld")
    tree.links.new(env.outputs[0], bg.inputs[0])
    tree.links.new(path_n.outputs["Is Camera Ray"], mix.inputs[0])
    tree.links.new(bg.outputs[0], mix.inputs[1])
    tree.links.new(plain.outputs[0], mix.inputs[2])
    tree.links.new(mix.outputs[0], out.inputs[0])
    # frame
    import mathutils
    pts = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    center = (lo + hi) / 2
    radius = (hi - lo).length / 2
    cam_data = bpy.data.cameras.new("DemoCam")
    cam_data.lens = lens
    cam = bpy.data.objects.new("DemoCam", cam_data)
    sc.collection.objects.link(cam)
    dirs = {"3/4": Vector((0.55, -1.0, 0.45)), "front": Vector((0, -1, 0.05)), "back34": Vector((-0.6, 1.0, 0.4)),
            "top": Vector((0.01, -0.2, 1.0)), "close": Vector((0.35, -1.0, 0.3))}
    d = dirs.get(view, dirs["3/4"]).normalized()
    fov = 2 * math.atan(36 / 2 / lens)
    dist = radius / math.sin(fov / 2) * (1.05 if view != "close" else 0.45)
    cam.location = center + d * dist
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    # a soft key light from the upper left of the camera
    key_data = bpy.data.lights.new("DemoKey", "AREA")
    key_data.energy = 60.0 * radius * radius / 0.2
    key_data.size = radius * 1.5
    key = bpy.data.objects.new("DemoKey", key_data)
    sc.collection.objects.link(key)
    kd = (d + Vector((-0.8, -0.3, 0.9))).normalized()
    key.location = center + kd * radius * 3
    key.rotation_euler = (-kd).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam)
    bpy.data.objects.remove(key)
    return path
