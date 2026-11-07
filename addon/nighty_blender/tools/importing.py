# SPDX-License-Identifier: GPL-3.0-or-later
# The import step (the public `import` tool): a model file from the person (GLB / glTF, FBX, OBJ) comes into the
# scene through a background Blender (nighty/io/import_file.py: a big file never freezes Blender), as ONE object.
# Two things happen every time:
#   - a locked _SOURCE copy: "<name>_SOURCE", kept in the .blend (fake user) but not in the scene, selection locked,
#     transforms locked, marked nighty_source_of = <name>. Nothing in Nighty Blender changes it; check
#     {what: "source"} compares the finished model with it, and the person can always go back to it.
#   - a triage report: what the file holds and what it needs (triangles, open edges, loose parts, UVs, textures,
#     scale, rigs), as JSON next to the .blend (or in Blender's user folder) and in the answer.

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

import bpy

from . import ToolError, action

FORMATS = (".glb", ".gltf", ".fbx", ".obj")
MAX_BYTES = 2 * 1024 ** 3
SOURCE_SUFFIX = "_SOURCE"
SOURCE_COLLECTION = "Nighty _SOURCE copies"
ROBLOX_MESHPART_TRIS = 20000


def check_file(path):
    """Raises ToolError unless `path` is a model file this can import."""
    if not isinstance(path, str) or not path.strip():
        raise ToolError("file: the full path of a GLB, glTF, FBX or OBJ file on this PC.")
    path = os.path.expanduser(path.strip())
    if not os.path.isabs(path):
        raise ToolError("file: give the full path (e.g. C:/Users/you/Downloads/chair.glb).")
    if not os.path.isfile(path):
        raise ToolError(f"There is no file at {path}.")
    if os.path.splitext(path)[1].lower() not in FORMATS:
        raise ToolError("Nighty Blender imports GLB, glTF, FBX and OBJ files.")
    if os.path.getsize(path) > MAX_BYTES:
        raise ToolError("That file is over 2 GB.")
    return path


def source_of(obj):
    """The locked _SOURCE copy of a working object, or None."""
    if obj is None:
        return None
    name = obj.get("nighty_source")
    src = bpy.data.objects.get(name) if name else None
    return src if src is not None and src.get("nighty_source_of") else None


def is_source(obj):
    return obj is not None and bool(obj.get("nighty_source_of"))


def keep_source(obj):
    """Makes (once) the locked _SOURCE copy of `obj`. Returns its name."""
    have = source_of(obj)
    if have is not None:
        return have.name
    copy = obj.copy()
    copy.data = obj.data.copy()
    copy.name = obj.name + SOURCE_SUFFIX
    copy.data.name = copy.name
    for key in ("nighty_source", "nighty_finished", "nighty_verify"):
        if key in copy:
            del copy[key]
    copy["nighty_source_of"] = obj.name
    copy.hide_select = True
    copy.hide_render = True
    copy.lock_location = (True, True, True)
    copy.lock_rotation = (True, True, True)
    copy.lock_scale = (True, True, True)
    coll = bpy.data.collections.get(SOURCE_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(SOURCE_COLLECTION)
    coll.use_fake_user = True           # kept in the .blend, never in the scene (no step can pick it up)
    coll.objects.link(copy)
    copy.use_fake_user = True
    obj["nighty_source"] = copy.name
    return copy.name


def triage(info, obj):
    """What the file needs before it is game-ready: a list of plain findings, worst first."""
    out = []
    tris = int(info.get("triangles") or 0)
    if tris > ROBLOX_MESHPART_TRIS:
        out.append(f"{tris:,} triangles: too many for one Roblox MeshPart (20,000) and heavy for games; "
                   "make_game_ready (or mesh retopo / decimate) brings it to an exact count.")
    if info.get("non_manifold_edges"):
        out.append(f"{info['non_manifold_edges']:,} open or non-manifold edges: mesh cleanup closes what should "
                   "be closed (some models are open on purpose: planes, leaves).")
    if (info.get("loose_parts") or 0) > 1:
        out.append(f"{info['loose_parts']} separate pieces: fine for a kit, but floating crumbs should go "
                   "(mesh cleanup removes floaters).")
    if info.get("ngons"):
        out.append(f"{info['ngons']:,} faces with more than 4 corners: triangulated on export; retopo gives clean "
                   "faces.")
    if not info.get("uv_layers"):
        out.append("No UVs: textures can't be baked until it has them (mesh uv_unwrap; make_game_ready does it).")
    images = info.get("images") or []
    if not images:
        out.append("No textures in the file: the colors come from materials (texture assign_materials) or stay "
                   "plain.")
    big = [i for i in images if max(i.get("size") or [0]) > 2048]
    if big:
        out.append(f"{len(big)} texture(s) over 2K: baked down to the size you pick (Roblox shows 1K at most).")
    dims = info.get("original_dimensions") or [0, 0, 0]
    longest = max(dims) if dims else 0
    if longest > 50:
        out.append(f"It is {longest:.0f} m long as stored: probably centimeters. Import again with size (meters) "
                   "or scale it.")
    elif 0 < longest < 0.02:
        out.append(f"It is {longest * 1000:.1f} mm long as stored: give size (meters) to bring it to a real size.")
    if info.get("armatures"):
        out.append("It had a rig (armature): the mesh came in posed, without the rig (rigs are not kept).")
    if info.get("shape_keys"):
        out.append("It had shape keys: they are not kept by the game-ready steps.")
    if not out:
        out.append("Looks clean: closed, UVs and textures present. make_game_ready still sets the exact count.")
    return out


def _report_folder(name):
    from ..nighty.bake import safe_name
    if bpy.data.filepath:
        return os.path.join(os.path.dirname(bpy.data.filepath), "nighty_imports", safe_name(name))
    root = bpy.utils.user_resource("DATAFILES", path="nighty_blender", create=True)
    return os.path.join(root, "imports", safe_name(name))


def _append(blend, name):
    with bpy.data.libraries.load(blend, link=False) as (src, dst):
        names = [n for n in src.objects if n == name] or list(src.objects[:1])
        dst.objects = names
    obj = dst.objects[0]
    layer = getattr(bpy.context, "view_layer", None)
    coll = None
    if layer is not None and layer.active_layer_collection is not None:
        coll = layer.active_layer_collection.collection
    (coll or bpy.context.scene.collection).objects.link(obj)
    return obj


def _no_window():
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def import_steps(path, name=None, size=None, fixes=None, location=None):
    """Generator (a job's steps): the background import, then the append, the _SOURCE copy and the triage report.
    Returns the answer (dict)."""
    t0 = time.time()
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nighty", "io",
                          "import_file.py")
    tmp = tempfile.mkdtemp(prefix="nighty-import-")
    out_blend = os.path.join(tmp, "import.blend")
    opts = {"name": name or os.path.splitext(os.path.basename(path))[0], "size": float(size or 0)}
    for key in ("level", "facing", "metal"):
        if fixes and key in fixes:
            opts[key] = True
    argv = [bpy.app.binary_path, "-b", "--factory-startup", "--python", script, "--", path, out_blend,
            json.dumps(opts)]
    yield 0.05, "reading the file in a background Blender"
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                            encoding="utf-8", errors="replace", **_no_window())
    lines = []
    import threading

    def reader():
        for line in proc.stdout:
            lines.append(line.rstrip("\n"))
    th = threading.Thread(target=reader, daemon=True)
    th.start()
    spin = 0.05
    while proc.poll() is None:
        spin = min(0.85, spin + 0.002)
        time.sleep(0.01)
        yield spin, "reading the file in a background Blender"
    th.join(timeout=5)
    info = None
    for line in lines:
        if line.startswith("NIGHTY_RESULT "):
            info = json.loads(line[len("NIGHTY_RESULT "):])
        elif line.startswith("NIGHTY_ERROR "):
            raise ToolError(line[len("NIGHTY_ERROR "):])
    if info is None or not os.path.isfile(out_blend):
        tail = "\n".join(lines[-15:])
        raise ToolError(f"Blender could not import that file.\n{tail}")
    yield 0.9, "adding it to the scene"
    obj = _append(out_blend, info["object"])
    if location is not None:
        obj.location = tuple(location)
    else:
        cursor = bpy.context.scene.cursor.location
        obj.location = (cursor.x, cursor.y, 0.0)
    try:
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    except Exception:  # noqa: BLE001 - selection is a nicety
        pass
    source = keep_source(obj)
    try:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
    findings = triage(info, obj)
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read(64 * 1024 * 1024)).hexdigest()
    report = {"file": path, "sha256_first_64mb": digest, "imported": time.strftime("%Y-%m-%d %H:%M:%S"),
              "object": obj.name, "source": source, "facts": info, "triage": findings}
    folder = _report_folder(obj.name)
    os.makedirs(folder, exist_ok=True)
    report_file = os.path.join(folder, "triage.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    obj["nighty_triage"] = report_file
    keys = ("format", "vertices", "triangles", "quads", "ngons", "non_manifold_edges", "loose_parts",
            "parts_joined", "dimensions", "scale", "uv_layers", "materials", "images")
    return {"object": obj.name, "source": source, "facts": {k: info.get(k) for k in keys},
            "triage": findings, "report_file": report_file, "seconds": round(time.time() - t0, 1),
            "next": "look at it; then make_game_ready { object } after the options question, or the single steps"}


@action("import_model",
        "Imports a GLB / glTF / FBX / OBJ file as one object, keeps a locked <name>_SOURCE copy and writes a triage "
        "report. Slow: a job.",
        {"type": "object", "properties": {
            "file": {"type": "string", "description": "Full path of the model file."},
            "name": {"type": "string", "description": "Object name (default: the file name)."},
            "size": {"type": "number", "description": "Longest side in meters (default: as stored in the file)."},
            "fixes": {"type": "array", "items": {"type": "string", "enum": ["level", "facing", "metal"]},
                      "description": "Optional: level (stand it upright), facing (long side along X, front +X), "
                                     "metal (make a guessed metal map exactly 0/1)."},
            "location": {"type": "array", "items": {"type": "number"}}},
         "required": ["file"]},
        slow=True, level="tools", changes=True)
def import_model(ctx, args):
    path = check_file(args.get("file"))
    fixes = args.get("fixes") or []
    if not isinstance(fixes, list) or any(f not in ("level", "facing", "metal") for f in fixes):
        raise ToolError("fixes: a list of level, facing, metal")
    size = args.get("size")
    if size is not None and (not isinstance(size, (int, float)) or size <= 0):
        raise ToolError("size: meters, more than 0")

    def step_fn(job):
        res = yield from import_steps(path, args.get("name"), size, set(fixes), args.get("location"))
        from ._chain import push_undo
        push_undo("import " + res["object"])
        return res
    return ctx.start_job(step_fn, "import")
