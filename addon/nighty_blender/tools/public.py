# SPDX-License-Identifier: GPL-3.0-or-later
# The 15 public tools: the only ones the AI sees (Nighty Vault shows them as blender_<name>). Most route to the
# working steps (ACTIONS) by `op` / `what`; their schemas are built from those steps' own schemas, so a step's options
# are always described where they are used.
#
#   status  scene  look  measure  check  reference  import  mesh  texture  make_game_ready  export  run_python  undo
#   job  guide
#
# Models come from the person: their file (import), a mesh already in the scene, or code only when the person asks.
# Nighty Blender has no AI model of its own and never generates anything.

import json

from . import ACTIONS, LEVELS, TOOLS, ToolError, action, content, text, tool  # noqa: F401
# the step modules register their actions first (the router schemas below are built from them)
from . import asset, checks, colors, core, fixes, importing, knowledge, reference, scene, texture, topology, verify  # noqa: F401,E501
from ._chain import push_undo

# MCP annotations per public tool (plugin.json carries them to Nighty Vault)
ANNOTATIONS = {
    "status": {"readOnlyHint": True, "destructiveHint": False},
    "scene": {"readOnlyHint": True, "destructiveHint": False},
    "look": {"readOnlyHint": True, "destructiveHint": False},
    "measure": {"readOnlyHint": True, "destructiveHint": False},
    "check": {"readOnlyHint": False, "destructiveHint": False},
    "reference": {"readOnlyHint": False, "destructiveHint": False},
    "import": {"readOnlyHint": False, "destructiveHint": False},
    "mesh": {"readOnlyHint": False, "destructiveHint": True},
    "texture": {"readOnlyHint": False, "destructiveHint": True},
    "make_game_ready": {"readOnlyHint": False, "destructiveHint": True},
    "export": {"readOnlyHint": False, "destructiveHint": False},
    "run_python": {"readOnlyHint": False, "destructiveHint": True},
    "undo": {"readOnlyHint": False, "destructiveHint": True},
    "job": {"readOnlyHint": False, "destructiveHint": False},
    "guide": {"readOnlyHint": True, "destructiveHint": False},
}

OBJECT_KEYS = ("objects", "names", "parts", "part", "object")


# ---------- helpers ----------

def _guard_sources(args):
    """No step may change or pick a locked _SOURCE copy by name."""
    import bpy
    names = []
    for key in OBJECT_KEYS:
        v = args.get(key)
        if isinstance(v, str):
            names.append(v)
        elif isinstance(v, list):
            names += [x for x in v if isinstance(x, str)]
        elif isinstance(v, dict):
            names += [x for x in v if isinstance(x, str)]
    for n in names:
        o = bpy.data.objects.get(n)
        if o is not None and o.get("nighty_source_of"):
            raise ToolError(f"{n} is the locked _SOURCE copy of {o['nighty_source_of']}: it is never changed. Work on "
                            f"{o['nighty_source_of']} (check {{what: source}} compares the two).")


def run_action(ctx, name, args, read_only=False):
    """Runs one step like the dispatcher would run a tool: the level gate, the _SOURCE guard, and ONE undo step for
    a change made at once (a job pushes its own when it ends)."""
    step = ACTIONS.get(name)
    if step is None:
        raise ToolError(f"The step {name!r} is not installed.")
    level = getattr(ctx, "level", "full")
    if level in LEVELS and LEVELS.index(step.level) > LEVELS.index(level):
        raise ToolError("That needs the %r safety level. The person has set %r in the Nighty panel in Blender."
                        % (step.level, level))
    if step.changes and not read_only:
        _guard_sources(args)
    result = step.fn(ctx, args)
    if step.changes and not (isinstance(result, dict) and set(result) == {"job"}):
        label = getattr(ctx, "undo_label", None) or name.replace("_", " ")
        push_undo(str(label).replace("AI: ", "", 1))
    return result


def _merge_schemas(op_map, op_key, op_help):
    """One schema for a router: the op enum, then every option of every step, typed when all steps agree."""
    props = {op_key: {"type": "string", "enum": list(op_map), "description": op_help}}
    seen = {}
    required_by = {}
    for op, name in op_map.items():
        schema = ACTIONS[name].input_schema
        for key, spec in (schema.get("properties") or {}).items():
            seen.setdefault(key, []).append((op, spec))
        for key in schema.get("required") or []:
            required_by.setdefault(key, []).append(op)
    for key, uses in seen.items():
        ops = [op for op, _ in uses]
        types = {json.dumps({k: v for k, v in spec.items() if k != "description"}, sort_keys=True)
                 for _, spec in uses}
        descs = []
        for _, spec in uses:
            d = spec.get("description")
            if d and d not in descs:
                descs.append(d)
        where = "" if len(ops) == len(op_map) else f"({', '.join(ops)}) "
        need = f"Required for {', '.join(required_by[key])}. " if key in required_by else ""
        if len(types) == 1:
            merged = {k: v for k, v in uses[0][1].items() if k != "description"}
        else:
            merged = {}
            kinds = sorted({spec.get("type") for _, spec in uses if spec.get("type")})
            if kinds:
                merged["type"] = kinds if len(kinds) > 1 else kinds[0]
        text_ = (where + need + " / ".join(descs)).strip()
        if text_:
            merged["description"] = text_[:400]
        props[key] = merged
    return {"type": "object", "properties": props, "required": [op_key]}


def _op(args, key, aliases):
    raw = str(args.get(key) or "").strip().lower()
    if raw not in aliases:
        raise ToolError(f"{key}: one of {', '.join(sorted({k for k in aliases if not k.endswith('_mesh')}))}.")
    rest = {k: v for k, v in args.items() if k != key}
    return aliases[raw], rest


# ---------- status / scene / look / measure ----------

@tool("status",
      "Nighty Blender in the person's Blender: pairing state, Blender and addon versions, the safety level the "
      "person set (tools / safe Python / full Python; only they can change it, in Blender's N panel), the open "
      ".blend file and the jobs still running. A good first call.",
      {"type": "object", "properties": {}, "additionalProperties": False}, changes=False)
def status_tool(ctx, args):
    out = ACTIONS["status"].fn(ctx, {})
    try:
        from .. import runtime
        session = runtime.get_session()
    except Exception:  # noqa: BLE001 - plain tests
        session = None
    if session is not None:
        out["paired"] = bool(getattr(session, "paired", False))
        if getattr(session, "client_name", None):
            out["client"] = session.client_name
        server = getattr(session, "server", None)
        if server is not None and getattr(server, "port", None):
            out["port"] = server.port
    out["models_come_from"] = "the person's file (import), a scene mesh, or code only when the person asks"
    return out


@tool("scene", ACTIONS["scene_info"].description, ACTIONS["scene_info"].input_schema, changes=False)
def scene_tool(ctx, args):
    return run_action(ctx, "scene_info", args, read_only=True)


@tool("look",
      ACTIONS["look"].description.replace("then wait_job", "then job { action: wait }"),
      ACTIONS["look"].input_schema, changes=False)
def look_tool(ctx, args):
    return run_action(ctx, "look", args, read_only=True)


@tool("measure", ACTIONS["measure"].description, ACTIONS["measure"].input_schema, changes=False)
def measure_tool(ctx, args):
    return run_action(ctx, "measure", args, read_only=True)


# ---------- check ----------

CHECKS = {"mesh": "verify_mesh", "textures": "verify_textures", "source": "compare_source",
          "roundtrip": "roundtrip", "roblox": "roblox_ready", "final": "finish_asset"}
CHECK_ALIASES = dict(CHECKS, **{"verify_mesh": "verify_mesh", "verify_textures": "verify_textures",
                                "finish": "finish_asset", "finish_asset": "finish_asset",
                                "roblox_ready": "roblox_ready", "compare": "compare_source"})


@tool("check",
      "Checks, by what: mesh (counts, open / non-manifold edges, floating parts, flipped normals, UV overlap and "
      "stretch; pass, errors, warnings), textures (the baked maps: blur, metallic 0/1, baked-in light, unbaked "
      "pixels), source (the model against its locked _SOURCE copy: size, triangles, surface drift), roundtrip "
      "(export, read back, compare: what the engine gets), roblox (the Roblox gate: 20,000 triangles per part, UVs, "
      "1024 px maps, scale, an export), final (marks the asset finished; refuses unless the last mesh check passed "
      "and nothing changed since, or a stated reason).",
      _merge_schemas(CHECKS, "what", "What to check."), changes=False)
def check_tool(ctx, args):
    name, rest = _op(args, "what", CHECK_ALIASES)
    return run_action(ctx, name, rest)


# ---------- reference / import ----------

@tool("reference", ACTIONS["reference_sheet"].description, ACTIONS["reference_sheet"].input_schema, changes=False)
def reference_tool(ctx, args):
    return run_action(ctx, "reference_sheet", args)


@tool("import",
      "Brings the person's model file in (GLB, glTF, FBX or OBJ, full path) as one object through a background "
      "Blender, keeps a locked <name>_SOURCE copy (never changed; check { what: source } compares against it) and "
      "writes a triage report (triangles, open edges, loose parts, UVs, textures, scale, rigs: what it needs). "
      "Optional fixes: level, facing, metal. A job: job { action: wait }.",
      ACTIONS["import_model"].input_schema, changes=False)
def import_tool(ctx, args):
    return run_action(ctx, "import_model", args)


# ---------- mesh / texture ----------

MESH_OPS = {"cleanup": "cleanup_mesh", "decimate": "decimate", "retopo": "retopo", "uv_unwrap": "uv_unwrap",
            "lods": "make_lods", "split_parts": "split_parts", "fix_shading": "fix_shading"}
MESH_ALIASES = dict(MESH_OPS, **{"cleanup_mesh": "cleanup_mesh", "make_lods": "make_lods", "uvs": "uv_unwrap",
                                 "unwrap": "uv_unwrap", "split": "split_parts", "shading": "fix_shading"})


@tool("mesh",
      "Mesh steps on the working model (never on a _SOURCE copy), by op: cleanup (weld, floaters, holes, manifold, "
      "normals, size, on the ground), decimate (an exact triangle count, keeps sharp edges, seams, symmetry), "
      "retopo (quads, triangles or auto; exact counts), uv_unwrap (one shared atlas, seams from sharp edges), lods "
      "(_LOD1.. copies), split_parts (by loose pieces, creases, planes or color regions), fix_shading (normals out, "
      "smooth with sharp edges by angle). Each is one undo step; the slow ones answer with a job id "
      "(job { action: wait }).",
      _merge_schemas(MESH_OPS, "op", "The mesh step."), changes=False)
def mesh_tool(ctx, args):
    name, rest = _op(args, "op", MESH_ALIASES)
    return run_action(ctx, name, rest)


TEXTURE_OPS = {"bake": "bake", "clean_colors": "clean_colors", "stylize": "stylize", "decal": "add_decal",
               "assign_materials": "assign_materials", "fix_seams": "fix_seams"}
TEXTURE_ALIASES = dict(TEXTURE_OPS, **{"add_decal": "add_decal", "materials": "assign_materials",
                                       "seams": "fix_seams", "colors": "clean_colors"})


@tool("texture",
      "Texture steps, by op: bake (the parts' materials or the model's own textures into clean maps, one texture "
      "set; a job), clean_colors (an imported model's ragged texture colors made flat and crisp per region, or only "
      "metal / roughness fixed when it has real detail; a job), stylize (hand-painted look), decal (a sharp image "
      "or text projected on a part), assign_materials (real library materials per part: steel, wood, rubber...; "
      "CC0 texture downloads only after the person agrees), fix_seams (texture colors grown past UV edges: no lines "
      "along seams).",
      _merge_schemas(TEXTURE_OPS, "op", "The texture step."), changes=False)
def texture_tool(ctx, args):
    name, rest = _op(args, "op", TEXTURE_ALIASES)
    return run_action(ctx, name, rest)


# ---------- make_game_ready / export ----------

def _make_schema():
    schema = json.loads(json.dumps(ACTIONS["make_game_ready"].input_schema))
    schema["properties"]["ask"] = {"type": "boolean", "description": "Only the options question for these picks "
                                                                      "(with options / preset; starts nothing)."}
    schema["properties"]["menu"] = {"type": "boolean", "description": "The options menu and presets."}
    return schema


@tool("make_game_ready",
      "The full pipeline as one job on the person's model: a file (imported first, with a locked _SOURCE copy and a "
      "triage report) or a mesh in the scene. Cleanup, clean colors, the exact triangle count, parts, UVs, "
      "textures (its own re-baked, or library materials per part), texture check, export for the engine, mesh "
      "check, finish. Ask first: without confirmed: true and the picks it starts nothing and answers with the ONE "
      "question to send the person (ask: true gives it at once); on their OK call again with their picks in "
      "options and confirmed: true. A job (job { action: wait }, minutes). Fixes after: mesh / texture.",
      _make_schema(), changes=False)
def make_game_ready_tool(ctx, args):
    if args.get("menu") or args.get("ask"):
        a = {"ask": bool(args.get("ask"))}
        if args.get("options"):
            a["choice"] = args["options"]
        if args.get("preset"):
            a["preset"] = args["preset"]
        return run_action(ctx, "asset_options", a, read_only=True)
    return run_action(ctx, "make_game_ready", {k: v for k, v in args.items() if k not in ("ask", "menu")})


@tool("export", ACTIONS["export_asset"].description, ACTIONS["export_asset"].input_schema, changes=False)
def export_tool(ctx, args):
    return run_action(ctx, "export_asset", args)


# ---------- run_python ----------

@tool("run_python", ACTIONS["run_python"].description, ACTIONS["run_python"].input_schema, level="safe",
      changes=False)
def run_python_tool(ctx, args):
    return run_action(ctx, "run_python", args)


# ---------- undo ----------

CHECKPOINT = "AI: checkpoint "


def undo_names():
    """The undo history as [(name, is_active)], oldest first ([] when it can't be read)."""
    try:
        import bpy
        from ..dispatch import _capture
        wm = bpy.context.window_manager
    except Exception:  # noqa: BLE001
        return []
    out = _capture(lambda: wm.print_undo_steps()) or ""
    rows = []
    for line in out.splitlines()[1:]:
        head, _, rest = line.partition("]")
        if "name='" in line:
            rows.append((line.split("name='", 1)[1].rsplit("'", 1)[0], "*" in head))
    return rows


@tool("undo",
      "Takes back the AI's own changes only (steps named 'AI: ...'); it stops at the person's own work and never "
      "undoes it. No arguments: the last AI step. steps: several. checkpoint: a named mark to come back to; to: "
      "back to that mark. list: the recent steps.",
      {"type": "object", "properties": {
          "steps": {"type": "integer", "description": "How many AI steps to take back (1-50, default 1)."},
          "checkpoint": {"type": "string", "description": "Set a named checkpoint now (nothing is undone)."},
          "to": {"type": "string", "description": "Undo the AI's steps back to this checkpoint."},
          "list": {"type": "boolean", "description": "List the recent undo steps."}},
       "additionalProperties": False},
      changes=False)
def undo_tool(ctx, args):
    import bpy
    from ..dispatch import active_undo_name
    if args.get("list"):
        rows = undo_names()[-30:]
        return {"steps": [{"name": n, "ai": n.startswith("AI:"), "current": a} for n, a in rows]}
    if args.get("checkpoint"):
        name = str(args["checkpoint"]).strip()[:60]
        try:
            bpy.ops.ed.undo_push(message=CHECKPOINT + name)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Could not set the checkpoint: {exc}")
        return {"checkpoint": name}
    target = (CHECKPOINT + str(args["to"]).strip()[:60]) if args.get("to") else None
    if target and not any(n == target for n, _ in undo_names()):
        raise ToolError(f"There is no checkpoint {args['to']!r} in the undo history.")
    count = 50 if target else max(1, min(50, int(args.get("steps") or 1)))
    undone = []
    for _ in range(count):
        name = active_undo_name()
        if name is None:
            if undone:
                break
            raise ToolError("Could not read the undo history, so nothing was undone (to be safe).")
        if target and name == target:
            break
        if not name.startswith("AI:"):
            if undone:
                break
            raise ToolError("The most recent step is the person's own work (%r), not the AI's, so nothing was "
                            "undone." % name[:80])
        try:
            bpy.ops.ed.undo()
        except Exception as exc:  # noqa: BLE001
            if undone:
                break
            raise ToolError("Undo failed: %s" % exc)
        undone.append(name)
    return {"undone": undone, "at": active_undo_name()}


# ---------- job ----------

@tool("job",
      "Slow work (imports, bakes, renders, exports, make_game_ready) runs as a job: the call answers with "
      "{ job: id } at once. action wait: wait up to 45 s for it, then its result (or its progress: wait again); "
      "cancel: stop it; get: its state now; list: every job.",
      {"type": "object", "properties": {
          "action": {"type": "string", "enum": ["wait", "cancel", "get", "list"]},
          "id": {"type": "string", "description": "The job id (wait, cancel, get)."},
          "seconds": {"type": "number", "description": "wait: how long, up to 45 (default 45)."}},
       "required": ["action"], "additionalProperties": False},
      changes=False)
def job_tool(ctx, args):
    act = args.get("action")
    jobs = getattr(ctx, "jobs", None)
    if act == "list":
        if jobs is None or not hasattr(jobs, "jobs"):
            return {"jobs": []}
        return {"jobs": [j.snapshot() for j in jobs.jobs.values()]}
    job_id = args.get("id")
    if not isinstance(job_id, str) or not job_id:
        raise ToolError("Give the job `id`.")
    if act not in ("wait", "cancel", "get"):
        raise ToolError("action: wait, cancel, get or list")
    snap = ctx.job_snapshot(job_id) if hasattr(ctx, "job_snapshot") else None
    if snap is None and hasattr(ctx, "job_snapshot"):
        raise ToolError("There is no job %r." % job_id)
    if act == "get":
        return snap
    if act == "cancel":
        return {"cancelled": bool(ctx.cancel_job(job_id)), "state": snap.get("state") if snap else None}
    seconds = args.get("seconds")
    seconds = 45 if not isinstance(seconds, (int, float)) else max(1, min(45, int(seconds)))
    return ctx.wait_job(job_id, seconds)   # parks the answer in the dispatcher; never blocks Blender


# ---------- guide ----------

def api_lookup(path, limit=60):
    """Blender's own API description for a type, a property or an operator (from this Blender's RNA)."""
    import bpy
    p = (path or "").strip()
    if p.startswith("bpy."):
        p = p[4:]
    if p.startswith("ops."):
        parts = p.split(".")
        if len(parts) != 3:
            raise ToolError("An operator looks like bpy.ops.mesh.primitive_cube_add.")
        try:
            op = getattr(getattr(bpy.ops, parts[1]), parts[2])
            rna = op.get_rna_type()
        except (AttributeError, KeyError):
            raise ToolError(f"No operator {p!r} in Blender {bpy.app.version_string}.") from None
        return {"operator": "bpy." + p, "description": rna.description,
                "properties": [_prop(x) for x in rna.properties if x.identifier != "rna_type"][:limit]}
    if p.startswith("types."):
        p = p[6:]
    name, _, member = p.partition(".")
    cls = getattr(bpy.types, name, None)
    if cls is None:
        close = [n for n in dir(bpy.types) if name.lower() in n.lower()][:20]
        raise ToolError(f"No type {name!r} in Blender {bpy.app.version_string}. Close: {', '.join(close) or 'none'}.")
    rna = cls.bl_rna
    if member:
        prop = rna.properties.get(member)
        if prop is not None:
            return {"type": name, "property": _prop(prop)}
        fn = rna.functions.get(member)
        if fn is not None:
            return {"type": name, "function": _func(fn)}
        raise ToolError(f"{name} has no {member!r}.")
    base = rna.base.identifier if rna.base else None
    return {"type": name, "base": base, "description": rna.description,
            "properties": [_prop(x) for x in rna.properties if x.identifier != "rna_type"][:limit],
            "functions": [_func(f) for f in rna.functions][:limit],
            "blender": bpy.app.version_string}


def _prop(x):
    row = {"name": x.identifier, "type": x.type.lower()}
    if x.description:
        row["about"] = x.description[:160]
    if getattr(x, "is_readonly", False):
        row["readonly"] = True
    if x.type == "ENUM":
        row["values"] = [i.identifier for i in x.enum_items][:30]
    if x.type == "POINTER" and getattr(x, "fixed_type", None) is not None:
        row["of"] = x.fixed_type.identifier
    if x.type == "COLLECTION" and getattr(x, "fixed_type", None) is not None:
        row["of"] = x.fixed_type.identifier
    if getattr(x, "array_length", 0):
        row["length"] = x.array_length
    return row


def _func(f):
    return {"name": f.identifier, "about": (f.description or "")[:160],
            "args": [p.identifier for p in f.parameters if not p.is_output],
            "returns": [p.identifier for p in f.parameters if p.is_output]}


@tool("guide",
      "Know-how. No arguments: the guide topics. topic: one guide (start with workflow: import first). examples: "
      "words to find verified example scripts (only when the person asked for a model built in code). api: this "
      "Blender's own API for a type, property or operator (bpy.types.Object, Mesh.vertices, "
      "bpy.ops.mesh.primitive_cube_add): look names up instead of guessing.",
      {"type": "object", "properties": {
          "topic": {"type": "string", "description": "A guide topic (workflow, blender-api, topology, texturing, ...)."},
          "examples": {"type": "string", "description": "Words for the example search, e.g. 'wooden crate'."},
          "style": {"type": "string", "enum": ["realistic", "stylized"], "description": "examples: only this style."},
          "limit": {"type": "integer", "description": "examples: 1-5 (default 2)."},
          "image": {"type": "boolean", "description": "examples: add the best match's render."},
          "api": {"type": "string", "description": "A bpy type, property or operator."}},
       "additionalProperties": False},
      changes=False)
def guide_tool(ctx, args):
    if args.get("api"):
        return api_lookup(args["api"])
    if args.get("examples"):
        a = {"query": args["examples"]}
        for k in ("style", "limit", "image"):
            if args.get(k) is not None:
                a[k] = args[k]
        return run_action(ctx, "search_examples", a, read_only=True)
    return run_action(ctx, "get_guide", {"topic": args.get("topic") or ""}, read_only=True)


for _name, _ann in ANNOTATIONS.items():
    if _name in TOOLS:
        TOOLS[_name].annotations = _ann
