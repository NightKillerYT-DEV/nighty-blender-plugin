# SPDX-License-Identifier: GPL-3.0-or-later
"""The options the person picks first, and presets that fill them in (nighty.presets).

    presets.menu()                                   # the questions, choices and presets (for the AI to ask)
    opts = presets.resolve({"textures": "stylized"}, preset="Stylized weapon")
    presets.store(opts, objects)                     # on the scene and on the parts
    presets.current()                                # what every step reads (topology reads mesh / detail / faces)

Stored as JSON in scene["nighty_options"] (the current asset) and on each part (obj["nighty_options"]).

Ask first: before making a model game-ready the AI sends the person ONE question with the picks filled in
(presets.question) and waits; make_game_ready refuses to start without `confirmed: true`, answering with that same
question (presets.on_ok gives the arguments to pass when the person says OK).
"""

import json

KEY = "nighty_options"

QUESTIONS = [
    ("mesh", "Mesh", ["auto", "triangles", "quads"], "auto"),
    ("detail", "Detail", ["low", "medium", "high"], "medium"),
    ("textures", "Textures", ["none", "color", "pbr", "stylized"], "pbr"),
    ("texture_type", "Texture type", ["baked", "blender"], "baked"),
    ("size", "Texture size", ["1K", "2K", "4K"], "2K"),
    ("made_for", "Made for", ["roblox", "unity", "unreal", "godot", "gltf", "blender"], "blender"),
    ("colors", "Model colors", ["auto", "clean", "keep"], "auto"),     # b-color (nighty.colors)
]
LABELS = {
    "auto": "Auto", "triangles": "Triangles", "quads": "Quads", "low": "Low poly", "medium": "Medium",
    "high": "High", "none": "None", "color": "Color only", "pbr": "PBR (realistic)", "stylized": "Stylized (hand-painted)",
    "baked": "Baked texture maps", "blender": "Blender materials", "roblox": "Roblox", "unity": "Unity",
    "unreal": "Unreal", "godot": "Godot", "gltf": "glTF",
    "clean": "Clean flat colors", "keep": "Keep the model's colors",
}
COLORS_NOTE = ("Auto: flat colors with crisp borders when the model's texture is mostly flat colors with ragged borders "
               "(stylized, plastic), its colors kept when it has real detail like wood grain (only metal / roughness "
               "fixed).")

MESH_NOTE = ("Triangles: the exact-count low poly, keeps the shape best (Roblox and game engines draw triangles; "
             "the default for Roblox). Quads: clean loops for editing further in Blender.")

# triangles per detail level (the topology step decimates / remeshes to these; 'faces' overrides)
FACES = {"low": 3000, "medium": 12000, "high": 40000}

# The exact triangle count an engine gets when the person picked neither a detail level nor a count (Roblox: one
# MeshPart takes 20,000 at most)
ENGINE_FACES = {"roblox": 15000}

# how the question names the picks (short)
_SAY_TEXTURES = {"none": "None", "color": "Color only", "pbr": "PBR", "stylized": "Hand-painted"}
_SAY_TYPE = {"baked": "baked", "blender": "Blender materials"}
_SAY_COLORS = {"auto": "Auto (sharp borders)", "clean": "Clean (sharp borders)", "keep": "Keep the model's"}
_SAY_ENGINE = {"roblox": "Roblox", "unity": "Unity", "unreal": "Unreal", "godot": "Godot", "gltf": "glTF",
               "blender": "just Blender"}

PRESETS = {
    "stylized_weapon": {
        "label": "Stylized weapon", "about": "hand-painted look, quads (triangles for Roblox), painted edge highlights",
        "options": {"mesh": "quads", "detail": "medium", "textures": "stylized", "texture_type": "baked",
                    "size": "2K"},
        "texturing": {"wear": 0.35, "dirt": 0.15, "stylize": {"edges": 0.7, "ao": 0.75, "gradient": 0.55,
                                                             "light": 0.6, "steps": 3, "roughness": 0.72}},
        "faces": {"low": 2500, "medium": 8000, "high": 25000},
    },
    "realistic_weapon": {
        "label": "Realistic weapon", "about": "PBR metal / polymer / wood, real edge wear, 2K, quads (triangles for "
                                                   "Roblox)",
        "options": {"mesh": "quads", "detail": "high", "textures": "pbr", "texture_type": "baked", "size": "2K"},
        "texturing": {"wear": 0.35, "dirt": 0.3},
        "faces": {"low": 4000, "medium": 15000, "high": 50000},
    },
    "roblox_prop": {
        "label": "Roblox prop", "about": "light mesh, PBR SurfaceAppearance maps at 1K, Roblox scale",
        "options": {"mesh": "triangles", "detail": "low", "textures": "pbr", "texture_type": "baked", "size": "1K",
                    "made_for": "roblox"},
        "texturing": {"wear": 0.3, "dirt": 0.25},
        "faces": {"low": 1500, "medium": 5000, "high": 15000},
    },
    "low_poly_mobile": {
        "label": "Low-poly mobile", "about": "very light mesh, color + simple maps, 1K",
        "options": {"mesh": "triangles", "detail": "low", "textures": "stylized", "texture_type": "baked",
                    "size": "1K"},
        "texturing": {"wear": 0.25, "dirt": 0.1, "stylize": {"edges": 0.6, "ao": 0.8, "steps": 2, "roughness": 0.8}},
        "faces": {"low": 800, "medium": 2000, "high": 5000},
    },
    "character": {
        "label": "Character", "about": "quads with clean loops, skin / cloth / leather, little wear",
        "options": {"mesh": "quads", "detail": "medium", "textures": "pbr", "texture_type": "baked", "size": "2K"},
        "texturing": {"wear": 0.12, "dirt": 0.1},
        "faces": {"low": 5000, "medium": 20000, "high": 60000},
    },
    "environment_piece": {
        "label": "Environment piece", "about": "rocks, walls, crates: more dirt and wear, triangles OK",
        "options": {"mesh": "auto", "detail": "medium", "textures": "pbr", "texture_type": "baked", "size": "2K"},
        "texturing": {"wear": 0.5, "dirt": 0.5},
        "faces": {"low": 2000, "medium": 10000, "high": 40000},
    },
}


def preset_key(name):
    if not name:
        return None
    k = str(name).strip().lower().replace("-", "_").replace(" ", "_")
    if k in PRESETS:
        return k
    for key, p in PRESETS.items():
        if p["label"].lower() == str(name).strip().lower():
            return key
    return None


def menu():
    """What the AI asks the person (short), with the defaults and the presets."""
    return {
        "ask": "Pick a preset or answer each (defaults in brackets).",
        "questions": [{"key": k, "question": q, "choices": [LABELS.get(c, c) for c in ch],
                       "values": ch, "default": d, **({"note": MESH_NOTE} if k == "mesh" else
                                                       {"note": COLORS_NOTE} if k == "colors" else {})}
                      for k, q, ch, d in QUESTIONS] +
                     [{"key": "faces", "question": "Exact face count (optional)", "values": "a number",
                       "default": None}],
        "presets": [{"key": k, "label": p["label"], "about": p["about"],
                     "sets": p["options"]} for k, p in PRESETS.items()],
    }


def _norm(key, value):
    if value is None:
        return None
    if key == "size":
        v = str(value).strip().upper().replace("PX", "")
        table = {"1024": "1K", "2048": "2K", "4096": "4K", "1K": "1K", "2K": "2K", "4K": "4K"}
        if v not in table:
            raise ValueError("size must be 1K, 2K or 4K")
        return table[v]
    v = str(value).strip().lower()
    for k, _, choices, _ in QUESTIONS:
        if k == key:
            for c in choices:
                if v in (c, LABELS.get(c, c).lower()) or LABELS.get(c, c).lower().startswith(v):
                    return c
            if key == "textures" and v in ("realistic", "pbr (realistic)"):
                return "pbr"
            if key == "textures" and v in ("hand-painted", "hand painted", "handpainted"):
                return "stylized"
            if key == "texture_type" and v in ("maps", "baked maps", "texture maps"):
                return "baked"
            if key == "made_for" and v in ("glb", "gltf2", "three", "ue", "ue5", "just blender"):
                return {"glb": "gltf", "gltf2": "gltf", "three": "gltf", "ue": "unreal", "ue5": "unreal",
                        "just blender": "blender"}[v]
            raise ValueError(f"{key} must be one of {', '.join(choices)}")
    raise ValueError(f"unknown option {key}")


def resolve(choice=None, preset=None):
    """Defaults <- preset <- the person's choices. Adds 'faces' (from detail unless exact), 'preset', and the
    texturing values (wear, dirt, style, stylize) every step uses."""
    out = {k: d for k, _, _, d in QUESTIONS}
    pk = preset_key(preset)
    if preset and pk is None:
        raise ValueError(f"unknown preset {preset!r}; presets: {', '.join(p['label'] for p in PRESETS.values())}")
    p = PRESETS.get(pk, {})
    out.update(p.get("options", {}))
    exact = None
    mesh_chosen = size_chosen = detail_chosen = False
    for k, v in (choice or {}).items():
        if k == "faces":
            if v not in (None, "", 0):
                try:
                    exact = int(str(v).replace(",", "").replace("_", "").strip())
                except ValueError:
                    raise ValueError("faces must be a number, e.g. 15000") from None
                if exact < 50:
                    raise ValueError("faces must be at least 50")
            continue
        if k in ("preset", "asset"):   # make_game_ready's own (not mesh / textures)
            continue
        n = _norm(k, v)
        if n is not None:
            out[k] = n
            mesh_chosen = mesh_chosen or (k == "mesh" and n != "auto")
            size_chosen = size_chosen or k == "size"
            detail_chosen = detail_chosen or k == "detail"
    # Roblox draws triangles: unless the person picked the mesh type themselves, its low poly is the exact-count
    # triangle one (it keeps the shape best for the count); presets' quads stay for every other engine
    if out["made_for"] == "roblox" and not mesh_chosen:
        out["mesh"] = "triangles"
        out["mesh_note"] = "Roblox uses triangles; ask for quads if you want to edit it further"
    # Roblox shows 1024 px per map at most: 1K unless the person picked a size (a bigger bake only costs time)
    if out["made_for"] == "roblox" and not size_chosen:
        out["size"] = "1K"
    out["mesh_chosen"] = mesh_chosen
    faces = p.get("faces", FACES)
    out["faces"] = exact or faces[out["detail"]]
    out["faces_exact"] = exact is not None
    if exact is None and not detail_chosen and not pk and out["made_for"] in ENGINE_FACES:
        out["faces"] = ENGINE_FACES[out["made_for"]]
        out["faces_note"] = f"{_SAY_ENGINE[out['made_for']]} default"
    out["preset"] = pk
    tex = dict(p.get("texturing", {"wear": 0.3, "dirt": 0.25}))
    tex["style"] = "stylized" if out["textures"] == "stylized" else "pbr"
    out["texturing"] = tex
    out["size_px"] = {"1K": 1024, "2K": 2048, "4K": 4096}[out["size"]]
    if out["made_for"] == "roblox" and out["size_px"] > 1024:
        out["note"] = "Roblox shows 1024 px at most per map; the export scales down"
    return out


def question(opts):
    """The ONE message the AI sends the person before make_game_ready, with the picks filled in, e.g.
    'Mesh: Triangles · Triangles: 15,000 (Roblox default; type any number) · Textures: PBR, baked · Size: 1K ·
    Made for: Roblox · Colors: Auto (sharp borders). OK, or change something?'
    The count is exact (make_game_ready uses it as given)."""
    engine = opts.get("made_for") or "blender"
    mesh = opts.get("mesh") or "auto"
    if mesh == "auto" and engine != "blender":
        mesh = "triangles"          # game engines get the exact-count triangle low poly
    hint = f"{opts['faces_note']}; type any number" if opts.get("faces_note") else "type any number"
    textures = opts.get("textures") or "pbr"
    parts = [f"Mesh: {LABELS.get(mesh, mesh)}",
             f"{'Triangles' if mesh == 'triangles' else 'Faces'}: {int(opts.get('faces') or 0):,} ({hint})"]
    if textures == "none":
        parts.append("Textures: None")
    else:
        parts += [f"Textures: {_SAY_TEXTURES.get(textures, textures)}, "
                  f"{_SAY_TYPE.get(opts.get('texture_type') or 'baked', 'baked')}", f"Size: {opts.get('size') or '2K'}"]
    parts.append(f"Made for: {_SAY_ENGINE.get(engine, engine)}")
    if textures != "none":
        parts.append(f"Colors: {_SAY_COLORS.get(opts.get('colors') or 'auto', 'Auto')}")
    return " · ".join(parts) + ". OK, or change something?"


def on_ok(opts, preset=None):
    """The make_game_ready arguments for when the person says OK to question(opts): every pick and the exact count
    inside options, and confirmed."""
    picks = {k: opts[k] for k in ("mesh", "textures", "texture_type", "size", "made_for", "colors")
             if opts.get(k) is not None}
    picks["faces"] = int(opts.get("faces") or FACES["medium"])
    out = {"options": picks}
    if preset:
        out["preset"] = preset
    out["confirmed"] = True
    return out


def form(opts):
    """The same question as a pick-list (for AI apps that show forms): one field per option, the smart defaults
    filled in. Choice fields: [value, label] pairs; number fields: minimum / maximum."""
    engine = opts.get("made_for") or "blender"
    mesh = opts.get("mesh") or "auto"
    if mesh == "auto" and engine != "blender":
        mesh = "triangles"
    fields = []
    meshes = [["triangles", "Triangles"], ["quads", "Quads"]] + ([["auto", "Auto"]] if mesh == "auto" else [])
    fields.append({"key": "mesh", "title": "Mesh", "default": mesh, "choices": meshes})
    hint = f"{opts['faces_note']}; type any number" if opts.get("faces_note") else "type any number"
    fields.append({"key": "faces", "title": "Triangles", "type": "integer", "default": int(opts.get("faces") or 0),
                   "minimum": 50, "maximum": 2000000, "description": f"The exact count ({hint})"})
    fields.append({"key": "textures", "title": "Textures", "default": opts.get("textures") or "pbr",
                   "choices": [[k, v] for k, v in _SAY_TEXTURES.items()]})
    fields.append({"key": "size", "title": "Texture size", "default": opts.get("size") or "2K",
                   "choices": [["1K", "1K"], ["2K", "2K"], ["4K", "4K"]]})
    fields.append({"key": "made_for", "title": "Made for", "default": engine,
                   "choices": [[k, v] for k, v in _SAY_ENGINE.items()]})
    fields.append({"key": "colors", "title": "Colors", "default": opts.get("colors") or "auto",
                   "choices": [[k, v] for k, v in _SAY_COLORS.items()]})
    return {"message": "Your options for this model (good defaults filled in). OK, or change any:",
            "fields": fields}


def store(opts, objects=(), scene=None):
    import bpy
    scene = scene or bpy.context.scene
    data = json.dumps(opts)
    scene[KEY] = data
    for o in objects:
        o[KEY] = data
    return opts


def current(obj=None, scene=None):
    """The stored options (the part's own, else the scene's, else the defaults)."""
    import bpy
    raw = None
    if obj is not None:
        raw = obj.get(KEY)
    if raw is None:
        scene = scene or bpy.context.scene
        raw = scene.get(KEY)
    if raw:
        try:
            return json.loads(raw)
        except ValueError:
            pass
    return resolve()


def maps_for(opts):
    """Which maps the bake makes for these options."""
    tex = opts.get("textures", "pbr")
    if tex == "none":
        return []
    if tex == "color":
        return ["base_color", "emission", "opacity"]
    if tex == "stylized":
        return ["base_color", "roughness", "metallic", "normal", "emission", "opacity"]
    return ["base_color", "roughness", "metallic", "normal", "ao", "emission", "opacity"]
