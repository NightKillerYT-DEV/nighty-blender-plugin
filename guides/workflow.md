# Workflow: import first, make it game-ready, check, fix
How every model goes through Nighty Blender: the person's file in, one question, make_game_ready, then checks and small fixes. No local AI: read this first.

## The first rule
- Nighty Blender has no AI model of its own and never generates one. Models come from the person: a file they give you (GLB, glTF, FBX or OBJ, from any source: their own work, a store, a 3D service they use), a mesh already in the scene, or code only when the person asks for it in their own words ("build it in code", "model it by hand").
- No file and no request for code: ask the person for the file (its full path on this PC). Never build a model in code by yourself.
- Edits on a model (move a part, recolor, add a decal, fix a spot): the step tools; `blender_run_python` only for a small fix the person asked for.

## Start
1. `blender_status` (paired, Blender and add-on versions, the safety level) and `blender_scene`.
2. Import: `blender_import { file: "C:/Users/you/Downloads/chair.glb" }` (a job: `blender_job { action: "wait", id }`). It brings the model in as one object, keeps a locked `<name>_SOURCE` copy (never changed; your undo of last resort and the reference for checks) and answers with a triage report: triangles, open edges, loose pieces, UVs, textures, scale, rigs. Tell the person the main points.
3. `blender_look` at it (solid and matcap; `wireframe: true` for the topology). A model stored in centimeters shows up 100x too big: import again with `size` (the longest side in meters).
4. Ask first, every time: `blender_make_game_ready { ask: true, options: { made_for: ... } }` with your best guesses from the request. Send the person its `question` as ONE message, as it is, and wait. It has the picks filled in: mesh (triangles or quads), the exact triangle count (Roblox: 15,000), textures, texture size (Roblox: 1K), made for, colors.
5. `blender_make_game_ready { file or object, options: their picks, confirmed: true }`. Without confirmed it refuses and answers with the question: ask it. A job: `blender_job { action: "wait", id }` until done (minutes; each wait is up to 45 s).
6. `blender_look { mode: "material", views: ["hero"] }`, `blender_check { what: "source" }` (did the shape stay close to the original?), tell the person the `mesh` line of the result, then fix single steps (below).

## What make_game_ready does
One job, step by step (each its own undo step), stopping at the first step that fails and saying which: import (a file), cleanup (a file; a scene mesh only with `cleanup: true`), clean colors, retopo to the exact count, parts, UVs, textures, texture check, export, mesh check, finish. Textures: the model's own textures re-baked onto the low poly (`texture_source: "own"`, the default), or `materials` per part (each part gets the library material closest to its own color; a list to choose from, e.g. `["wood", "brass"]`). Roblox and other game engines get the exact-count triangle low poly unless the person picks quads (for editing further).
Ragged texture colors (halos, stair-stepped borders): make_game_ready cleans them (`colors: auto`); by hand `blender_texture { op: "clean_colors" }`, then bake again.
Budgets: Roblox 15,000 triangles by default (one MeshPart takes 20,000 at most), mobile under 5,000, PC props 10,000-40,000.

## Checks
- `blender_check { what: "mesh" }`: counts, open and non-manifold edges, floating parts, flipped normals, UVs. Fix every error.
- `blender_check { what: "textures" }`: the baked maps (blur, metallic 0/1, light baked in, unbaked pixels).
- `blender_check { what: "source" }`: the model against its `_SOURCE` copy (size, triangles, surface drift in % of its size).
- `blender_check { what: "roundtrip" }`: export, read back, compare (what the engine will get).
- `blender_check { what: "roblox" }`: the Roblox gate (20,000 triangles per part, UVs, 1024 px maps, applied scale, an export).
- `blender_check { what: "final" }`: marks it finished; refuses unless the last mesh check passed.

## Fixes after make_game_ready
- `blender_mesh` ops: retopo (another count), decimate, uv_unwrap, split_parts, cleanup, lods, fix_shading (faceted or smeared shading).
- `blender_texture` ops: assign_materials, decal (sharp text and logos), clean_colors, bake, stylize, fix_seams (lines along UV seams in game).
- `blender_export { made_for }` for another engine.
- A small add-on the person asked for (a sight, a strap, a sign): a few parts in `blender_run_python` with the library, placed on the model (`n.place_on`), then `blender_check { what: "mesh" }` and `blender_look`.
- Every change is one undo step named "AI: ..."; `blender_undo` takes back only yours (`checkpoint` / `to` for several).
- Blender API names: `blender_guide { api: "bpy.types.Mesh" }` instead of guessing.

## Only when the person asks: building in code
- `blender_guide { examples: "wooden crate", style: "realistic" }` and adapt the closest code in `blender_run_python` (`import nighty as n`). Guides: library, hard-surface, props, organic, topology.
- Plan: what it is, the style, real size in meters (a pistol is about 0.2 m long, a door 2.0 x 0.9 m, a chair seat 0.45 m high), a parts list, a triangle budget.
- The loop, every part: build one part or a few (`n.settings(detail, size)` first: detail "low" for game assets; meters, Z up, front is -Y, right is +X); `blender_check { what: "mesh" }` and fix every error (floating parts, holes, flipped faces, inside-out parts, same-plane flicker); `blender_measure` against the plan or the reference (`blender_reference`); `blender_look` (matcap + wireframe for shape, solid for colors); fix, and `blender_undo` a fix that made it worse. Done: the mesh check on all parts, the studio look, `blender_check { what: "final" }`.
- The bar: a readable silhouette; secondary forms that step out of each other (shell / plate / chassis, insets, raised panels); a few strong details (vents, seams, bolts at joints), not hundreds of tiny bits; value contrast between neighbors; bevels on every visible edge (`n.mark_bevel` the main shape, cut the details, then `n.bevel(part, width, limit="weight")`).
- Budgets: tiny props 500-3000 triangles, props 2000-12000, hero props and weapons 12000-20000. Texture what a texture can carry (knurling, stipple, grain). An example script runs in about 1 s.
