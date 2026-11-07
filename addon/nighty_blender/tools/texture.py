# SPDX-License-Identifier: GPL-3.0-or-later
"""Texturing tools: options, materials per part, decals, stylize, bake, engine exports, texture checks.
The work lives in nighty.materials / nighty.bake / nighty.export / nighty.presets; these are thin wrappers."""

import json
import os

import bpy

from . import action, text, image, ToolError
from ..nighty import presets
from ..nighty.materials import library

SIZES = ["1K", "2K", "4K"]
MAP_KEYS = ["base_color", "roughness", "metallic", "normal", "ao", "emission", "opacity"]
ENGINES = ["roblox", "unity", "unreal", "godot", "gltf", "blender"]


# ----------------------------------------------------------------------------------------------- helpers

def _is_helper(o, names_high):
    n = o.name
    return (o.name in names_high or n.endswith(("_high", ".high", "_HP", "_hp")) or o.get("nighty_lod_of")
            or ("_LOD" in n and n.rpartition("_LOD")[2].isdigit()) or o.get("nighty_decal_of"))


def _parts(args, key="parts", required=False):
    names = args.get(key)
    if isinstance(names, str):
        names = [names]
    if names:
        objs, missing = [], []
        for n in names:
            o = bpy.data.objects.get(n)
            if o is None or o.type != "MESH":
                missing.append(n)
            else:
                objs.append(o)
        if missing:
            raise ToolError(f"no mesh named {', '.join(missing)}")
        return objs
    if required:
        raise ToolError(f"give {key}")
    highs = {o.get("nighty_high") for o in bpy.data.objects if o.get("nighty_high")}
    sel = [o for o in bpy.context.selected_objects if o.type == "MESH" and not _is_helper(o, highs)]
    if sel:
        return sel
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.visible_get() and not _is_helper(o, highs)]
    if not objs:
        raise ToolError("no mesh parts in the scene")
    return objs


def _name(args, objs):
    if args.get("name"):
        return args["name"]
    coll = bpy.context.view_layer.active_layer_collection.collection
    if coll is not bpy.context.scene.collection and all(o.name in coll.objects for o in objs):
        return coll.name
    return objs[0].name if len(objs) == 1 else (objs[0].name.split("_")[0] or "Asset")


def _job(ctx, gen, label):
    """Hands the steps to the addon's jobs (ctx.start_job(step_fn, label): step_fn(job) is a generator yielding
    (progress, message) and returning the result; job.cancelled stops it) and returns {'job': id} at once. Without
    a jobs framework (tests, scripts) the steps run to the end here."""
    start = getattr(ctx, "start_job", None)
    if not callable(start):
        from ..nighty.bake.job import run_steps
        return run_steps(gen)

    def step_fn(job):
        while True:
            if getattr(job, "cancelled", False):
                gen.close()          # stops the background Blender and cleans up
                return {"cancelled": True}
            try:
                p = next(gen)
            except StopIteration as stop:
                return stop.value
            yield p

    jid = start(step_fn, label)
    return jid if isinstance(jid, dict) else {"job": jid}


def _label(ctx, label):
    if hasattr(ctx, "undo_label"):
        try:
            ctx.undo_label = f"AI: {label}"
        except AttributeError:
            pass


def _opts():
    return presets.current()


def _size(v, default):
    v = v or default
    from ..nighty.bake.maps import size_of
    try:
        return size_of(v)
    except ValueError as e:
        raise ToolError(str(e))


# ----------------------------------------------------------------------------------------------- options

@action("asset_options",
      "Before make_game_ready: ask: true with your best guesses in choice (e.g. made_for) gives the ONE question "
      "to send the person; wait for the answer, then make_game_ready with their picks and confirmed: true. No "
      "arguments: the menu and presets. preset / choice alone: stores the picks on the parts.",
      {"type": "object", "properties": {
          "ask": {"type": "boolean", "description": "true: only the question for these picks (stores nothing)"},
          "preset": {"type": "string", "description": "e.g. 'Realistic weapon', 'Roblox prop'"},
          "choice": {"type": "object", "description": "mesh, detail, faces, textures, texture_type, size, made_for, "
                                                     "colors",
                     "properties": {
                         "mesh": {"type": "string", "enum": ["auto", "triangles", "quads"]},
                         "detail": {"type": "string", "enum": ["low", "medium", "high"]},
                         "faces": {"type": "integer", "description": "exact face count"},
                         "textures": {"type": "string", "enum": ["none", "color", "pbr", "stylized"]},
                         "texture_type": {"type": "string", "enum": ["baked", "blender"]},
                         "size": {"type": "string", "enum": SIZES},
                         "made_for": {"type": "string", "enum": ENGINES},
                         "colors": {"type": "string", "enum": ["auto", "clean", "keep"],
                                    "description": "the model's own colors: auto / clean flat colors / keep"}}},
          "parts": {"type": "array", "items": {"type": "string"}, "description": "default: selected or all"}}},
      level="tools", changes=True)
def asset_options(ctx, args):
    if args.get("ask") or (not args.get("preset") and not args.get("choice")):
        try:
            opts = presets.resolve(args.get("choice"), args.get("preset"))
        except ValueError as e:
            raise ToolError(str(e))
        ask = {"question": presets.question(opts),
               "on_ok": presets.on_ok(opts, preset=args.get("preset")),
               "form": presets.form(opts),
               "next": "Send the person `question` as ONE message and wait. OK: make_game_ready with on_ok (plus the "
                       "file or object); changes: their picks in options, confirmed: true."}
        if args.get("ask"):
            return ask
        menu = presets.menu()
        stored = bpy.context.scene.get(presets.KEY)
        if stored:
            menu["current"] = json.loads(stored)
        menu.update(ask)
        return menu
    try:
        opts = presets.resolve(args.get("choice"), args.get("preset"))
    except ValueError as e:
        raise ToolError(str(e))
    try:
        objs = _parts(args)
    except ToolError:
        objs = []
    presets.store(opts, objs)
    _label(ctx, "asset options")
    return {"stored": opts, "parts": [o.name for o in objs]}


# ----------------------------------------------------------------------------------------------- materials

@action("assign_materials",
      "A real material per part from the smart library (steel, gunmetal, painted_metal, polymer, rubber, wood, "
      "glass, emissive...). Edge wear and cavity dirt come from the real geometry; metallic is 0 or 1. Instant; "
      "assign again to change one part. parts: {} lists the library.",
      {"type": "object", "properties": {
          "parts": {"type": "object", "additionalProperties": {},
                    "description": "{part: 'gunmetal'} or {part: {material, color '#rrggbb', force_tint (tint "
                                   "wood / leather too), wear, dirt, roughness}}"},
          "style": {"type": "string", "enum": ["pbr", "stylized"]},
          "wear": {"type": "number", "description": "0 clean .. 1 battered (default from the options)"},
          "dirt": {"type": "number", "description": "0 .. 1 cavity dirt"},
          "cc0": {"type": "boolean", "description": "use CC0 photo textures (Poly Haven) where the library has them"},
          "cc0_agree": {"type": "boolean", "description": "the person said yes to CC0 downloads"},
          "cc0_folder": {"type": "string", "description": "where the person wants them (optional)"}},
       "required": ["parts"]},
      level="tools", changes=True)
def assign_materials(ctx, args):
    from ..nighty import materials
    from ..nighty.materials import cc0
    parts = args.get("parts") or {}
    if not parts:
        return {"materials": library.describe(), "styles": ["pbr", "stylized"]}
    opts = _opts()
    tex = opts.get("texturing", {})
    style = args.get("style") or tex.get("style", "pbr")
    wear = args.get("wear", tex.get("wear", 0.3))
    dirt = args.get("dirt", tex.get("dirt", 0.25))
    note, cc0_sets, download = None, {}, None
    if args.get("cc0"):
        if args.get("cc0_agree"):
            cc0.agree(args.get("cc0_folder"))
        if not cc0.consent():
            raise ToolError("CC0 textures download from Poly Haven into a folder on this computer. Ask the person "
                            "first; if they agree call again with cc0_agree: true (and cc0_folder if they chose one).")
        kinds = {library.resolve(v if isinstance(v, str) else (v or {}).get("material")) for v in parts.values()}
        missing = []
        for k in kinds:
            if k in library.CC0:
                src, aid = library.CC0[k]
                have = cc0.cached(src, aid)
                if have:
                    cc0_sets[k] = have
                else:
                    missing.append((src, aid))
        if missing:
            download = _job(ctx, cc0.download_steps(missing), "Downloading CC0 textures")
            note = "CC0 textures are downloading; procedural detail for now. Call assign_materials again after it."
    try:
        rows = materials.assign(parts, style=style, wear=wear, dirt=dirt, cc0_sets=cc0_sets,
                                stylize_opts=tex.get("stylize"))
    except ValueError as e:
        raise ToolError(str(e))
    for k, files in cc0_sets.items():
        cc0.tag_images(files, f"https://polyhaven.com/a/{library.CC0[k][1]}")
    _label(ctx, "assign materials")
    out = {"parts": rows, "next": "bake for maps (or look in Cycles: wear and dirt show in Cycles and after bake)"}
    if note:
        out["note"] = note
        out["download"] = download
    return out


@action("add_decal",
      "Puts a sharp image or text on a part as a projection (never painted by AI). It follows its projector "
      "(an Image empty you can move) and bakes in at full resolution. remove: a decal's name takes it off.",
      {"type": "object", "properties": {
          "part": {"type": "string"},
          "image": {"type": "string", "description": "a PNG / JPG path (or give text)"},
          "text": {"type": "string"},
          "side": {"type": "string", "enum": ["front", "back", "left", "right", "top", "bottom"]},
          "offset": {"type": "array", "items": {"type": "number"}, "description": "[right, up] meters from center"},
          "at": {"type": "array", "items": {"type": "number"}, "description": "a world point instead of side"},
          "size": {"type": "number", "description": "width in meters"},
          "rotation": {"type": "number", "description": "degrees"},
          "color": {"type": "string", "description": "text color '#rrggbb'"},
          "outline": {"type": "number", "description": "text outline, share of its height (0.06)"},
          "outline_color": {"type": "string"},
          "font": {"type": "string", "description": "a .ttf / .otf path"},
          "roughness": {"type": "number"},
          "metallic": {"type": "integer", "enum": [0, 1]},
          "name": {"type": "string"},
          "remove": {"type": "string", "description": "name of a decal to remove"}}},
      level="tools", changes=True)
def add_decal(ctx, args):
    from ..nighty.materials import decals
    if args.get("remove"):
        try:
            decals.remove_decal(args["remove"])
        except ValueError as e:
            raise ToolError(str(e))
        _label(ctx, "remove decal")
        return {"removed": args["remove"]}
    obj = bpy.data.objects.get(args.get("part") or "")
    if obj is None or obj.type != "MESH":
        raise ToolError("part: the mesh to put the decal on")
    try:
        res = decals.add_decal(
            obj, image_path=args.get("image"), text=args.get("text"), name=args.get("name"),
            side=args.get("side", "front"), at=args.get("at"), offset=args.get("offset") or (0.0, 0.0),
            size=args.get("size"), rotation=args.get("rotation", 0.0), color=args.get("color", "#ffffff"),
            outline=args.get("outline", 0.0), outline_color=args.get("outline_color", "#111111"),
            font=args.get("font"), roughness=args.get("roughness", 0.45), metallic=args.get("metallic", 0))
    except ValueError as e:
        raise ToolError(str(e))
    _label(ctx, f"decal {res['name']}")
    return res


@action("stylize",
      "Hand-painted look on the parts: gradients, painted light in bands, painted edge highlights, AO in the "
      "colors on purpose, flat roughness. Instant; bake to make it maps.",
      {"type": "object", "properties": {
          "parts": {"type": "array", "items": {"type": "string"}},
          "gradient": {"type": "number", "description": "0..1 darker low, lighter high"},
          "light": {"type": "number", "description": "0..1 painted light strength"},
          "light_dir": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z] toward the light"},
          "steps": {"type": "integer", "description": "toon bands (0 = smooth)"},
          "edges": {"type": "number", "description": "0..1 edge highlights"},
          "ao": {"type": "number", "description": "0..1 AO painted in"},
          "cavity": {"type": "number", "description": "0..1 dark cavities"},
          "roughness": {"type": "number"},
          "saturation": {"type": "number", "description": "1 = as is"}}},
      level="tools", changes=True)
def stylize(ctx, args):
    from ..nighty.materials import stylize as st
    objs = _parts(args)
    given = {k: args[k] for k in ("gradient", "light", "light_dir", "steps", "edges", "ao", "cavity", "roughness",
                                  "saturation") if k in args}
    base = dict(_opts().get("texturing", {}).get("stylize") or {})
    base.update(given)
    rows = st.stylize(objs, base)
    if not any(r["stylized"] for r in rows):
        raise ToolError("no Principled materials on these parts: assign_materials first")
    _label(ctx, "stylize")
    return {"parts": rows, "options": st.make_options(base)}


# ----------------------------------------------------------------------------------------------- bake / export / check

@action("bake",
      "Bakes the parts' materials into clean maps (base color, roughness, metallic 0/1, normal, AO, emission) in a "
      "background Blender, packs all parts into one texture set and puts a clean material on them. Slow: a job.",
      {"type": "object", "properties": {
          "parts": {"type": "array", "items": {"type": "string"}},
          "name": {"type": "string"},
          "size": {"type": "string", "enum": SIZES},
          "maps": {"type": "array", "items": {"type": "string", "enum": MAP_KEYS}},
          "high": {"type": "object", "additionalProperties": {"type": "string"},
                   "description": "{low part: high poly} for normal / AO from a high poly"},
          "from_high": {"type": "boolean",
                        "description": "Colors / roughness / metallic from the high poly's own textures (an imported "
                                       "model's) instead of the parts' materials"},
          "device": {"type": "string", "enum": ["auto", "cpu", "gpu"]}}},
      slow=True, level="tools", changes=True)
def bake(ctx, args):
    from ..nighty import bake as bk
    objs = _parts(args)
    opts = _opts()
    size = _size(args.get("size"), opts.get("size", "2K"))
    maps_wanted = args.get("maps") or presets.maps_for(opts)
    if not maps_wanted:
        raise ToolError("the options say Textures: None; nothing to bake")
    high = None
    if args.get("high"):
        high = {}
        for lo_name, hi_name in args["high"].items():
            h = bpy.data.objects.get(hi_name)
            if h is None or bpy.data.objects.get(lo_name) is None:
                raise ToolError(f"high: no object {hi_name if h is None else lo_name}")
            high[lo_name] = h
    device = {"cpu": "CPU", "gpu": "GPU"}.get(args.get("device", "auto"), "auto")
    try:
        gen = bk.bake_steps(objs, size=size, maps_wanted=maps_wanted, name=_name(args, objs), high=high,
                            device=device, style=opts.get("texturing", {}).get("style", "pbr"),
                            transfer=bool(args.get("from_high")))
    except ValueError as e:
        raise ToolError(str(e))
    if args.get("from_high"):    # b-color: models with clean colors get their color maps painted exactly
        from ..nighty.colors import paint
        gen = paint.after_bake(gen, objs)
    return _job(ctx, _summarize_bake(gen), f"Bake {size}px")


def _summarize_bake(gen):
    res = yield from gen
    m = res["manifest"]
    return {"folder": res["folder"], "maps": m["maps"], "size": m["size"], "material": res.get("material"),
            "seconds": m["seconds"], "atlas": m["atlas"], "unbaked_pixels": sum(m["unbaked_pixels"].values()),
            "warnings": m["warnings"], "next": "check {what: textures}, then export",
            **({"clean_colors": res["clean_colors"]} if res.get("clean_colors") else {})}


@action("export_asset",
      "Exports for an engine with the right scale, axes, normal-map format and channel packing: roblox "
      "(SurfaceAppearance maps, studs), unity (URP / HDRP maps), unreal (ORM, DirectX normal, cm), godot / gltf "
      "(.glb), blender (.blend). Bakes first when needed. Slow: a job.",
      {"type": "object", "properties": {
          "made_for": {"type": "string", "enum": ENGINES},
          "path": {"type": "string", "description": "output folder (default next to the .blend)"},
          "parts": {"type": "array", "items": {"type": "string"}},
          "name": {"type": "string"},
          "size": {"type": "string", "enum": SIZES},
          "format": {"type": "string", "enum": ["fbx", "obj", "glb"], "description": "override (Roblox: fbx / obj)"},
          "join": {"type": "boolean", "description": "one mesh (default: yes for Roblox)"}}},
      slow=True, level="tools", changes=True)
def export_asset(ctx, args):
    from ..nighty import export as ex
    objs = _parts(args)
    opts = _opts()
    made_for = args.get("made_for") or opts.get("made_for")
    if not made_for:
        raise ToolError("made_for: roblox, unity, unreal, godot, gltf or blender")
    size = _size(args.get("size"), opts.get("size", "2K"))
    name = _name(args, objs)
    style = opts.get("texturing", {}).get("style", "pbr")

    def make():
        return ex.export_steps(objs, made_for, path=args.get("path"), name=name, size=size,
                               maps_wanted=presets.maps_for(opts) or None, fmt=args.get("format"),
                               join=args.get("join"), style=style)
    from ..nighty.colors import paint
    if paint.stale_and_wanted(objs, made_for, size, name):
        # b-color: a stale clean-colors bake is baked and painted again first (else the export's own bake would
        # bring the ray-cast colors back)
        gen = paint.export_repainted(objs, size, presets.maps_for(opts) or None, style, name, make)
        return _job(ctx, _mark_export(gen, objs, made_for), f"Export for {made_for}")
    try:
        gen = make()
    except ValueError as e:
        raise ToolError(str(e))
    return _job(ctx, _mark_export(gen, objs, made_for), f"Export for {made_for}")


def _mark_export(gen, objs, made_for):
    """Remembers the export on the objects (check { what: roblox } looks for it)."""
    res = yield from gen
    folder = res.get("folder") if isinstance(res, dict) else None
    for o in objs:
        try:
            o[f"nighty_export_{made_for}"] = str(folder or "")
        except ReferenceError:
            pass
    return res


@action("verify_textures",
      "Checks the baked maps: blur, metallic exactly 0/1, lighting baked into the colors, unbaked "
      "pixels, seams, normal map; renders albedo-only and two lights. The final check reads the report. Slow: a job.",
      {"type": "object", "properties": {
          "parts": {"type": "array", "items": {"type": "string"}},
          "renders": {"type": "boolean", "description": "default true"}}},
      slow=True, level="tools", changes=False)
def verify_textures(ctx, args):
    from ..nighty import bake as bk
    objs = _parts(args)
    opts = _opts()
    try:
        gen = bk.verify_steps(objs, style=opts.get("texturing", {}).get("style"), made_for=opts.get("made_for"),
                              renders=args.get("renders", True))
    except ValueError as e:
        raise ToolError(str(e))
    return _job(ctx, _verify_content(gen), "Texture checks")


def _verify_content(gen):
    rep = yield from gen
    short = {"passed": rep["passed"], "failed": rep["failed"],
             "checks": {c["name"]: c["value"] for c in rep["checks"]}, "current": rep.get("current", True)}
    if not rep["passed"]:
        short["fix"] = {c["name"]: c["note"] for c in rep["checks"] if not c["ok"]}
    blocks = [text(short)]
    if rep.get("renders") and os.path.exists(rep["renders"]):
        with open(rep["renders"], "rb") as f:
            blocks.append(image(f.read()))
        blocks.append(text("Picture: albedo only | light A | light B, front and back. The albedo must show no "
                           "shading; edges crisp; metal only where metal is."))
    return blocks
