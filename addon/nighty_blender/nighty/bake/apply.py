# SPDX-License-Identifier: GPL-3.0-or-later
"""Brings a finished bake into the person's file (main thread, quick): the shared atlas UVs, and one clean
Principled material built only from the baked maps. The procedural source materials are kept (fake user) and
remembered on each object, so the next bake starts from them again and assign_materials can rebuild them."""

import json
import os

import bpy
import numpy as np

from ..materials import compat
from ..materials.compat import Graph, socket
from . import maps

GLTF_GROUP = "glTF Material Output"
SOURCES = "nighty_source_materials"


def gltf_output_group():
    """The node group Blender's glTF exporter reads ambient occlusion from (it matches it by name)."""
    ng = bpy.data.node_groups.get(GLTF_GROUP) or bpy.data.node_groups.get("glTF Settings")
    if ng is not None:
        return ng
    ng, _, _ = compat.new_group(GLTF_GROUP, [("Occlusion", "NodeSocketFloat", 1.0)], [])
    return ng


def load_image(path, colorspace):
    img = bpy.data.images.load(path, check_existing=True)
    img.reload()
    try:
        img.colorspace_settings.name = colorspace
    except TypeError:
        pass
    return img


def baked_material(manifest, folder, name=None):
    """A clean material from the maps in `folder` (bake.json's names). Rebuilt in place on every bake."""
    mname = f"NB Baked · {name or manifest['name']}"
    mat = bpy.data.materials.get(mname) or compat.new_material(mname)
    tree = compat.ensure_nodes(mat)
    tree.nodes.clear()
    g = Graph(tree)
    out = g.node("ShaderNodeOutputMaterial")
    bsdf = g.node("ShaderNodeBsdfPrincipled")
    g.links.new(bsdf.outputs[0], socket(out.inputs, "Surface"))
    layer = manifest.get("uv_layer") or ""
    uvn = g.node("ShaderNodeUVMap")
    uvn.uv_map = layer
    files = manifest["maps"]

    def tex(key):
        if key not in files:
            return None
        cs = maps.MAPS[key][2]
        n = g.node("ShaderNodeTexImage", label=maps.MAPS[key][0])
        n.image = load_image(os.path.join(folder, files[key]), cs)
        n.interpolation = "Linear"
        g.links.new(uvn.outputs[0], socket(n.inputs, "Vector"))
        return n

    n = tex("base_color")
    if n:
        g.links.new(n.outputs[0], socket(bsdf.inputs, "Base Color"))
    n = tex("roughness")
    if n:
        g.links.new(n.outputs[0], socket(bsdf.inputs, "Roughness"))
    n = tex("metallic")
    if n:
        g.links.new(n.outputs[0], socket(bsdf.inputs, "Metallic"))
    n = tex("normal")
    if n:
        nm = g.node("ShaderNodeNormalMap", space="TANGENT")
        nm.uv_map = layer
        g.links.new(n.outputs[0], socket(nm.inputs, "Color"))
        g.links.new(nm.outputs[0], socket(bsdf.inputs, "Normal"))
    n = tex("emission")
    if n:
        g.links.new(n.outputs[0], socket(bsdf.inputs, "Emission Color"))
        socket(bsdf.inputs, "Emission Strength").default_value = float(manifest.get("emission_strength") or 1.0)
    n = tex("opacity")
    if n:
        g.links.new(n.outputs[0], socket(bsdf.inputs, "Alpha"))
        for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
            try:
                setattr(mat, attr, val)
            except (AttributeError, TypeError):
                pass
    n = tex("ao")
    if n:
        go = g.group(gltf_output_group())
        g.links.new(n.outputs[0], socket(go.inputs, "Occlusion"))
    compat.layout(tree)
    mat["nighty_baked"] = json.dumps({"folder": folder, "name": manifest["name"], "size": manifest["size"],
                                      "normal_format": manifest.get("normal_format", "opengl")})
    return mat


def source_materials(obj):
    """The procedural materials behind a baked object (or its current ones if it was never baked)."""
    names = obj.get(SOURCES)
    if names:
        mats = [bpy.data.materials.get(n) for n in names]
        if all(m is not None for m in mats):
            return mats
    return [s.material for s in obj.material_slots]


def apply_uvs(manifest, folder, objects):
    """Writes the packed atlas UVs into each object's mesh (the bake ran on a copy). Returns skipped names."""
    skipped = []
    layer = manifest.get("uv_layer")
    if not layer:
        return skipped
    for obj in objects:
        info = manifest.get("uv_files", {}).get(obj.name)
        me = obj.data
        if info is None:
            if me.uv_layers.get(layer) is None:
                skipped.append(obj.name)
            continue
        if len(me.loops) != info["loops"]:
            skipped.append(obj.name)
            continue
        uv_path = os.path.join(folder, info["file"])
        buf = np.load(uv_path)
        lay = me.uv_layers.get(layer) or me.uv_layers.new(name=layer)
        lay.data.foreach_set("uv", buf.astype(np.float32))
        me.uv_layers.active = lay
        try:
            lay.active_render = True
        except AttributeError:
            pass
        try:
            os.remove(uv_path)   # only needed once
        except OSError:
            pass
    return skipped


def apply(manifest, folder, objects, use_baked=True):
    """UVs + the baked material on every slot of every part. Returns a short summary."""
    skipped = apply_uvs(manifest, folder, objects)
    mat = baked_material(manifest, folder)
    for obj in objects:
        if obj.name in skipped:
            continue
        srcs = source_materials(obj)
        obj[SOURCES] = [m.name for m in srcs if m is not None]
        for m in srcs:
            if m is not None:
                m.use_fake_user = True
        if use_baked:
            for slot in obj.material_slots:
                slot.material = mat
            if not obj.material_slots:
                obj.data.materials.append(mat)
        obj["nighty_bake"] = os.path.join(folder, "bake.json")
    bpy.context.scene["nighty_last_bake"] = os.path.join(folder, "bake.json")
    return {"material": mat.name, "skipped": skipped}


def restore_sources(obj):
    """Puts the procedural materials back in the slots (before editing materials again)."""
    names = obj.get(SOURCES)
    if not names:
        return False
    for slot, n in zip(obj.material_slots, names):
        m = bpy.data.materials.get(n)
        if m is not None:
            slot.material = m
    return True
