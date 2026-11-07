# SPDX-License-Identifier: GPL-3.0-or-later
# Runs in a background Blender (blender -b --factory-startup --python import_glb.py -- <file> <out.blend> <json>)
# so a big model file never freezes the person's Blender. Blender's own importer reads it (GLB / glTF, FBX, OBJ),
# all mesh parts become ONE object (transforms applied), optionally scaled so its longest side is `size` meters,
# with its lowest point on the ground (z = 0) and its origin at the bottom center; images are packed. The object is
# saved alone in out.blend, which the addon then appends in one quick step. Prints "NIGHTY_RESULT {json}" at the end
# (the facts the triage report is built from). Not imported by the addon (it needs a fresh background Blender).

import json
import os
import sys

FORMATS = {".glb": "gltf", ".gltf": "gltf", ".fbx": "fbx", ".obj": "obj"}


def _import(path):
    import bpy
    kind = FORMATS.get(os.path.splitext(path)[1].lower())
    if kind == "gltf":
        try:                          # weld the UV-seam splits glTF stores, so the mesh is one watertight piece
            bpy.ops.import_scene.gltf(filepath=path, merge_vertices=True)
        except TypeError:
            bpy.ops.import_scene.gltf(filepath=path)
    elif kind == "fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif kind == "obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=path)
        else:                         # very old Blenders only
            bpy.ops.import_scene.obj(filepath=path)
    else:
        raise SystemExit("NIGHTY_ERROR not a GLB, glTF, FBX or OBJ file")


def main(argv):
    import bpy
    from mathutils import Matrix, Vector

    src, out_blend, opts = argv[0], argv[1], json.loads(argv[2])
    name = opts.get("name") or os.path.splitext(os.path.basename(src))[0] or "Imported"
    size = float(opts.get("size") or 0)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    before = set(bpy.data.objects)
    _import(src)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH" and o.data and len(o.data.vertices)]
    if not meshes:
        raise SystemExit("NIGHTY_ERROR the file has no mesh")
    armatures = sum(1 for o in new if o.type == "ARMATURE")
    shape_keys = sum(1 for o in meshes if o.data.shape_keys)
    # bake every part's world transform into its mesh, then join them into one object
    for o in meshes:
        mw = o.matrix_world.copy()
        o.parent = None
        for mod in list(o.modifiers):
            if mod.type == "ARMATURE":
                o.modifiers.remove(mod)
        o.data.transform(mw)
        o.matrix_world = Matrix.Identity(4)
    scene = bpy.context.scene
    for o in meshes:
        if o.name not in scene.collection.objects and not o.users_collection:
            scene.collection.objects.link(o)
    main_obj = max(meshes, key=lambda o: len(o.data.polygons))
    if len(meshes) > 1:
        with bpy.context.temp_override(active_object=main_obj, object=main_obj, selected_objects=meshes,
                                       selected_editable_objects=meshes):
            bpy.ops.object.join()
    for o in list(bpy.data.objects):
        if o is not main_obj:
            bpy.data.objects.remove(o, do_unlink=True)
    import numpy as np
    me = main_obj.data
    welded = _weld(me)                 # glTF and FBX store split vertices along UV seams and hard edges
    fixes = _fixes(main_obj, opts, np, Matrix)
    co = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    lo, hi = Vector(co.min(axis=0).tolist()), Vector(co.max(axis=0).tolist())
    dims = hi - lo
    longest = max(dims) or 1.0
    scale = size / longest if size > 0 else 1.0
    pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    me.transform(Matrix.Scale(scale, 4) @ Matrix.Translation(-pivot))
    me.update()
    main_obj.name = name
    me.name = name
    main_obj.location = (0.0, 0.0, 0.0)
    for img in bpy.data.images:
        if not img.has_data:
            try:
                img.pixels[0]          # loads it (an image is read lazily)
            except (IndexError, RuntimeError):
                pass
        if img.has_data and not img.packed_file:
            try:
                img.pack()
            except RuntimeError:
                pass
    main_obj["nighty_imported"] = os.path.basename(src)
    main_obj["nighty_import_fixes"] = json.dumps(fixes)
    bpy.data.libraries.write(out_blend, {main_obj}, fake_user=False, compress=False)
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    open_edges = sum(1 for e in bm.edges if not e.is_manifold)
    tris = sum(len(f.verts) - 2 for f in bm.faces)
    ngons = sum(1 for f in bm.faces if len(f.verts) > 4)
    quads = sum(1 for f in bm.faces if len(f.verts) == 4)
    bm.verts.ensure_lookup_table()
    seen, parts = bytearray(len(bm.verts)), 0
    for v in bm.verts:
        if seen[v.index]:
            continue
        parts += 1
        stack = [v]
        seen[v.index] = 1
        while stack:
            x = stack.pop()
            for e in x.link_edges:
                y = e.other_vert(x)
                if not seen[y.index]:
                    seen[y.index] = 1
                    stack.append(y)
    bm.free()
    report = {"object": main_obj.name, "format": FORMATS.get(os.path.splitext(src)[1].lower()),
              "vertices": len(me.vertices), "faces": len(me.polygons), "triangles": tris, "quads": quads,
              "ngons": ngons, "non_manifold_edges": open_edges, "loose_parts": parts,
              "parts_joined": len(meshes), "dimensions": [round(d * scale, 4) for d in dims],
              "original_dimensions": [round(d, 4) for d in dims], "scale": round(scale, 6),
              "uv_layers": len(me.uv_layers), "materials": [m.name for m in me.materials if m],
              "images": [{"name": i.name, "size": list(i.size)} for i in bpy.data.images if i.has_data],
              "armatures": armatures, "shape_keys": shape_keys, "welded_vertices": welded, "fixes": fixes}
    print("NIGHTY_RESULT " + json.dumps(report), flush=True)


def _weld(me):
    """Merges vertices at the same spot (the file's split seams), keeping UVs and sharp edges. Returns how many."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    before = len(bm.verts)
    if before:
        lo = [min(v.co[i] for v in bm.verts) for i in range(3)]
        hi = [max(v.co[i] for v in bm.verts) for i in range(3)]
        size = max(h - l for h, l in zip(hi, lo)) or 1.0
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=size * 1e-6)
    after = len(bm.verts)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return before - after


def _fixes(obj, opts, np, Matrix):
    """Optional fixes the person or the AI asks for (all off unless asked): stand the model upright (flat sides
    squared to the axes), turn it to nighty's facing rule (a long model along X, front end at +X; see orient.py) and
    clean a guessed metal map (exactly 0 / 1, by color: wood never metal). See glbfix.py."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import glbfix
    out = {}
    me = obj.data
    if opts.get("level") and len(me.polygons):
        n = len(me.polygons)
        nor = np.empty(n * 3, dtype=np.float32)
        me.polygons.foreach_get("normal", nor)
        area = np.empty(n, dtype=np.float32)
        me.polygons.foreach_get("area", area)
        R, info = glbfix.level_rotation(nor.reshape(-1, 3), area)
        out["upright"] = info
        if R is not None:
            co = np.empty(len(me.vertices) * 3, dtype=np.float32)
            me.vertices.foreach_get("co", co)
            co = co.reshape(-1, 3)
            c = (co.min(axis=0) + co.max(axis=0)) / 2
            T = Matrix.Translation(c.tolist())
            me.transform(T @ Matrix(R).to_4x4() @ T.inverted())
            me.update()
    if opts.get("facing") and len(me.vertices):
        import orient
        co = np.empty(len(me.vertices) * 3, dtype=np.float64)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        deg, info = orient.facing(co, pixel_aligned=bool(opts.get("pixel_aligned")))
        out["facing"] = info
        if deg:
            c = (co.min(axis=0) + co.max(axis=0)) / 2
            T = Matrix.Translation(c.tolist())
            me.transform(T @ Matrix(orient.turn_matrix(deg)).to_4x4() @ T.inverted())
            me.update()
    if opts.get("metal"):
        out["metal"] = _clean_metal(me, glbfix, np)
    return out


def _source(sock, depth=0):
    """(image, channel or None) feeding a shader input, through Separate Color and simple nodes."""
    if not sock.is_linked or depth > 4:
        return None
    link = sock.links[0]
    node = link.from_node
    if node.type == "TEX_IMAGE":
        return (node.image, None) if node.image is not None else None
    if node.type in ("SEPARATE_COLOR", "SEPRGB", "SEPARATE_RGB"):
        ch = list(node.outputs).index(link.from_socket)
        r = _source(node.inputs[0], depth + 1)
        return (r[0], ch) if r else None
    for inp in node.inputs:
        if inp.is_linked:
            return _source(inp, depth + 1)
    return None


def _pixels(img, np):
    w, h = img.size
    px = np.empty(w * h * img.channels, dtype=np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(h, w, img.channels)


def _clean_metal(me, glbfix, np):
    done, reports = set(), []
    for mat in me.materials:
        if mat is None or not mat.use_nodes:
            continue
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        base = _source(bsdf.inputs["Base Color"])
        met = _source(bsdf.inputs["Metallic"])
        if not base or not met or met[0] is None or (met[0].name, met[1]) in done:
            if not met and not bsdf.inputs["Metallic"].is_linked:
                v = bsdf.inputs["Metallic"].default_value
                bsdf.inputs["Metallic"].default_value = 1.0 if v >= 0.5 else 0.0
            continue
        img, ch = met
        done.add((img.name, ch))
        try:
            bp, mp = _pixels(base[0], np), _pixels(img, np)
        except (RuntimeError, ValueError):
            continue
        h, w = mp.shape[:2]
        if bp.shape[:2] != (h, w):            # nearest resample of the colors onto the metal map's pixels
            yi = (np.arange(h) * bp.shape[0] // h)
            xi = (np.arange(w) * bp.shape[1] // w)
            bp = bp[yi][:, xi]
        c = 0 if ch is None else ch
        new, info = glbfix.clean_metal(bp[..., :3], mp[..., c])
        mp[..., c] = new
        if ch is None and mp.shape[2] >= 3:
            mp[..., :3] = new[..., None]
        img.pixels.foreach_set(mp.ravel())
        img.update()
        try:
            img.pack()
        except RuntimeError:
            pass
        info["material"] = mat.name
        reports.append(info)
    return reports


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    try:
        main(args)
    except SystemExit as stop:
        print(str(stop), flush=True)
        sys.exit(1)
    except Exception as err:  # noqa: BLE001
        print(f"NIGHTY_ERROR {err.__class__.__name__}: {err}", flush=True)
        sys.exit(1)
