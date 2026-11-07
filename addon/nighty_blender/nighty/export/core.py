# SPDX-License-Identifier: GPL-3.0-or-later
"""Engine exports (worker side): engine textures from the baked maps (packing, normal format, size), export copies
of the parts (modifiers applied, triangulated exactly like the bake, one UV map, one material), the mesh file(s),
LODs, short import notes and an attribution file. Runs inside the `blender -b` worker (or a test)."""

import json
import os
import shutil

import bpy
import numpy as np

from ..bake import png, maps
from ..bake.core import add_triangulate, ATLAS, log
from ..materials import compat
from ..materials.compat import Graph, socket
from .engines import ENGINES


# ----------------------------------------------------------------------------------------------- textures

def _load(folder, manifest, key):
    f = manifest.get("maps", {}).get(key)
    if not f:
        return None
    a = png.read(os.path.join(folder, f)).astype(np.float32)
    return a / (65535.0 if a.max() > 255 else 255.0)


def engine_textures(engine_key, manifest, folder, out_dir, name, max_size=None):
    """Writes the engine's texture files; returns ({recipe: path}, [file rows])."""
    eng = ENGINES[engine_key]
    size = min(int(manifest["size"]), int(max_size or eng["max_size"]))
    src = {k: _load(folder, manifest, k) for k in maps.ORDER}
    s = size

    def fit(a):
        return None if a is None else maps.resize(a, s)

    base = fit(src["base_color"])
    if base is None:
        base = np.full((s, s, 3), 0.5, np.float32)
    rough = fit(src["roughness"])
    rough = rough[..., 0] if rough is not None else np.full((s, s), 0.5, np.float32)
    metal = fit(src["metallic"])
    metal = maps.snap_binary(metal[..., 0]) if metal is not None else np.zeros((s, s), np.float32)
    normal = fit(src["normal"])
    if normal is None:
        normal = np.zeros((s, s, 3), np.float32) + np.array([0.5, 0.5, 1.0], np.float32)
    elif normal.shape[0] != src["normal"].shape[0]:
        v = normal * 2 - 1
        normal = (v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-6)) * 0.5 + 0.5
    if eng["normal"] == "directx":
        normal = maps.flip_green(normal)
    ao = fit(src["ao"])
    ao = ao[..., 0] if ao is not None else np.ones((s, s), np.float32)
    emis = fit(src["emission"])
    opac = fit(src["opacity"])
    opac = opac[..., 0] if opac is not None else None

    recipes = {
        "color_alpha": lambda: base[..., :3] if opac is None else np.dstack([base[..., :3], opac]),
        "normal": lambda: normal[..., :3],
        "roughness": lambda: rough,
        "metallic": lambda: metal,
        "ao": lambda: ao,
        "emission": lambda: None if emis is None else emis[..., :3],
        "emissive_mask": lambda: None if emis is None else emis[..., :3].max(axis=-1),
        "unity_metallic_smoothness": lambda: maps.pack(metal, metal, metal, 1.0 - rough),
        "unity_mask": lambda: maps.pack(metal, ao, np.ones_like(ao), 1.0 - rough),
        "orm": lambda: maps.pack(ao, rough, metal),
    }
    written, rows = {}, []
    os.makedirs(out_dir, exist_ok=True)
    for pattern, recipe, slot in eng["textures"]:
        arr = recipes[recipe]()
        if arr is None:
            continue
        path = os.path.join(out_dir, pattern.format(n=name))
        n = png.write(path, png.to_uint(arr))
        written[recipe] = path
        rows.append({"file": os.path.basename(path), "for": slot, "bytes": n, "size": s})
    written["_alpha"] = opac is not None
    # glTF / Godot: images for the embedded material (not shipped loose)
    if eng["format"] == "glb":
        tmp = os.path.join(out_dir, ".nb_gltf")
        os.makedirs(tmp, exist_ok=True)
        for recipe, arr in (("color_alpha", recipes["color_alpha"]()), ("normal", normal),
                            ("orm", recipes["orm"]()), ("emission", recipes["emission"]())):
            if arr is None:
                continue
            p = os.path.join(tmp, f"{name}_{recipe}.png")
            png.write(p, png.to_uint(arr))
            written[recipe] = p
    return written, rows


# ----------------------------------------------------------------------------------------------- materials

def export_material(engine_key, tex, name, emission_strength=1.0):
    """One material for the export copies, built from the engine textures (so FBX / glTF reference them)."""
    mat = compat.new_material(f"{name}")
    tree = mat.node_tree
    tree.nodes.clear()
    g = Graph(tree)
    out = g.node("ShaderNodeOutputMaterial")
    bsdf = g.node("ShaderNodeBsdfPrincipled")
    g.links.new(bsdf.outputs[0], socket(out.inputs, "Surface"))

    def img(path, cs):
        i = bpy.data.images.load(path, check_existing=False)
        try:
            i.colorspace_settings.name = cs
        except TypeError:
            pass
        n = g.node("ShaderNodeTexImage")
        n.image = i
        return n

    if "color_alpha" in tex:
        n = img(tex["color_alpha"], "sRGB")
        g.links.new(n.outputs[0], socket(bsdf.inputs, "Base Color"))
        if tex.get("_alpha"):
            g.links.new(n.outputs[1], socket(bsdf.inputs, "Alpha"))
            for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
                try:
                    setattr(mat, attr, val)
                except (AttributeError, TypeError):
                    pass
    if "normal" in tex:
        n = img(tex["normal"], "Non-Color")
        nm = g.node("ShaderNodeNormalMap")
        g.links.new(n.outputs[0], socket(nm.inputs, "Color"))
        g.links.new(nm.outputs[0], socket(bsdf.inputs, "Normal"))
    if "orm" in tex:
        n = img(tex["orm"], "Non-Color")
        sep = g.node("ShaderNodeSeparateColor")
        g.links.new(n.outputs[0], sep.inputs[0])
        g.links.new(sep.outputs[1], socket(bsdf.inputs, "Roughness"))
        g.links.new(sep.outputs[2], socket(bsdf.inputs, "Metallic"))
        from ..bake.apply import gltf_output_group
        go = g.group(gltf_output_group())
        g.links.new(sep.outputs[0], socket(go.inputs, "Occlusion"))
    else:
        if "roughness" in tex:
            n = img(tex["roughness"], "Non-Color")
            g.links.new(n.outputs[0], socket(bsdf.inputs, "Roughness"))
        if "metallic" in tex:
            n = img(tex["metallic"], "Non-Color")
            g.links.new(n.outputs[0], socket(bsdf.inputs, "Metallic"))
    if "emission" in tex:
        n = img(tex["emission"], "sRGB")
        g.links.new(n.outputs[0], socket(bsdf.inputs, "Emission Color"))
        socket(bsdf.inputs, "Emission Strength").default_value = float(emission_strength or 1.0)
    compat.layout(tree)
    return mat


# ----------------------------------------------------------------------------------------------- meshes

def make_copies(objs, layer, mat, join=False, name="Asset"):
    """Export copies: modifiers applied (with NB Triangulate, the same split as the bake), one UV map named
    'UVMap', one material. Returns the copy objects (one when joined)."""
    sc = bpy.context.scene
    coll = bpy.data.collections.new("NB Export")
    sc.collection.children.link(coll)
    for o in objs:
        add_triangulate(o)
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    copies = []
    for o in objs:
        ev = o.evaluated_get(dg)
        me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
        keep = me.uv_layers.get(layer) if layer else me.uv_layers.active
        for lay in [lay for lay in me.uv_layers if keep is None or lay.name != keep.name]:
            me.uv_layers.remove(lay)
        if me.uv_layers:
            me.uv_layers[0].name = "UVMap"
        me.materials.clear()
        me.materials.append(mat)
        if len(me.polygons):
            me.polygons.foreach_set("material_index", np.zeros(len(me.polygons), np.int32))
        base = o.name
        o.name = base + "__src"
        c = bpy.data.objects.new(base, me)
        c.matrix_world = o.matrix_world.copy()
        coll.objects.link(c)
        copies.append(c)
    if join and len(copies) > 1:
        vl = bpy.context.view_layer
        for o in vl.objects:
            o.select_set(False)
        for c in copies:
            c.select_set(True)
        vl.objects.active = copies[0]
        bpy.ops.object.join()
        joined = vl.objects.active
        joined.name = name
        joined.data.name = name
        copies = [joined]
    return copies


def transfer_uvs(lod, base, layer):
    """Gives a LOD the baked UV layout of its part (a Data Transfer of the nearest face's UVs), so the LOD uses the
    same texture set. False when there is nothing to take it from."""
    if base is None or base.data.uv_layers.get(layer) is None:
        return False
    me = lod.data
    lay = me.uv_layers.get(layer) or me.uv_layers.new(name=layer)
    me.uv_layers.active = lay
    base.data.uv_layers.active = base.data.uv_layers[layer]
    mod = lod.modifiers.new("NB UV from part", "DATA_TRANSFER")
    mod.object = base
    mod.use_loop_data = True
    mod.data_types_loops = {"UV"}
    mod.loop_mapping = "POLYINTERP_NEAREST"
    for attr, options in (("layers_uv_select_src", (layer, "ACTIVE")), ("layers_uv_select_dst", ("NAME", "ACTIVE"))):
        for v in options:
            try:
                setattr(mod, attr, v)
                break
            except TypeError:   # the choices differ between Blender versions
                continue
    return True   # after the LOD's own modifiers: onto its final faces


def _select(objs):
    vl = bpy.context.view_layer
    for o in vl.objects:
        if o is not None:
            o.select_set(False)
    for o in objs:
        o.select_set(True)
    vl.objects.active = objs[0] if objs else None


def _op_kwargs(op, kw):
    props = op.get_rna_type().properties.keys()
    return {k: v for k, v in kw.items() if k in props}


def write_mesh(engine_key, objs, path, fmt):
    eng = ENGINES[engine_key]
    _select(objs)
    if fmt == "fbx":
        kw = dict(filepath=path, use_selection=True, object_types={"MESH"}, use_mesh_modifiers=True,
                  mesh_smooth_type="OFF", use_tspace=True, add_leaf_bones=False, bake_anim=False,
                  apply_unit_scale=True, use_custom_props=False)
        kw.update(eng["fbx"])
        bpy.ops.export_scene.fbx(**_op_kwargs(bpy.ops.export_scene.fbx, kw))
    elif fmt == "obj":
        kw = dict(filepath=path, export_selected_objects=True, apply_modifiers=True, export_uv=True,
                  export_normals=True, export_materials=True, path_mode="COPY", export_triangulated_mesh=True)
        kw.update(eng.get("obj", {}))
        bpy.ops.wm.obj_export(**_op_kwargs(bpy.ops.wm.obj_export, kw))
    elif fmt == "glb":
        kw = dict(filepath=path, export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
                  export_texcoords=True, export_normals=True, export_tangents=False, export_materials="EXPORT",
                  export_image_format="AUTO", export_animations=False, export_cameras=False, export_lights=False,
                  export_extras=False)
        bpy.ops.export_scene.gltf(**_op_kwargs(bpy.ops.export_scene.gltf, kw))
    else:
        raise ValueError(fmt)
    return path


def tri_count(objs):
    n = 0
    for o in objs:
        o.data.calc_loop_triangles()
        n += len(o.data.loop_triangles)
    return n


def world_dims(objs):
    from mathutils import Vector
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    if not pts:
        return [0.0, 0.0, 0.0]
    return [max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3)]


# ----------------------------------------------------------------------------------------------- notes

def attribution(objs):
    """Third-party sources recorded on objects, materials and images (nighty_source / nighty_license /
    nighty_author custom properties; CC0 downloads record themselves)."""
    rows, seen = [], set()

    def visit(idb):
        lic = idb.get("nighty_license") if hasattr(idb, "get") else None
        if lic:
            key = (idb.get("nighty_source", ""), lic)
            if key not in seen:
                seen.add(key)
                rows.append({"what": idb.name, "license": lic, "source": idb.get("nighty_source", ""),
                             "author": idb.get("nighty_author", "")})

    for o in objs:
        visit(o)
        for s in o.material_slots:
            m = s.material
            if m is None:
                continue
            visit(m)
            if m.node_tree:
                for n in m.node_tree.nodes:
                    if n.type == "TEX_IMAGE" and n.image is not None:
                        visit(n.image)
    return rows


def write_attribution(out_dir, rows):
    if not rows:
        return None
    lines = ["Third-party assets in this export", ""]
    for r in rows:
        need = "" if r["license"].upper() in ("CC0", "CC0-1.0", "CC0 1.0") else "  (attribution required)"
        by = f" by {r['author']}" if r["author"] else ""
        lines.append(f"- {r['what']}{by}: {r['license']}{need}  {r['source']}".rstrip())
    p = os.path.join(out_dir, "ATTRIBUTION.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return p


def notes(engine_key, name, mesh_file, rows, dims_units, tris):
    eng = ENGINES[engine_key]
    tex = {r["for"]: r["file"] for r in rows}
    d = " x ".join(f"{v:.2f}" for v in dims_units)
    if engine_key == "roblox":
        lines = [f"Roblox: {name}",
                 f"1. Studio > Import 3D > {mesh_file} (Scale Unit: Studs). Size: about {d} studs.",
                 "2. Add a SurfaceAppearance to the MeshPart and set: " +
                 ", ".join(f"{k} = {v}" for k, v in tex.items()) + ".",
                 f"Triangles: {tris} (Roblox limit: 20000 per mesh)."]
    elif engine_key == "unity":
        lines = [f"Unity: {name}", f"1. Drop this folder into Assets. {mesh_file} is in meters ({d} m).",
                 f"2. URP Lit: Base Map {tex.get('Base Map', '-')}, Metallic Map "
                 f"{tex.get('URP Metallic Map (smoothness in alpha)', '-')} (Source: Metallic Alpha), Normal Map "
                 f"{tex.get('Normal Map', '-')}, Occlusion {tex.get('Occlusion Map', '-')}"
                 + (f", Emission {tex['Emission Map']}" if "Emission Map" in tex else "") + ".",
                 f"   HDRP Lit: Mask Map {tex.get('HDRP Mask Map', '-')}."]
    elif engine_key == "unreal":
        lines = [f"Unreal: {name}", f"1. Import {mesh_file} (size {d} cm).",
                 f"2. {tex.get('Occlusion R, Roughness G, Metallic B (sRGB off)', '-')}: sRGB off, compression Masks. "
                 f"{tex.get('Normal (DirectX)', '-')} is already DirectX."]
    elif engine_key in ("gltf", "godot"):
        lines = [f"{eng['label']}: {name}", f"{mesh_file} has the textures inside (base color, normal, "
                 f"occlusion-roughness-metallic, emission). Size: {d} m."]
    else:
        lines = [f"Blender: {name}", f"File > Append > {mesh_file} > Object. Size: {d} m."]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------------------------- the task

def run(spec, progress):
    """Worker task 'export': bake first when asked, then the engine files. Returns the result for the main side."""
    from ..bake import core as bake_core
    engine_key = spec["made_for"]
    eng = ENGINES[engine_key]
    name = spec["name"]
    out_dir = spec["path"]
    os.makedirs(out_dir, exist_ok=True)
    res = {"files": [], "warnings": []}
    manifest, folder = None, spec.get("bake_folder")
    if spec.get("bake"):
        def sub(p, m):
            progress(0.75 * p, m)
        manifest = bake_core.bake_asset(spec["bake"], sub)
        folder = spec["bake"]["out_dir"]
        res["manifest"] = manifest
        res["bake_folder"] = folder
    elif folder and os.path.exists(os.path.join(folder, "bake.json")):
        with open(os.path.join(folder, "bake.json"), encoding="utf-8") as f:
            manifest = json.load(f)
    objs = [bpy.data.objects[n] for n in spec["objects"] if n in bpy.data.objects]
    progress(0.8, "Writing files")
    if eng["format"] == "blend":
        if spec.get("keep_procedural"):   # Texture type: Blender materials
            for o in objs:
                for slot, mname in zip(o.material_slots, (spec.get("sources") or {}).get(o.name, [])):
                    if bpy.data.materials.get(mname) is not None:
                        slot.material = bpy.data.materials[mname]
        res["files"] += export_blend(objs, out_dir, name, manifest, folder)
    else:
        if manifest is None:
            raise RuntimeError("no baked maps for this asset (bake first)")
        tex, rows = engine_textures(engine_key, manifest, folder, out_dir, name, spec.get("max_size"))
        res["textures"] = rows
        layer = manifest.get("uv_layer") or None
        mat = export_material(engine_key, tex, name, manifest.get("emission_strength", 1.0))
        join = spec.get("join", eng.get("join", False))
        fmt = spec.get("format") or eng["format"]
        prefix = eng.get("prefix", "")
        lod_objects = {n: bpy.data.objects[n] for lv in (spec.get("lods") or []) for n in lv if n in bpy.data.objects}
        lod_bases = {k: bpy.data.objects.get(v) for k, v in (spec.get("lod_bases") or {}).items()}
        copies = make_copies(objs, layer, mat, join=join, name=name)
        mesh_file = f"{prefix}{name}.{fmt}"
        write_mesh(engine_key, copies, os.path.join(out_dir, mesh_file), fmt)
        tris = tri_count(copies)
        dims_m = world_dims(copies)
        units = [v / eng["meters_per_unit"] for v in dims_m]
        res["mesh"] = {"file": mesh_file, "triangles": tris, "size_m": [round(v, 4) for v in dims_m],
                       "size_" + eng["unit"]: [round(v, 3) for v in units], "parts": len(copies)}
        if eng.get("tri_limit"):
            for c in copies:
                c.data.calc_loop_triangles()
                if len(c.data.loop_triangles) > eng["tri_limit"]:
                    res["warnings"].append(f"{c.name}: {len(c.data.loop_triangles)} triangles (limit "
                                           f"{eng['tri_limit']}); lower the detail")
        res["files"].append(mesh_file)
        res["files"] += [r["file"] for r in rows]
        # LODs (from the topology step): same textures, own files; UVs carried over from their part when missing
        if eng.get("lods") and spec.get("lods"):
            for level, names in enumerate(spec["lods"], start=1):
                lod_objs = [lod_objects[n] for n in names if n in lod_objects]
                lod_objs = [o for o in lod_objs if not layer or o.data.uv_layers.get(layer) or
                            transfer_uvs(o, lod_bases.get(o.name), layer)]
                if not lod_objs:
                    res["warnings"].append(f"LOD{level}: no parts with the baked UVs, skipped")
                    continue
                lc = make_copies(lod_objs, layer, mat, join=join, name=f"{name}_LOD{level}")
                f = f"{prefix}{name}_LOD{level}.{fmt}"
                write_mesh(engine_key, lc, os.path.join(out_dir, f), fmt)
                res["files"].append(f)
        with open(os.path.join(out_dir, f"{name}_import.txt"), "w", encoding="utf-8") as fh:
            fh.write(notes(engine_key, name, mesh_file, rows, units, tris))
        res["files"].append(f"{name}_import.txt")
        shutil.rmtree(os.path.join(out_dir, ".nb_gltf"), ignore_errors=True)
    att = write_attribution(out_dir, attribution(objs))
    if att:
        res["files"].append(os.path.basename(att))
    res["out_dir"] = out_dir
    res["made_for"] = engine_key
    res["normal_format"] = eng["normal"]
    progress(1.0, "Done")
    log("export", engine_key, res["files"])
    return res


def export_blend(objs, out_dir, name, manifest, folder):
    """'Just Blender': the parts with their materials (procedural or baked) in a .blend; baked maps copied into
    textures/ and linked relative to it."""
    tex_dir = os.path.join(out_dir, "textures")
    files = []
    blocks = set(objs)
    for o in objs:
        for s in o.material_slots:
            if s.material is not None:
                blocks.add(s.material)
                for n in (s.material.node_tree.nodes if s.material.node_tree else []):
                    if n.type == "TEX_IMAGE" and n.image is not None and n.image.filepath:
                        src = bpy.path.abspath(n.image.filepath)
                        if os.path.exists(src):
                            os.makedirs(tex_dir, exist_ok=True)
                            dst = os.path.join(tex_dir, os.path.basename(src))
                            if os.path.abspath(src) != os.path.abspath(dst):
                                shutil.copyfile(src, dst)
                            n.image.filepath = dst
                            files.append("textures/" + os.path.basename(src))
    path = os.path.join(out_dir, f"{name}.blend")
    bpy.data.libraries.write(path, blocks, path_remap="RELATIVE_ALL", compress=True)
    files.insert(0, os.path.basename(path))
    with open(os.path.join(out_dir, f"{name}_import.txt"), "w", encoding="utf-8") as fh:
        fh.write(notes("blender", name, os.path.basename(path), [], world_dims(objs), 0))
    files.append(f"{name}_import.txt")
    return sorted(set(files), key=files.index)
