# SPDX-License-Identifier: GPL-3.0-or-later
# clean_colors: an imported model's colors made clean on its dense surface (nighty.colors): flat colors with crisp
# borders when its texture is mostly flat colors with ragged borders (models from 3D generators often are), or only
# metal / roughness per region when it has real texture detail (wood grain). make_game_ready runs it by itself before
# retopology (option colors: auto | clean | keep); this step is for running it again, forcing a mode, or taking it
# back.

import os

import bpy

from . import ToolError, action
from ._chain import push_undo
from ..nighty import colors as C
from ..nighty import presets

MODES = ["auto", "clean", "gentle", "keep", "restore"]


def target_of(obj):
    """The dense surface to work on: the hidden bake source once retopology made a low poly, else the object."""
    src = obj.get("nighty_bake_source")
    if isinstance(src, str):
        src = bpy.data.objects.get(src)
    if src is None and obj.get("nighty_high"):
        src = bpy.data.objects.get(obj["nighty_high"])
    try:
        return src if src is not None and src.type == "MESH" else obj
    except ReferenceError:
        return obj


def _targets(args):
    names = args.get("objects")
    if names:
        objs = []
        for n in names:
            o = bpy.data.objects.get(n)
            if o is None or o.type != "MESH":
                raise ToolError(f"No mesh object named {n!r}.")
            objs.append(o)
    else:
        objs = [o for o in bpy.context.selected_objects if o.type == "MESH"]
        if not objs:
            objs = [o for o in bpy.context.scene.objects if o.type == "MESH" and (o.get("nighty_imported") or o.get("nighty_generated"))
                    and o.get("nighty_role") != "bake_source"]
    if not objs:
        raise ToolError("No imported model to clean: pass objects.")
    return objs


def short(rep):
    """The report for the AI: mode, why, the regions (color, what it looks like, metal, roughness, share)."""
    out = {"object": rep.get("object"), "mode": rep.get("mode"), "why": rep.get("why")}
    if rep.get("palette"):
        out["regions"] = [{"color": r["color"], "looks_like": r["kind"], "metal": r["metal"],
                           "roughness": r["roughness"], "share": r["share"]} for r in rep["palette"]]
    d = {k: v for k, v in (rep.get("dropped") or {}).items() if v}
    if d:
        out["fixed"] = d
    if rep.get("hue_from_picture"):
        out["hue_from_picture"] = rep["hue_from_picture"]
    if rep.get("seconds"):
        out["seconds"] = rep["seconds"].get("total")
    return out


@action(
    "clean_colors",
    "An imported model's colors made clean on its 3D surface (no seams): when its texture is mostly flat colors "
    "(stylized / painted / plastic) it gets flat colors with crisp borders, no dark halos, stray bands or painted "
    "highlights; with real texture detail (wood grain) the colors stay and only metal (exactly 0 / 1) and roughness "
    "are fixed per region. make_game_ready does this by itself (option colors); bake again after it. mode: auto "
    "(default), clean, gentle, keep, restore (the model's own material back). Slow: a job (seconds).",
    {"type": "object", "properties": {
        "objects": {"type": "array", "items": {"type": "string"},
                    "description": "Models (default: selected, else every imported model)."},
        "mode": {"type": "string", "enum": MODES},
        "size": {"type": "string", "enum": ["1K", "2K", "4K"],
                 "description": "The final texture size (default from asset_options): details it can't show go."},
        "picture": {"type": "string", "description": "A picture of the object (full path, optional): fixes colors "
                                                     "that drifted in the texture (white gone lavender)."}}},
    slow=True, level="tools", changes=True)
def clean_colors(ctx, args):
    mode = args.get("mode", "auto")
    if mode not in MODES:
        raise ToolError(f"mode: one of {', '.join(MODES)}")
    objs = _targets(args)
    size = args.get("size") or presets.current().get("size", "2K")
    picture = args.get("picture")
    if picture and not os.path.isfile(picture):
        raise ToolError(f"picture: no file {picture!r}")
    pairs = [(o, target_of(o)) for o in objs]
    if mode == "restore":
        done = [o.name for o, t in pairs if C.restore(t) | (C.restore(o) if o is not t else False)]
        if done:
            push_undo("clean_colors restore")
        return {"restored": done, "next": "bake again to carry it onto the low poly" if done else
                "nothing to restore"}
    for o, t in pairs:
        if C.textures_of(C.source_material(t, 0)) is None:
            raise ToolError(f"{o.name}: no image texture to clean (its material's base color is not an image)")

    def step_fn(job):
        reports = []
        n = len(pairs)
        for i, (o, t) in enumerate(pairs):
            gen = C.clean_steps(t, mode, size=size, picture=picture)
            while True:
                if getattr(job, "cancelled", False):
                    gen.close()
                    return {"cancelled": True}
                try:
                    f, msg = next(gen)
                except StopIteration as stop:
                    rep = stop.value
                    break
                except ValueError as err:
                    raise ToolError(f"{o.name}: {err}") from None
                yield (i + f) / n, f"{o.name}: {msg}"
            if t is not o:
                C.carry_to(o, t, refresh=True)
            if o.get("nighty_bake"):
                o["nighty_bake_stamp"] = ""     # the baked maps are stale now
            rep = short(rep)
            rep["object"] = o.name
            if o.get("nighty_bake"):
                rep["next"] = "bake again (bake from_high) to carry the clean colors onto the low poly"
            reports.append(rep)
        push_undo("clean_colors")
        return reports[0] if len(reports) == 1 else {"objects": reports}

    jid = ctx.start_job(step_fn, "clean_colors") if hasattr(ctx, "start_job") else None
    if jid is None:
        return C.run(step_fn(type("J", (), {"cancelled": False})()))
    return jid if isinstance(jid, dict) else {"job": jid}
