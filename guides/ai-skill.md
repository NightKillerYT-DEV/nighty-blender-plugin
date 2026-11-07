# Nighty Blender skill

Rules for AI apps that work in Blender through Nighty Blender (the blender_* tools of Nighty Vault): models come from the person's file, an import, or code only when the person asks; everything is checked before it is called done. Nighty Blender has no AI model and never generates one.

## Where it comes from

The Nighty Blender plugin in Nighty Vault adds the blender_* tools to Nighty Vault's own AI connection and installs this skill (its "Install AI skills" button). The Blender add-on is paired once with a 6-digit code (Nighty Vault's Blender card shows it; the person types it in Blender's N panel, Nighty tab). Nighty Vault must be open for the tools to work.

## The first rule

- A model comes from the person: a file (GLB, glTF, FBX or OBJ) -> `blender_import`; a mesh already in the scene; or code, only when the person asks for it in their own words ("build it in code", "model it by hand").
- No file and no request for code: ask for the file's full path. Never build a model in code by yourself.
- Edits on a model (move a part, recolor, a decal, fix a spot): the step tools. `blender_run_python` only for a small fix the person asked for.

## How to make a model game-ready

1. `blender_status` and `blender_scene`.
2. `blender_import { file }` (a job: `blender_job { action: "wait", id }`). Read the triage report to the person: triangles, open edges, loose pieces, UVs, textures, scale. A locked `<name>_SOURCE` copy is kept.
3. `blender_look` at it.
4. Ask first, every time: `blender_make_game_ready { ask: true, options: { made_for } }` with your best guesses (Roblox gets 15,000 triangles and 1K maps). Send its `question` to the person as ONE message, as it is, and wait.
5. `blender_make_game_ready { object (or file), options: their picks, confirmed: true }`; then `blender_job { action: "wait", id }` until done (each wait is up to 45 s).
6. `blender_look { mode: "material", views: ["hero"] }` and `blender_check { what: "source" }`; tell the person the `mesh` line. Fix single steps with `blender_mesh` / `blender_texture` (ops), `blender_export` for another engine, `blender_check { what: "roblox" }` before Roblox.
7. Every change is one undo step named "AI: ..."; `blender_undo` takes back only your own steps. The safety level (tools / safe Python / full Python) is set by the person in Blender only.

## Only when the person asks you to build in code

- Guides, read once then: `blender_guide { topic }` with workflow (its last part), library, topology, hard-surface, props, organic, texturing, blender-api. Blender API names: `blender_guide { api: "bpy.types.Object" }`.
- `blender_guide { examples, style }` for something close; adapt its code in `blender_run_python` (`import nighty as n`). Safe level (the default): modelling only (`bpy`, `bmesh`, `mathutils`, `math`, `random`, `nighty`); files, other programs, the internet and settings are off. A refused call says the person can switch to 'full' in Blender's Nighty panel.
- The loop: one part or a few (`n.settings(detail, size)` first; meters, Z up, front -Y), `blender_check { what: "mesh" }` (fix every error), `blender_measure`, `blender_look`, fix; done: the mesh check on all parts, the studio look, `blender_check { what: "final" }`.
- The bar: silhouette first, secondary forms that step out of each other, a few strong details, value contrast, bevels on every visible edge (never 8-sided visible cylinders), real proportions, parts touching. Game budget: props 2000-12000 triangles, weapons up to 20000 (one Roblox mesh).
- Library in one breath: shapes (`box`, `rounded_box`, `cylinder`, `tube`, `lathe`, `extrude`, `spline`), finish (`bevel`, `mark_bevel`, `chamfer`, `chunky`, `boolean_cut`, `panel_cut`, `vents`), detail kit (`inset`, `plate`, `grille`, `groove`, `bolts_along`), place (`align`, `snap`, `place_on`), surfaces (`surface`, `paint`), checks (`verify`, `measure`).
- Guide topics: nighty-blender://guide/workflow, /library, /topology, /hard-surface, /props, /organic, /texturing, /blender-api.
