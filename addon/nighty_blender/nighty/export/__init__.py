# SPDX-License-Identifier: GPL-3.0-or-later
"""Exports per engine (nighty.export): "Made for" Roblox / Unity / Unreal / Godot / glTF / Blender.

    gen = export.export_steps(parts, "roblox", path="C:/out/Gun")   # a job (generator), see nighty.bake.job

Bakes first when the maps are missing or stale (so what is exported always matches the materials), then writes
the mesh with the engine's scale, axes, normal-map format and channel packing, LODs, short import notes and an
attribution file for third-party assets."""

import json
import os

import bpy

from . import engines
from .. import bake as bake_mod
from ..bake.job import WorkerJob, steps


def default_path(name, engine):
    if bpy.data.filepath:
        return os.path.join(os.path.dirname(bpy.data.filepath), "export", engine, bake_mod.safe_name(name))
    root = bpy.utils.user_resource("DATAFILES", path="nighty_blender", create=True)
    return os.path.join(root, "export", engine, bake_mod.safe_name(name))


def find_lods(objects, with_bases=False):
    """LODs made by the topology step: objects with 'nighty_lod_of' = a part's name and 'nighty_lod' = level, or
    named '<part>_LOD1', '<part>_LOD2', ... -> [[level-1 parts], [level-2 parts], ...] (and {lod: part})."""
    names = {o.name for o in objects}
    levels, bases = {}, {}
    for o in bpy.data.objects:
        if o.type != "MESH" or o.name in names:
            continue
        base, lvl = o.get("nighty_lod_of"), o.get("nighty_lod")
        if base is None and "_LOD" in o.name:
            b, _, tail = o.name.rpartition("_LOD")
            if tail.isdigit() and b in names:
                base, lvl = b, int(tail)
        if base in names and lvl:
            levels.setdefault(int(lvl), []).append(o.name)
            bases[o.name] = base
    out = [levels[k] for k in sorted(levels) if k > 0]
    return (out, bases) if with_bases else out


def export_steps(objects, made_for, path=None, name=None, size=1024, maps_wanted=None, fmt=None, join=None,
                 max_size=None, device="auto", style="pbr", force_bake=False, keep_job=False):
    engine = engines.resolve(made_for)
    if engine is None:
        raise ValueError(f"made_for must be one of {', '.join(engines.ENGINES)}")
    objects = [o for o in objects if o is not None and o.type == "MESH"]
    if not objects:
        raise ValueError("nothing to export: no mesh parts")
    name = bake_mod.safe_name(name or objects[0].name)
    out_dir = bpy.path.abspath(path) if path else default_path(name, engine)
    if os.path.splitext(out_dir)[1].lower() in (".fbx", ".glb", ".gltf", ".obj", ".blend"):
        out_dir = os.path.dirname(out_dir)   # a file was given: its folder
    # the maps these parts were baked into (a bake under another name must not be baked again)
    folder = bake_mod.bake_folder_of(objects) or bake_mod.asset_folder(name)
    high = bake_mod.find_high(objects)
    lods, lod_bases = find_lods(objects, with_bases=True)
    size = bake_mod.maps.size_of(size)
    need_bake = engines.needs_maps(engine) and (force_bake or not bake_mod.fresh(objects, folder, size))
    from ..presets import current
    from ..bake.apply import source_materials
    spec = {"made_for": engine, "name": name, "path": out_dir, "objects": [o.name for o in objects],
            "lods": lods, "lod_bases": lod_bases, "format": fmt, "max_size": max_size, "bake_folder": folder,
            "keep_procedural": current().get("texture_type") == "blender",
            "sources": {o.name: [m.name for m in source_materials(o) if m is not None] for o in objects}}
    if join is not None:
        spec["join"] = bool(join)
    st = bake_mod.stamp(objects)
    if need_bake:
        transfer = any(o.get("nighty_bake_transfer") for o in objects) and all(o.name in high for o in objects)
        spec["bake"] = bake_mod.bake_spec(objects, size, maps_wanted, folder, name, high, device, None, style,
                                          transfer)
    blocks = bake_mod.datablocks_for(objects + [bpy.data.objects[n] for lv in lods for n in lv], high)
    job = WorkerJob("export", spec, blocks, keep=keep_job)
    names = [o.name for o in objects]

    def finish(res):
        out = {"made_for": engine, "folder": out_dir, "files": res.get("files", []),
               "mesh": res.get("mesh"), "textures": res.get("textures"), "warnings": res.get("warnings", []),
               "normal_format": res.get("normal_format"), "baked": bool(res.get("manifest"))}
        if res.get("manifest"):
            bake_mod.apply_with_stamp(res["manifest"], folder, names, st)
        info = {"made_for": engine, "folder": out_dir, "files": out["files"]}
        bpy.context.scene["nighty_last_export"] = json.dumps(info)
        return out

    return steps(job, finish)
