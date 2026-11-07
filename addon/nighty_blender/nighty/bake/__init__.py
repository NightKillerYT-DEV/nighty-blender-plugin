# SPDX-License-Identifier: GPL-3.0-or-later
"""Baking (nighty.bake): clean maps from the materials, in a background Blender.

    from nighty import bake
    gen = bake.bake_steps(objs, size=2048)          # a job: each next() is a short main-thread step
    result = bake.job.run_steps(gen)                # (tests / scripts; tools hand the generator to the jobs)

Maps: base_color, roughness, metallic (exactly 0 / 1), normal (tangent, OpenGL), ao, emission, opacity.
Data maps are Non-Color; every map is saved to disk; the result is one clean Principled material.
"""

import os
import re

import bpy

from . import maps
from .job import WorkerJob, steps, run_steps  # noqa: F401  (re-exported)

DEFAULT_MAPS = ["base_color", "roughness", "metallic", "normal", "ao", "emission", "opacity"]
MAPS_BY_TEXTURES = {
    "pbr": DEFAULT_MAPS,
    "stylized": ["base_color", "roughness", "metallic", "normal", "emission", "opacity"],
    "color": ["base_color", "emission", "opacity"],
}


def safe_name(name):
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", name or "Asset").strip("_") or "Asset"


def asset_folder(name, base=None):
    """Where maps go: <base>/<name>, else next to the saved .blend (textures/<name>), else Blender's user folder
    (bakes/<name>-<this file's id>: two unsaved files that both make a 'Chest' must not share, and so overwrite,
    one folder of maps)."""
    if base:
        return os.path.join(bpy.path.abspath(base), safe_name(name))
    if bpy.data.filepath:
        return os.path.join(os.path.dirname(bpy.data.filepath), "textures", safe_name(name))
    root = bpy.utils.user_resource("DATAFILES", path="nighty_blender", create=True)
    return os.path.join(root, "bakes", f"{safe_name(name)}-{_file_id()}")


def _file_id():
    """A short id kept in this .blend (on its first scene), made once."""
    import uuid
    scenes = sorted(bpy.data.scenes, key=lambda sc: sc.name)
    for sc in scenes:
        if sc.get("nighty_file_id"):
            return sc["nighty_file_id"]
    fid = uuid.uuid4().hex[:8]
    try:
        scenes[0]["nighty_file_id"] = fid
    except (IndexError, AttributeError, RuntimeError):
        pass
    return fid


def referenced_objects(materials):
    """Objects that node trees point at (decal projectors use Texture Coordinate 'object')."""
    found, seen = set(), set()

    def walk(tree):
        if tree is None or tree.name in seen:
            return
        seen.add(tree.name)
        for n in tree.nodes:
            if n.type == "TEX_COORD" and n.object is not None:
                found.add(n.object)
            if n.type == "GROUP":
                walk(n.node_tree)

    for m in materials:
        if m is not None:
            walk(m.node_tree)
    return found


def datablocks_for(objects, high=None):
    """Everything the worker needs: parts, their high polys, decal projectors, the procedural source materials."""
    from .apply import source_materials
    blocks = set(objects)
    for h in (high or {}).values():
        if h is not None:
            blocks.add(h)
    mats = set()
    for o in list(blocks):
        if o.type == "MESH":
            mats.update(m for m in source_materials(o) if m is not None)
            mats.update(s.material for s in o.material_slots if s.material is not None)
    blocks |= mats
    blocks |= referenced_objects(mats)
    return blocks


def find_high(objects):
    """High polys by convention: a custom property 'nighty_high' on the low (an object name), or an object called
    '<name>_high' / '<name>.high' / '<name>_HP'."""
    pairs = {}
    for o in objects:
        name = o.get("nighty_high")
        cands = [name] if name else [f"{o.name}_high", f"{o.name}.high", f"{o.name}_HP", f"{o.name}_hp"]
        for c in cands:
            h = bpy.data.objects.get(c) if c else None
            if h is not None and h.type == "MESH" and h is not o:
                pairs[o.name] = h
                break
    return pairs


def tree_hash(tree, h=None, _seen=None):
    """A fingerprint of a node tree (nodes, values, links, images, groups): tells whether a bake is stale."""
    import hashlib
    h = h or hashlib.sha1()
    _seen = _seen if _seen is not None else set()
    if tree is None or tree.name in _seen:
        return h
    _seen.add(tree.name)
    for n in sorted(tree.nodes, key=lambda n: n.name):
        h.update(f"{n.bl_idname}|{n.name}".encode())
        for attr in ("operation", "blend_type", "data_type", "interpolation_type", "noise_dimensions", "feature",
                     "wave_type", "projection", "extension", "inside", "only_local", "samples", "uv_map"):
            if hasattr(n, attr):
                h.update(f"{attr}={getattr(n, attr)}".encode())
        if n.type == "TEX_IMAGE" and n.image is not None:
            h.update(f"img={n.image.filepath}|{n.image.name}".encode())
        if n.type == "TEX_COORD" and n.object is not None:
            h.update(repr([round(v, 5) for row in n.object.matrix_world for v in row]).encode())
        if n.type == "VALTORGB":
            h.update(repr([(round(e.position, 4), tuple(round(c, 4) for c in e.color))
                           for e in n.color_ramp.elements]).encode())
        for i in n.inputs:
            if not i.is_linked and hasattr(i, "default_value"):
                v = i.default_value
                try:
                    v = tuple(round(x, 5) for x in v)
                except TypeError:
                    v = round(v, 5) if isinstance(v, float) else v
                h.update(f"{i.identifier}={v}".encode())
        if n.type == "GROUP":
            tree_hash(n.node_tree, h, _seen)
    for link in tree.links:
        h.update(f"{link.from_node.name}.{link.from_socket.identifier}>{link.to_node.name}."
                 f"{link.to_socket.identifier}".encode())
    return h


def stamp(objects):
    """One fingerprint for the asset's source materials and meshes (stored on each part after a bake)."""
    import hashlib
    from .apply import source_materials
    h = hashlib.sha1()
    for o in sorted(objects, key=lambda o: o.name):
        h.update(f"{o.name}|{len(o.data.vertices)}|{len(o.data.loops)}".encode())
        for m in source_materials(o):
            if m is not None:
                h.update(m.name.encode())
                tree_hash(m.node_tree, h)
    return h.hexdigest()[:16]


def fresh(objects, folder, size=None):
    """True when the maps in `folder` were baked from exactly these parts and materials (and are big enough)."""
    import json
    path = os.path.join(folder, "bake.json")
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        return False
    if size and int(manifest.get("size", 0)) < int(size):
        return False
    st = stamp(objects)
    return all(o.get("nighty_bake") == path and o.get("nighty_bake_stamp") == st for o in objects)


def bake_spec(objects, size, maps_wanted, folder, name, high, device, samples, style, transfer=False):
    from . import apply as apply_mod
    return {"objects": [o.name for o in objects], "size": size, "maps": maps_wanted or DEFAULT_MAPS,
            "out_dir": folder, "name": name, "high": {k: v.name for k, v in high.items()}, "device": device,
            "samples": samples or {}, "style": style, "transfer": bool(transfer),
            "sources": {o.name: [m.name for m in apply_mod.source_materials(o) if m is not None] for o in objects},
            "threads": max(1, (os.cpu_count() or 2) - 1)}


def apply_with_stamp(manifest, folder, names, st):
    from . import apply as apply_mod
    parts = [bpy.data.objects.get(n) for n in names]
    parts = [p for p in parts if p is not None]
    out = apply_mod.apply(manifest, folder, parts)
    for p in parts:
        p["nighty_bake_stamp"] = st
    return out


def bake_steps(objects, size=1024, maps_wanted=None, out_dir=None, name=None, high=None, device="auto",
               samples=None, style="pbr", apply_result=True, keep_job=False, transfer=False):
    """The bake as a job (generator). Returns {'manifest', 'folder', 'material', ...} at the end.
    transfer: colors / roughness / metallic come from each part's high poly's own material (selected to active),
    e.g. an AI model's textures onto its low poly; needs a high poly per part."""
    objects = [o for o in objects if o is not None and o.type == "MESH"]
    if not objects:
        raise ValueError("nothing to bake: no mesh parts")
    name = safe_name(name or objects[0].name)
    size = maps.size_of(size)
    folder = out_dir or asset_folder(name)
    high = high if high is not None else find_high(objects)
    if transfer:
        missing = [o.name for o in objects if o.name not in high]
        if missing:
            raise ValueError(f"no high poly for {', '.join(missing)} (retopo / decimate keep the dense original "
                             "as the bake source)")
    spec = bake_spec(objects, size, maps_wanted, folder, name, high, device, samples, style, transfer)
    st = stamp(objects)
    job = WorkerJob("bake", spec, datablocks_for(objects, high), keep=keep_job)
    names = [o.name for o in objects]

    def finish(res):
        manifest = res["manifest"]
        out = {"manifest": manifest, "folder": folder}
        if apply_result:
            out.update(apply_with_stamp(manifest, folder, names, st))
            for n in names:          # an export that bakes again must take the colors from the high poly too
                o = bpy.data.objects.get(n)
                if o is not None:
                    if transfer:
                        o["nighty_bake_transfer"] = True
                    elif "nighty_bake_transfer" in o:
                        del o["nighty_bake_transfer"]
        return out

    return steps(job, finish)


REPORT_KEY = "nighty_texture_report"


def bake_folder_of(objects):
    for o in objects:
        p = o.get("nighty_bake")
        if p and os.path.exists(p):
            return os.path.dirname(p)
    return None


def verify_steps(objects, folder=None, style=None, made_for=None, renders=True, keep_job=False):
    """verify_textures as a job. The report also goes on the scene (scene['nighty_texture_report'], JSON) for
    finish_asset: {passed, failed, checks, renders, stamp, time}."""
    import json
    objects = [o for o in objects if o is not None and o.type == "MESH"]
    folder = folder or bake_folder_of(objects)
    if not folder or not os.path.exists(os.path.join(folder, "bake.json")):
        raise ValueError("no baked maps for these parts yet: bake first")
    st = stamp(objects)
    spec = {"objects": [o.name for o in objects], "folder": folder, "style": style, "made_for": made_for,
            "renders": renders, "stamp": st}
    job = WorkerJob("verify", spec, datablocks_for(objects), keep=keep_job)

    def finish(res):
        res["current"] = all(o.get("nighty_bake_stamp") == st for o in objects)
        bpy.context.scene[REPORT_KEY] = json.dumps(res)
        return res

    return steps(job, finish)
