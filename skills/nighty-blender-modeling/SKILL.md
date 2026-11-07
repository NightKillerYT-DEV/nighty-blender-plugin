---
name: nighty-blender-modeling
description: Use when the creator wants a 3D model, prop, weapon, creature or kit in Blender through Nighty Blender 2 - from their own file or download (import first), or built in code only when they ask for that in their own words.
metadata:
  author: NightyCode
  version: "2.0"
  origin: nighty-blender-v2
  as_of: 2026-11
  license: GPL-3.0-or-later
---

# Blender modeling with Nighty Blender 2

Gets game-ready 3D models into the creator's Blender with Nighty Blender 2: import first, build in code only on request, and check every stage with numbers before pictures.

Nighty Blender 2 is a Nighty Vault plugin. Its tools appear in Nighty Vault's MCP as `blender_*` (`blender_status`, `blender_scene`, `blender_look`, `blender_measure`, `blender_check`, `blender_reference`, `blender_import`, `blender_mesh`, `blender_texture`, `blender_make_game_ready`, `blender_export`, `blender_run_python`, `blender_undo`, `blender_job`, `blender_guide`). It has **no AI generation at all**: no local model, no cloud model, no image generation.

## The first rule

- **A model comes from the creator.** Their own file (GLB, glTF, FBX or OBJ), a download they made themselves (a Tripo or Meshy export, a store purchase, a Creator Store mesh they saved), or a mesh already in the scene. Import it first.
- **No file:** ask for one (its full path on this PC). Do not build one in code by yourself, and do not send them to a generator unless they ask where to get one.
- **Build in code only when the creator asks for it in their own words** ("model it in code", "build it from primitives", "make it procedural"). "Make me a wolf" is not that request.
- **Refining an imported model with code is an edit.** It is allowed when the creator asks for the change ("add horns", "replace the teeth"), and only for that change.
- Always use Nighty Blender's `blender_*` tools. Do not build models with any other Blender MCP that happens to be connected.
- Never change the open scene destructively. New work goes into its own collection; ask before you delete or replace anything that was already there.

## Start of every model chat

1. `blender_status`: paired or not, Blender and add-on versions, the safety level the creator set (tools / safe Python / full Python; only they change it, in Blender's N panel), running jobs. Then `blender_scene`.
2. Read the workflow guide once: `blender_guide { topic: "workflow" }` (`blender_guide` with no arguments lists the topics). Keep it; do not re-read.
3. If you use Nighty Vault: `context_pack { project, task }` and look for the game's style guide page (palette, scale table, budgets, reference pictures). If there is none, offer to write one after this model.

Not paired: tell the creator to open the Nighty Blender card in Nighty Vault, press **Pair** and type the 6-digit code into Blender's Nighty tab (N panel).

## Stage 0: the spec (always, a few lines)

Write it in the chat, and save it to a project page for big models:
- what it is and its **budget class** (table below);
- named parts, real size in metres and studs (1 stud is about 0.28 m; an R15 avatar is about 5 studs tall, a door about 7 to 8), what attaches where;
- style, palette (2 to 3 colours plus 1 accent), where the origin goes (bottom centre for floor props, back for wall props, a grid corner for kit pieces);
- target engine (`made_for`), texture size, whether it will be animated (then quads).

## Path A: the creator's file (the default)

1. `blender_import { file: "<full path>", name, size }` (`size` = longest side in metres when the file is in centimetres or unknown; `fixes: ["level", "facing"]` when it lies on its side or faces the wrong way). It is a job: `blender_job { action: "wait", id }` until done (each wait is up to 45 s).
2. Read the triage report to the creator in plain words: triangles, open edges, loose pieces, UVs, textures, scale, rigs. A locked `<name>_SOURCE` copy is kept and never changed; it is the reference for every later check.
3. `blender_look` (solid, then `mode: "matcap", wireframe: true`) and `blender_measure` against the spec.
4. Ask once: `blender_make_game_ready { ask: true, options: { made_for, mesh, faces, textures, size, colors } }` with your best guesses (`menu: true` lists the presets). Send its `question` as ONE message, exactly as given, and wait.
5. `blender_make_game_ready { object: "<name>", options: <their picks>, confirmed: true }`, then `blender_job { action: "wait", id }` until done. Without `confirmed: true` it starts nothing and answers with the question again.
6. Check it (see "Checks" below), including `blender_check { what: "source" }` (did the shape stay close to the original?). Show a `blender_look` sheet and ask for approval.

Anything that fails a gate, or needs step-by-step control: nighty-blender-fix-model.

## Path B: a model built in code (only on request)

Use this only after the creator asked for code. Start from the verified examples (`blender_guide { examples: "<what>", style: "realistic" | "stylized" }`) and the guides (`library`, then `hard-surface`, `props` or `organic`). Keep **one model script** that you improve round by round, never rewrite from nothing, and run it with `blender_run_python` (`import nighty as n`) inside a new collection. Look up Blender API names with `blender_guide { api: "bpy.types.Mesh" }` instead of guessing.

| Stage | Allowed edits | Number gate | Look gate | Rounds |
|---|---|---|---|---|
| 1. Blockout (in full below) | Named primitives only: boxes, cylinders, spheres, simple lofts | `blender_reference { action: "score" }`: silhouette IoU 0.85 or more front and side; sizes within 5% of the spec (`blender_measure`); 0 floating parts (`blender_check { what: "mesh" }`) | `blender_look` 4 ortho views, solid; creator approves | 3 |
| 2. Form | Fuse into one body, smooth, secondary masses | IoU 0.90 or more; one closed body; symmetry passes (`blender_check { what: "mesh", symmetry: "X" }`) | `blender_look` matcap | 5 |
| 3. Detail | Displacement, carved detail, inserts (eyes, teeth, horns, claws) | Inserts touch the body (`blender_measure { pairs }`); no new floaters; IoU drops less than 0.01 | `blender_look` 8 views plus close-ups | 3 |
| 4. Materials | **No geometry edits** | `blender_check { what: "textures" }` passes | `blender_look { mode: "material" }` | 3 |
| 5. Game mesh | Hand over to nighty-blender-fix-model: retopo or decimate, UVs, bake from the dense version | That skill's gates | Creator approves | - |

Load the creator's reference pictures first with `blender_reference { action: "load" }` so the IoU gate has something to compare with. "Nothing gets detail until its silhouette passes."

**Snapshot and revert.** Before each round, set `blender_undo { checkpoint: "<stage>-<round>" }`. If a gate number gets worse, `blender_undo { to: "<stage>-<round>" }` and try a different fix. For a copy you can compare side by side, also duplicate the model into a hidden collection `AI_Snapshots/<stage>-<round>` in the same script. `blender_undo` only takes back steps named "AI: ...", never the creator's own work.

**Stop rules.** Stop a stage after two rounds with no gain and keep the best attempt. When the round budget runs out, keep the best attempt and say which gate is still short. If the same gate fails twice on a simple prop, say so: a model file from the creator, or a small rebuild, is often faster.

### Stage 1 in full: the blockout

The blockout decides the shape. It is cheap to change now and expensive after detail, so nothing gets detail until it passes. Everything here runs on the creator's PC with Nighty Blender's own tools.

**1. Spec first.** Before any geometry, write (and save on a project page for big models):
- the overall size in studs (1 stud = 0.28 m) and the budget class;
- a parts list, each part with a name and rough size in studs, and what it attaches to;
- one or more reference pictures from the creator, at least front and side for anything asymmetric. Load them with `blender_reference { action: "load", images: [{ path, view, height or width in metres }] }`.

| Part | Size W × D × H (studs) | Attaches to |
|---|---|---|
| `PRP_kiosk_base` | 8 × 6 × 1 | ground |
| `PRP_kiosk_counter` | 8 × 2 × 3.5 | base, front edge |
| `PRP_kiosk_roof` | 9 × 7 × 1 | posts, top |

**2. Primitives only, each part named, at game scale.**
- Boxes, cylinders, spheres and simple lofts; no bevels, booleans, smoothing or detail. One object per spec part, named `PRP_<asset>_<part>` (the spec's names), under one root collection `PRP_<asset>`; role prefixes `PRP_`, `ENV_`, `REF_`.
- Build in a new collection; if the file holds other work, use a new scene, and hide default objects instead of deleting them.
- Keep a `REF_` R15 dummy beside it and compare against it. Roblox scale to check against (tune to the game's style guide): character about 5 studs tall; doorway about 4 wide and 7 to 8 tall; stair step about 1 stud high; table about 3 studs high; chair seat about 1.5 to 2; one storey about 12 studs; a crate 2 to 4 studs.
- Parametric props (fences, stairs, walls, rocks, trees, barrels): build the blockout with nighty-blender-procedural and keep its settings.

**3. Gates before any detail** (all four, numbers first):
1. **Sizes vs spec:** `blender_measure` every part and the whole; each size ÷ 0.28 within 5% of the spec in studs.
2. **Four orthographic views:** `blender_look { views: ["front", "right", "top", "back"], mode: "solid" }` (ortho is the default), plus `references: true` to see the pictures behind.
3. **Silhouette vs reference:** `blender_reference { action: "score", view }` for front and side; IoU 0.85 or more each. The red and blue picture says where to move mass.
4. **No floating parts:** `blender_check { what: "mesh" }` (0 floating, or listed in `allow_floating` on purpose) and `blender_measure { pairs }` on every "attaches to" pair from the spec (touching).

**4. The creator approves with one look.** Show one `blender_look` sheet (four views, solid) with the numbers in one line (sizes, IoU front and side, floating 0). Wait for an OK before detail. A change request is another blockout round, not a detail round.

**5. Detail one part at a time, with a revert.** After approval, take the parts in spec order. Each round: checkpoint ("Snapshot and revert" above), detail one part, then rescore all four gates. If any number gets worse (a size leaves 5%, IoU drops more than 0.01, a part floats), go back to the checkpoint and try a different fix. The stop rules above apply per part.

### Hard-surface props and weapons (Path B)

- **Modifier order, top to bottom:** booleans → design bevel (weight-limited, only on chosen silhouette edges) → micro bevel (angle-limited at about 30 degrees, Harden Normals on) → Mirror → Triangulate (keep custom normals) for the game version → **Weighted Normal at the very bottom**. Never let a pinned Smooth by Angle modifier sit below Weighted Normal: details in `references/version-notes.md`. The library does most of this: `n.mark_bevel` the main shape, cut the details, then `n.bevel(part, width, limit="weight")`.
- **Bevel segments for games: 1 to 2.** Segment counts of 8 to 12 are for renders only.
- **Bevel width is absolute:** about 3 mm on a body, 1 mm on small parts; when the real size is unknown, about 0.5% of the largest dimension.
- **Every wall, step, groove or facet must be wider than twice the micro bevel.** Otherwise Clamp Overlap shrinks the bevel on the whole object, not only there.
- **Booleans:** solver EXACT. Cutters pass fully through every surface they enter, sit clearly away from the target's edges or exactly on them, and are smooth-shaded. A round cutter on a round target with the same segment count is rotated by half a segment.
- If Weighted Normal or Harden Normals changes nothing on a face, the face is not flat: flatten it rather than stacking more normal modifiers. `blender_mesh { op: "fix_shading" }` resets normals and smooths by angle when the shading is a mess.
- Judge in a shiny matcap (`blender_look { mode: "matcap" }`) plus one close-up per cut. After export, confirm the shading in Studio: custom normals surviving the Roblox import is not proven.

**Creatures.** Pure code does well on stylized creatures seen from the game camera and on hard-surface props. Detailed close-up monsters (muscle, teeth, scales, hands, faces) come out better as a sculpted or downloaded body the creator provides, refined by code (Path C). Tell the creator this before they choose.

## Path C: refine an imported model (an edit they asked for)

1. Import the creator's file (`blender_import`), or take the mesh already in the scene.
2. `blender_mesh { op: "cleanup" }` to close gaps and join loose pieces.
3. Fix symmetry only where the creator agrees: logos, text and deliberate asymmetry break.
4. `blender_mesh { op: "split_parts", names: [...] }` when a part must be replaced; add the requested inserts (horns, teeth, eyes) with a short `blender_run_python` and seat them (`n.place_on`; `blender_measure { pairs }` shows touching).
5. Hand over to nighty-blender-fix-model for retopo, UVs and a rebake from the dense original (or `blender_make_game_ready { object }` when it fits).

## Checks: numbers first, pictures second

Models misjudge exact things from pictures: positions, sizes, rotations, which way +X points, whether parts touch, symmetry, small gaps. A self-check picture once passed an object built at two thirds of its intended size. So:

1. Numbers first: `blender_measure` (sizes against the spec, `pairs` for gaps and touching, `reference` for an overlap score), `blender_check { what: "mesh", budget, symmetry }`, `blender_reference { action: "score" }`, and for imports `blender_check { what: "source" }`.
2. Then `blender_look`: solid for shape, matcap for shading errors, silhouette for readability, material for the final look, `wireframe: true` for density. A small `size` (256 to 512) keeps long chats cheap.
3. Trust your eyes for meaning-level questions only: does it read as the thing, is the silhouette clear, does it match the style.

Camera choice: Claude and Codex may pick their own views (it helps them); Gemini and Antigravity should keep the fixed four-view sheet.

### Quality gate (every model, before you call it done)

Hard checks (any fail = not done):
- triangles within the class ceiling, never over 20,000 per mesh;
- closed surface (except leaf and cloth cards), no flipped normals, no loose or zero-area faces, no n-gons in the export;
- transforms applied, sane size in studs, origin where the spec says;
- one UV map inside 0 to 1, one material per exported object;
- symmetric-by-design objects (shields, swords, bottles, most props and creatures) mirror within about 1% of their size;
- features meant to be centred (emblems, gems, guards) sit on the parent's axis, and features meant to sit on a surface touch it, measured, never judged by eye;
- **part contact, as fractions of the asset's bounding diagonal D:** a part more than 1% of D from every other part floats; within 0.2% of D (or crossing) it touches; anything between is a near miss to seat. Faces of two parts in one plane within 0.01% of D z-fight in Studio. Inward faces over 0.1% of a part's surface are an error (Roblox culls back faces). Gate separate props one at a time. Script: nighty-blender-fix-model `references/gate-scripts.md`, script 1;
- materials: dielectric base colour between about 30 and 240 sRGB (under 2% of pixels outside), metal colour 180 or more, metallic 0 or 1 (under 5% in between), roughness not flat, data maps Non-Color, and no live Bevel, AO or Pointiness shader nodes at export (games ignore them: bake them);
- the export reads back: `blender_check { what: "roundtrip" }` (and `what: "roblox"` for Roblox), plus the GLB to FBX metal and roughness check in nighty-blender-fix-model ("Gates in numbers").

Then score the look with the model rubric in nighty-quality-gate (8.5 bar). For hero assets or a borderline score, the creator can run nighty-council (Quick, Art Director lens).

### Triangle budgets (target / ceiling; tune per game)

| Class | Target | Ceiling |
|---|---|---|
| Tiny prop | 150 | 300 |
| Small prop | 600 | 1,500 |
| Medium prop | 2,000 | 4,000 |
| Rock | 400 | 1,000 |
| Tree | 2,000 | 5,000 |
| Held weapon | 2,500 | 4,000 |
| Kit module | 800 | 2,000 |
| Building | 6,000 | 10,000 (split into modules) |
| Creature | 5,000 | about 10,000 |
| Hero piece | 10,000 | 20,000 |

Going over the target needs a stated reason. Extra bevel segments are expensive: one segment on a box costs several times the triangles, two segments far more. (`blender_make_game_ready` defaults to 15,000 for Roblox; give it the class target in `faces` instead.)

## The critic pass (fresh eyes)

Before the creator's approval at the end of a stage, get one critique from a fresh context: a subagent (or a new chat) that sees only the `blender_look` sheet, the numbers, the spec and the model rubric. It never sees your reasoning. It returns at most **three fixes, each with a number** ("raise the horn base 0.02 m", "thin the neck to 0.18 m"). Apply them, then check with numbers that each fix actually landed before you look again.

## Roblox in short

- 20,000 triangles per mesh; one material and one UV set; quads only matter for animated meshes.
- `blender_export { made_for: "roblox" }` writes studs, axes and SurfaceAppearance maps. Bake at 2K, export at 1K (`size: "1K"`).
- `blender_check { what: "roblox" }` before the creator imports: triangles per part, UVs, 1024 px maps, scale, an export.
- UVs and bakes for the game mesh follow nighty-blender-fix-model's numbers: coverage 0.70 or more on props, padding = texture size / 128, about 512 px/m texel density for third-person props, a measured cage, a fail when more than 2% of normal-map pixels are inverted, AO distance about 0.2 × the diagonal.
- Rigged characters and R15 avatars: nighty-blender-rigging.
- Origin bottom centre for props; apply transforms; no scaling in Studio to fix units.
- Skip `blender_mesh { op: "lods" }` for Roblox: Roblox builds its own mesh LODs.
- Import settings, pivots, collision and budgets: nighty-roblox-asset-import.

## Finishing

1. `blender_check { what: "mesh" }` passes, then `blender_check { what: "final", names, notes }` (it refuses without a passing mesh check; a written `reason` is kept with the report).
2. `blender_export { made_for }` for the target engine; tell the creator where the files are.
3. If you use Nighty Vault: `add_lesson` for a mistake worth never repeating, `log_decision` for a style choice, update the style guide page.
4. Pairing is managed in Nighty Vault's Nighty Blender card; there is nothing to disconnect from the chat.

Blender API traps for code (Path B and C), exact version notes and `blender_run_python` discipline: `references/version-notes.md`.

## Deeper

- Procedural props in code (Geometry Nodes, six tested recipes): nighty-blender-procedural.
- Nighty Blender's own guides: `blender_guide { topic }` (workflow, library, topology, hard-surface, props, organic, texturing, blender-api).
- If you use Nighty Vault, see the Library pages "Nighty Blender for 3D models", "Mesh Gates for Generated Models - Symmetry, Seating and Caps" (section "Running the gates"), "Shape Language and Silhouette Testing" (section "Silhouette testing on Roblox: four views, not one"), "Critiquing a Model - Paintovers and Iteration" (section "Critique in a fixed order"), "Stylized Creatures - Soft Forms, Painted Gradients and Light Rigs" and "Exporting and Validating Models for Roblox" (section "Hard limits").

<!-- SPDX-FileCopyrightText: 2026 NightyCode -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
