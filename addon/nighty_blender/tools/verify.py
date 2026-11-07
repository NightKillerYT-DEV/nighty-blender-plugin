# SPDX-License-Identifier: GPL-3.0-or-later
# Quality gate: verify_mesh (the JSON report) and finish_asset (refuses until the last verify of those objects
# passed and nothing changed since, or the AI states a reason).

import json
import time

import bpy

from . import ToolError, text, action
from ..nighty import check
from .scene import NAMES, targets

# name -> {"fingerprint", "pass", "time", "errors", "warnings", "triangles"} (this Blender session)
LAST = {}

KEEP = ("faces", "triangles_total", "quads", "tris", "ngons", "shells", "size", "volume")
PROBLEMS = ("boundary_edges", "non_manifold_edges", "loose_edges", "loose_verts", "zero_area_faces",
            "zero_length_edges", "duplicate_verts", "flipped_faces", "inverted_shells", "ngons_not_flat")


def compact(rep):
    """The per-object rows with the numbers that matter (zero problem counts left out)."""
    rows = {}
    for name, r in rep["objects"].items():
        row = {k: r[k] for k in KEEP if k in r}
        for k in PROBLEMS:
            if r.get(k):
                row[k] = r[k]
        if isinstance(r.get("self_intersections"), int) and r["self_intersections"]:
            row["self_intersections"] = r["self_intersections"]
        if r.get("poles"):
            row["poles"] = r["poles"]
        if r.get("symmetry"):
            row["symmetry"] = r["symmetry"]
        if r.get("faces_per_m2"):
            row["faces_per_m2"] = r["faces_per_m2"]
        if r.get("uv"):
            row["uv"] = {k: r[k] for k in ("uv_coverage", "uv_overlap", "uv_stretch", "uv_density_spread",
                                           "uv_flipped_tris", "uv_outside_0_1") if k in r}
        else:
            row["uv"] = False
        if not r.get("scale_applied", True):
            row["scale"] = r["scale"]
        if r.get("modifiers"):
            row["modifiers"] = r["modifiers"]
        rows[name] = row
    return rows


@action("verify_mesh",
      "Checks models: face counts (tris / quads / ngons), open and non-manifold edges, loose and floating parts, "
      "zero-area faces, flipped normals, inside-out parts, symmetry, applied scale, UV overlap and stretch, poles, "
      "density. Returns pass, errors (fix these) and warnings. The final check needs a passing one.",
      {"type": "object", "properties": {
          "names": NAMES,
          "allow_open": {"type": "boolean", "description": "Open surfaces are fine (planes, leaves, cards)."},
          "allow_floating": {"type": "array", "items": {"type": "string"},
                             "description": "Objects that may float on purpose (a hanging lamp, a hover part)."},
          "budget": {"type": "integer", "description": "Most triangles allowed over all objects."},
          "symmetry": {"type": "string", "enum": ["X", "Y", "Z", "none"], "description": "Mirror axis to score (X)."},
          "full": {"type": "boolean", "description": "Every number per object (default: the ones that matter)."}}},
      changes=False)
def verify_mesh(ctx, args):
    objs = targets(args)
    sym = args.get("symmetry") or "X"
    allow = [n for n in (args.get("allow_floating") or []) if n in bpy.data.objects]
    try:
        rep = check.verify(objs, allow_open=bool(args.get("allow_open")), budget=args.get("budget"),
                           symmetry=None if sym == "none" else sym, allow_floating=allow)
    except ValueError as error:
        raise ToolError(str(error))
    now = time.time()
    dg = bpy.context.evaluated_depsgraph_get()
    own = lambda e, name: e.startswith(name + ": ")
    floating = {f["object"] for f in rep["floating"]}
    shared = [e for e in rep["errors"] if not any(own(e, o.name) for o in objs) and "floating parts" not in e]
    for o in objs:
        mine = [e for e in rep["errors"] if own(e, o.name)] + shared
        if o.name in floating:
            mine.append(f"{o.name}: has floating parts")
        LAST[o.name] = {"fingerprint": check.fingerprint(o, dg), "pass": not mine, "time": now,
                        "errors": mine, "triangles": rep["objects"].get(o.name, {}).get("triangles_total")}
    out = {"pass": rep["pass"], "errors": rep["errors"], "warnings": rep["warnings"], "triangles": rep["triangles"],
           "objects": rep["objects"] if args.get("full") else compact(rep)}
    if rep["floating"]:
        out["floating"] = rep["floating"]
    if rep["pass"]:
        out["next"] = "measure against the reference, look (matcap + wireframe), then check { what: final }"
    return out


@action("finish_asset",
      "Marks objects as a finished asset. Refuses unless the last mesh check of every one of them passed and "
      "nothing changed since; or give a reason (why it is fine as it is), which is kept with the report.",
      {"type": "object", "properties": {
          "names": {"type": "array", "items": {"type": "string"}, "description": "The asset's objects."},
          "reason": {"type": "string", "description": "Why finishing without a passing check is right."},
          "notes": {"type": "string", "description": "What it is, for the record (one line)."}},
       "required": ["names"]},
      changes=True)
def finish_asset(ctx, args):
    names = args.get("names") or []
    if not names:
        raise ToolError("names: list the asset's objects.")
    objs = targets({"names": names})
    reason = (args.get("reason") or "").strip()
    dg = bpy.context.evaluated_depsgraph_get()
    problems = []
    for o in objs:
        rec = LAST.get(o.name)
        if rec is None:
            problems.append(f"{o.name}: not checked yet (run check {{what: mesh}})")
        elif rec["fingerprint"] != check.fingerprint(o, dg):
            problems.append(f"{o.name}: changed since the last mesh check (run it again)")
        elif not rec["pass"]:
            problems.append(f"{o.name}: the last mesh check failed ({'; '.join(rec['errors'][:2]) or 'see it'})")
    if problems and not reason:
        raise ToolError("Not finished: " + " | ".join(problems) + ". Fix it and check { what: mesh } again, or give a reason.")
    record = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "objects": [o.name for o in objs],
              "triangles": sum((LAST.get(o.name) or {}).get("triangles") or 0 for o in objs),
              "verified": not problems, "notes": (args.get("notes") or "")[:300]}
    if problems:
        record["reason"] = reason[:500]
        record["open_points"] = problems
    for o in objs:
        o["nighty_asset"] = json.dumps(record)
    log = bpy.data.texts.get("Nighty assets") or bpy.data.texts.new("Nighty assets")
    log.write(json.dumps(record) + "\n")
    if hasattr(ctx, "undo_label"):
        try:
            ctx.undo_label = "AI: finish " + ", ".join(record["objects"])[:60]
        except AttributeError:
            pass
    msg = "Finished" + ("" if not problems else " with a reason") + f": {', '.join(record['objects'])}" + \
          f" ({record['triangles']} triangles). The report is kept on the objects and in the text 'Nighty assets'."
    return [text(msg), text(record)]
