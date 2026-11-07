# SPDX-License-Identifier: GPL-3.0-or-later
# make_game_ready: the whole pipeline in one job, following the person's options (asset_options), on a model that
# came from the person: a file they import (GLB / glTF / FBX / OBJ, through the import step, which keeps a locked
# _SOURCE copy and writes a triage report) or a mesh already in the scene. Steps: clean up, clean colors, the exact
# triangle count (retopology), parts, UVs, textures (the model's own textures re-baked onto the low poly, or real
# materials per part + bake), texture checks, export for the engine, mesh check and finish. Each step is the same
# step the AI can run by itself (its own undo step, its own report); this runs them in order on the job runner and
# stops at the first step that fails, saying which. No model is ever made here: Nighty Blender has no AI of its own.

import json
import os
import time

import bpy

from . import ToolError, image, text, action
from ._chain import StepFailed, run_tool
from ..nighty import presets

TEXTURE_SOURCES = ("auto", "own", "materials")
CHOICE_KEYS = ("mesh", "detail", "faces", "textures", "texture_type", "size", "made_for", "colors")


def _materials_for(parts, materials):
    """Without the model's own colors: one name for every part, or a list for the parts biggest first (the last
    one repeats)."""
    if isinstance(materials, str):
        return {p: materials for p in parts}
    order = sorted(parts, key=lambda n: -bpy.data.objects[n].dimensions.length)
    out = {}
    for i, p in enumerate(order):
        out[p] = materials[min(i, len(materials) - 1)]
    return out


def _high_textures(high):
    """(base color pixels (h, w, 3), metal (h, w) or None, uv layer name) of the dense original's own material."""
    import numpy as np
    from ..nighty.io.import_file import _source
    mat = next((m for m in high.data.materials if m is not None and m.use_nodes), None)
    if mat is None or not high.data.uv_layers:
        return None
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return None
    base = _source(bsdf.inputs["Base Color"])
    if not base or base[0] is None or not base[0].has_data:
        return None

    def pixels(img):
        w, h = img.size
        px = np.empty(w * h * img.channels, dtype=np.float32)
        img.pixels.foreach_get(px)
        return px.reshape(h, w, img.channels)
    bp = pixels(base[0])[..., :3]
    met = _source(bsdf.inputs["Metallic"])
    mp = None
    if met and met[0] is not None and met[0].has_data:
        m = pixels(met[0])
        mp = m[..., met[1] if met[1] is not None else 0]
    elif not bsdf.inputs["Metallic"].is_linked:
        mp = np.full(bp.shape[:2], float(bsdf.inputs["Metallic"].default_value), np.float32)
    layer = high.data.uv_layers.active or high.data.uv_layers[0]
    return bp, mp, layer.name


def _part_looks(parts, n=400, seed=0):
    """Each part's own color and metal share, read from the dense original's texture where the part sits:
    {part: ((r, g, b) sRGB, metal share)}, or None when there is no textured original to read."""
    import numpy as np
    from mathutils.bvhtree import BVHTree
    objs = [bpy.data.objects[p] for p in parts if p in bpy.data.objects]
    high = next((bpy.data.objects.get(o.get("nighty_high")) for o in objs if o.get("nighty_high")
                 and bpy.data.objects.get(o.get("nighty_high"))), None)
    if high is None:
        return None
    tex = _high_textures(high)
    if tex is None:
        return None
    base, metal, uvname = tex
    me = high.data
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    tv = np.empty(nt * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("vertices", tv)
    tl = np.empty(nt * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("loops", tl)
    co = np.empty(len(me.vertices) * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    mw = np.array(high.matrix_world)
    co = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
    uv = np.empty(len(me.loops) * 2, dtype=np.float64)
    me.uv_layers[uvname].data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    tv, tl = tv.reshape(-1, 3), tl.reshape(-1, 3)
    bvh = BVHTree.FromPolygons(co.tolist(), tv.tolist())
    h, w = base.shape[:2]
    rng = np.random.default_rng(seed)
    out = {}
    for o in objs:
        pm = o.data
        pm.calc_loop_triangles()
        k = len(pm.loop_triangles)
        if k == 0:
            continue
        pv = np.empty(k * 3, dtype=np.int64)
        pm.loop_triangles.foreach_get("vertices", pv)
        pa = np.empty(k, dtype=np.float64)
        pm.loop_triangles.foreach_get("area", pa)
        pco = np.empty(len(pm.vertices) * 3, dtype=np.float64)
        pm.vertices.foreach_get("co", pco)
        pw = np.array(o.matrix_world)
        pco = pco.reshape(-1, 3) @ pw[:3, :3].T + pw[:3, 3]
        pv = pv.reshape(-1, 3)
        pick = rng.choice(k, size=n, p=pa / pa.sum()) if pa.sum() > 0 else rng.integers(0, k, n)
        r1, r2 = rng.random(n), rng.random(n)
        flip = r1 + r2 > 1
        r1[flip], r2[flip] = 1 - r1[flip], 1 - r2[flip]
        tri = pco[pv[pick]]
        pts = tri[:, 0] + (tri[:, 1] - tri[:, 0]) * r1[:, None] + (tri[:, 2] - tri[:, 0]) * r2[:, None]
        cols, mets = [], []
        for pt in pts:
            loc, _nor, idx, _d = bvh.find_nearest(pt.tolist())
            if idx is None:
                continue
            a, b, c = co[tv[idx]]
            v0, v1, v2 = b - a, c - a, np.array(loc) - a
            d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
            d20, d21 = v2 @ v0, v2 @ v1
            den = d00 * d11 - d01 * d01 or 1e-12
            bv = (d11 * d20 - d01 * d21) / den
            bw = (d00 * d21 - d01 * d20) / den
            t = uv[tl[idx]]
            u = t[0] * (1 - bv - bw) + t[1] * bv + t[2] * bw
            x = int(np.clip(u[0] % 1.0 * w, 0, w - 1))
            y = int(np.clip(u[1] % 1.0 * h, 0, h - 1))
            cols.append(base[y, x])
            mets.append(metal[y, x] if metal is not None else 0.0)
        if not cols:
            continue
        cols, mets = np.array(cols), np.array(mets)
        share = float((mets > 0.5).mean())
        main = cols[(mets > 0.5) == (share >= 0.5)]
        out[o.name] = (tuple(float(c) for c in np.median(main, axis=0)), share)
    return out


def _choose_materials(parts, materials, looks_):
    """({part: name or {material, color}}, why per part). With the parts' own colors each part gets the material
    that fits it (from the person's list when given); without them, the list goes biggest part first."""
    from ..nighty.io import looks
    if not looks_:
        if not materials:
            raise ToolError("no textured original to read the parts' colors from: give materials (e.g. "
                            "['polymer', 'gunmetal', 'rubber'], biggest part first)")
        plan = _materials_for(parts, materials)
        return plan, {p: {"material": m, "why": "biggest part first (no colors to read)"} for p, m in plan.items()}
    cands = [materials] if isinstance(materials, str) else list(materials or [])
    flags = {}
    if any(c not in looks.REFERENCE for c in cands):
        from ..nighty.materials import library
        flags = {r["material"]: r["metallic"] for r in library.describe()}
    plan, report = {}, {}
    for p in parts:
        if p not in looks_:
            continue
        rgb, share = looks_[p]
        name, paint, why = looks.pick_material(rgb, share >= 0.5, cands or None, flags)
        if paint:
            plan[p] = {"material": name, "color": paint}
        else:   # b-color: natural materials take the part's own color (a red-brown wood), grain and wear kept
            plan[p] = {"material": name, "color": looks.rgb_hex(rgb), "force_tint": True}
        report[p] = {"material": name, "own_color": looks.rgb_hex(rgb), "metal_share": round(share, 2), "why": why}
        if paint:
            report[p]["color"] = paint
    for p in parts:                       # a part the reading missed: what the first read part got
        if p not in plan:
            plan[p] = next(iter(plan.values())) if plan else (cands[0] if cands else "polymer")
            report[p] = {"material": plan[p] if isinstance(plan[p], str) else plan[p]["material"],
                         "why": "no color read"}
    return plan, report


def _carry_regions(name):
    """After retopology: the clean-colors regions onto the low poly (a triangle decimate keeps them; quads are
    rebuilt). Returns how many regions it has (0: none)."""
    from ..nighty import colors as C
    low = bpy.data.objects.get(name)
    high = bpy.data.objects.get(low.get("nighty_high") or "") if low is not None else None
    if low is None or high is None or C.info(high) is None:
        return 0
    try:
        return C.carry_to(low, high, refresh=True)
    except Exception:  # noqa: BLE001 - only a preview / split help: never stop make_game_ready for it
        return 0


def _mark_parts(name):
    from ..nighty import colors as C
    o = bpy.data.objects.get(name)
    return C.mark_parts(o) if o is not None else 0


def _region_looks(parts):
    """Each part's color and metal from its clean-colors region: {part: (rgb, metal share)}, or None."""
    from ..nighty import colors as C
    objs = [bpy.data.objects[p] for p in parts if p in bpy.data.objects]
    looks_ = C.part_looks(objs)
    return {k: (v[0], v[1]) for k, v in looks_.items()} if looks_ else None


def _check_args(args):
    srcs = [k for k in ("file", "object") if args.get(k)]
    if not srcs:
        raise ToolError("Give the model: a file to import (file: a GLB / glTF / FBX / OBJ path) or a mesh in the scene "
                        "(object). Nighty Blender makes no models itself: they come from the person.")
    if len(srcs) > 1:
        raise ToolError("Give only one of file / object.")
    if args.get("file"):
        from .importing import check_file
        check_file(args["file"])
    if args.get("object"):
        o = bpy.data.objects.get(args["object"])
        if o is None or o.type != "MESH":
            raise ToolError(f"No mesh object named {args['object']!r}.")
        if o.get("nighty_source_of"):
            raise ToolError(f"{o.name} is a locked _SOURCE copy: work on {o['nighty_source_of']} instead.")
    src = args.get("texture_source", "auto")
    if src not in TEXTURE_SOURCES + ("ai",):
        raise ToolError("texture_source must be auto, own or materials")
    mats = args.get("materials")
    if mats is not None and not (isinstance(mats, str) or (isinstance(mats, list) and mats and
                                                           all(isinstance(m, str) for m in mats))):
        raise ToolError("materials: one material name, or a list (biggest part first)")
    choice = args.get("options") or {}
    if not isinstance(choice, dict):
        raise ToolError('options: an object, e.g. {"made_for": "roblox", "faces": 15000}')
    unknown = [k for k in choice if k not in CHOICE_KEYS]
    if unknown:
        raise ToolError(f"options: unknown {', '.join(unknown)} (use {', '.join(CHOICE_KEYS)})")
    try:
        opts = presets.resolve(choice, args.get("preset"))
    except ValueError as err:
        raise ToolError(str(err)) from None
    return opts


def ask_first(opts, args, tool_name="make_game_ready"):
    """Ask first: the pipeline starts only after the person answered the one question (asset_options). Without
    `confirmed: true` and the picks (options or a preset) this refuses, and the refusal IS the question to send.
    Returns None when the call may start."""
    picks = args.get("options") or {}
    if args.get("confirmed") is True and (picks or args.get("preset")):
        return None
    q = presets.question(opts)
    ok = json.dumps(presets.on_ok(opts, preset=args.get("preset")))
    if args.get("confirmed") is True:
        why = "Not started: confirmed needs the picks the person confirmed, in options. The question was:"
    else:
        why = "Not started: ask the person first. Send them this ONE message and wait for the answer:"
    return (f"{why}\n{q}\nOn OK, call {tool_name} again with the same file or object and {ok}; on changes, put "
            "their picks in options (faces is the exact triangle count), with confirmed: true.")


MAKE_SCHEMA = {"type": "object", "properties": {
    "file": {"type": "string", "description": "A model file on this PC to start from (GLB, glTF, FBX or OBJ; full "
                                              "path). It is imported first, with a locked _SOURCE copy."},
    "object": {"type": "string", "description": "Or a mesh already in the scene (imported before, or built in code "
                                                "when the person asked for that)."},
    "name": {"type": "string"},
    "size": {"type": "number", "description": "With file: longest side in meters (default: the file's own size)."},
    "preset": {"type": "string", "description": "e.g. 'Roblox prop', 'Realistic weapon' (asset_options lists them)"},
    "confirmed": {"type": "boolean", "description": "true only after the person answered the options question "
                                                    "(OK or their changes). Without it nothing starts: the answer is "
                                                    "the question to ask."},
    "options": {"type": "object", "description": "The picks the person confirmed (override the preset): mesh auto / "
                                                 "triangles / quads, faces (the exact triangle count), detail low / "
                                                 "medium / high, textures none / color / pbr / stylized, texture_type "
                                                 "baked / blender, size 1K / 2K / 4K, made_for roblox / unity / unreal "
                                                 "/ godot / gltf / blender, colors auto / clean / keep",
                "properties": {
                    "mesh": {"type": "string", "enum": ["auto", "triangles", "quads"]},
                    "detail": {"type": "string", "enum": ["low", "medium", "high"]},
                    "faces": {"type": "integer", "description": "The exact triangle count (used as given)."},
                    "textures": {"type": "string", "enum": ["none", "color", "pbr", "stylized"]},
                    "texture_type": {"type": "string", "enum": ["baked", "blender"]},
                    "size": {"type": "string", "enum": ["1K", "2K", "4K"]},
                    "made_for": {"type": "string", "enum": ["roblox", "unity", "unreal", "godot", "gltf", "blender"]},
                    "colors": {"type": "string", "enum": ["auto", "clean", "keep"],
                               "description": "the model's colors: auto (clean flat colors with crisp borders when "
                                              "the texture is mostly flat colors, else only metal / roughness per "
                                              "region), clean, keep"}}},
    "texture_source": {"type": "string", "enum": list(TEXTURE_SOURCES),
                       "description": "own: the model's own textures re-baked onto the low poly; materials: real "
                                      "library materials per part, picked from each part's own colors; auto "
                                      "(default): materials when materials are given, else own."},
    "materials": {"type": "array", "items": {"type": "string"},
                  "description": "Library materials to choose from, e.g. ['wood', 'brass'] (biggest part first)."},
    "split": {"type": "boolean", "description": "Split into parts (default: only for materials per part)."},
    "cleanup": {"type": "boolean", "description": "Clean the mesh first (weld, floaters, holes; default: yes for a "
                                                  "file, no for a scene mesh)."},
    "path": {"type": "string", "description": "Export folder (default next to the .blend / Blender's folder)."},
}}


@action("make_game_ready",
        "The full pipeline as one job on the person's model (an import or a scene mesh), after they answered the "
        "options question: cleanup, the exact triangle count, UVs, textures, checks, export, finish.",
        MAKE_SCHEMA, slow=True, level="tools", changes=True)
def make_game_ready(ctx, args):
    opts = _check_args(args)
    refusal = ask_first(opts, args)
    if refusal:
        raise ToolError(refusal)
    if not hasattr(ctx, "start_job"):
        raise ToolError("make_game_ready needs the addon's job runner.")
    src = args.get("texture_source", "auto")
    src = {"ai": "own"}.get(src, src)
    if src == "auto":
        src = "materials" if args.get("materials") else "own"
    split = bool(args.get("split", src == "materials"))
    choice = dict(args.get("options") or {})

    def step_fn(job):
        t_all = time.time()
        steps, out = [], {"options": {k: opts.get(k) for k in CHOICE_KEYS}, "texture_source": src}
        tex = opts["textures"] != "none"
        colors_on = tex and opts.get("colors", "auto") != "keep"
        keep_materials = opts.get("texture_type") == "blender" and src == "materials"
        bake_it = tex and not keep_materials
        clean_it = bool(args.get("cleanup", bool(args.get("file"))))   # an import: yes; a scene mesh: when asked
        plan = [("asset_options", 0.005), ("import_model", 0.08 if args.get("file") else 0.0),
                ("cleanup_mesh", 0.04 if clean_it else 0.0),
                ("clean_colors", 0.03 if colors_on else 0.0),
                ("retopo", 0.2), ("split_parts", 0.02 if split else 0.0), ("uv_unwrap", 0.08),
                ("assign_materials", 0.01 if tex and src == "materials" else 0.0),
                ("bake", 0.3 if bake_it else 0.0), ("verify_textures", 0.05 if bake_it else 0.0),
                ("export_asset", 0.1), ("verify_mesh", 0.01), ("finish_asset", 0.005)]
        total = sum(w for _, w in plan)
        spans, at = {}, 0.0
        for name_, w in plan:
            spans[name_] = (at / total, (at + w) / total)
            at += w

        def run(name_, a, label):
            t0 = time.time()
            s0, s1 = spans[name_]
            res = yield from run_tool(ctx, name_, a, s0, s1, label, parent=job)
            steps.append({"step": name_, "seconds": round(time.time() - t0, 1)})
            return res

        try:
            o = {"choice": choice}
            if args.get("preset"):
                o["preset"] = args["preset"]
            yield from run("asset_options", o, "options")
            # 1. the model: imported (with its locked _SOURCE copy and triage report), or the scene mesh
            if args.get("file"):
                a = {"file": args["file"]}
                for k in ("name", "size"):
                    if args.get(k):
                        a[k] = args[k]
                res = yield from run("import_model", a, "import")
                obj = res["object"]
                out["imported"] = {k: res.get(k) for k in ("object", "source", "triage", "report_file")
                                   if res.get(k) is not None}
            else:
                obj = args["object"]
                from .importing import keep_source
                out["source"] = keep_source(bpy.data.objects[obj])
            if clean_it:
                res = yield from run("cleanup_mesh", {"objects": [obj]}, "cleanup")
                out["cleanup"] = {k: res.get(k) for k in ("objects", "warnings") if res.get(k) is not None}
            # 1b. the model's colors made clean on the dense surface (before retopology, so the low poly keeps the
            # borders between colors as edges). Skipped when the model has no image texture.
            if colors_on:
                from ..nighty import colors as C
                o_ = bpy.data.objects.get(obj)
                if o_ is not None and C.textures_of(C.source_material(o_, 0)) is not None:
                    cc = {"objects": [obj], "mode": opts.get("colors", "auto"), "size": opts["size"]}
                    res = yield from run("clean_colors", cc, "clean colors")
                    out["colors"] = {k: res.get(k) for k in ("mode", "why", "regions", "fixed") if res.get(k)}
            # 2. topology (mesh type and face count from the options). Auto for a game engine = triangles: engines
            # draw triangles, the count is exact and hard edges stay crisp; quads only when asked or for Blender
            mode = opts.get("mesh", "auto")
            why = opts.get("mesh_note")
            if mode == "auto" and opts.get("made_for") not in (None, "blender"):
                mode = "triangles"
                why = (f"{presets.LABELS.get(opts['made_for'], opts['made_for'])} draws triangles; ask for quads if "
                       "you want to edit it further")
            res = yield from run("retopo", {"objects": [obj], "mode": mode, "faces": int(opts["faces"])},
                                 "retopology")
            row = (res.get("objects") or [{}])[0]
            out["retopo"] = {k: row.get(k) for k in ("result", "why", "faces", "triangles", "after")}
            out["mesh"] = _mesh_line(row, why)
            regions = _carry_regions(obj)
            # 3. parts: by color region when the clean-colors step found some, else where the shape says
            parts = [obj]
            if split:
                method = "attribute" if regions and _mark_parts(obj) else "auto"
                res = yield from run("split_parts", {"objects": [obj], "method": method}, "parts")
                parts = [p["name"] for rep in res.get("objects", []) for p in rep.get("parts", [])] or parts
            out["parts"] = parts
            # 4. UVs (one shared atlas, margins for the texture size)
            yield from run("uv_unwrap", {"objects": parts, "texture_size": opts["size"]}, "UVs")
            # 5. textures
            name = args.get("name") or obj.split("_part")[0]
            if tex and src == "materials":
                plan_, out["materials"] = _choose_materials(parts, args.get("materials"), _region_looks(parts) or
                                                            _part_looks(parts))
                yield from run("assign_materials", {"parts": plan_, "style": "stylized" if opts["textures"] ==
                                                    "stylized" else "pbr"}, "materials")
            if bake_it:
                b = {"parts": parts, "size": opts["size"], "name": name}
                if src == "own":
                    b["from_high"] = True
                res = yield from run("bake", b, "baking maps")
                out["maps"] = {"folder": res.get("folder"), "maps": res.get("maps")}
                if res.get("clean_colors"):
                    out["maps"]["clean_colors"] = res["clean_colors"]
                res = yield from run("verify_textures", {"parts": parts}, "texture checks")
                out["texture_check"] = {k: res.get(k) for k in ("passed", "failed", "fix") if k in res}
            # 6. export for the engine
            e = {"made_for": opts["made_for"], "parts": parts, "name": name}
            if args.get("path"):
                e["path"] = args["path"]
            res = yield from run("export_asset", e, f"export for {opts['made_for']}")
            out["export"] = {k: res.get(k) for k in ("folder", "files", "mesh", "warnings")}
            # 7. check and finish (finish refuses without a passing check: it is never forced here)
            vm = yield from run("verify_mesh", {"names": parts}, "mesh check")
            out["mesh_check"] = {k: vm.get(k) for k in ("pass", "errors", "warnings", "triangles")}
            tex_ok = (out.get("texture_check") or {}).get("passed", True)
            if vm.get("pass") and tex_ok:
                yield from run("finish_asset", {"names": parts, "notes": f"make_game_ready {name}"}, "finish")
                out["finished"] = True
            else:
                out["finished"] = False
                out["next"] = ("the mesh check failed: fix the errors (mesh cleanup / retopo), then check "
                               "{what: final}" if not vm.get("pass") else
                               "the texture check failed (see texture_check.fix): fix it and bake again, then check "
                               "{what: textures} and {what: final}")
        except StepFailed as err:
            raise ToolError(f"make_game_ready stopped at {err.tool}: {err.message} (the steps before it are done: "
                            f"{', '.join(s['step'] for s in steps) or 'none'}; fix it and run that step or "
                            "make_game_ready again)") from None
        out["steps"] = steps
        out["seconds"] = round(time.time() - t_all, 1)
        if out.get("finished"):
            out["next"] = ("look at it (look, material mode) and check {what: source} against the original; small "
                           "fixes with mesh / texture")
        blocks = [text(out)]
        pic = _check_picture() if bake_it else None
        if pic:
            blocks.append(image(pic))
        return blocks

    return ctx.start_job(step_fn, "make_game_ready")


def _mesh_line(row, why=None):
    """'Triangles, 15,000 - Roblox uses triangles; ...' / 'Quads, 7,400 (14,800 triangles in a game)'."""
    if row.get("result") == "quads":
        line = f"Quads, {row.get('faces') or 0:,} ({row.get('triangles') or 0:,} triangles in a game)"
    else:
        line = f"Triangles, {row.get('triangles') or row.get('faces') or 0:,}"
    return f"{line} - {why}" if why and row.get("result") != "quads" else line


def _check_picture():
    """The texture check's picture (albedo only + two lights), when there is one."""
    import json
    raw = bpy.context.scene.get("nighty_texture_report")
    if not raw:
        return None
    try:
        path = json.loads(raw).get("renders")
    except ValueError:
        return None
    if path and os.path.isfile(path):
        with open(path, "rb") as f:
            return f.read()
    return None
