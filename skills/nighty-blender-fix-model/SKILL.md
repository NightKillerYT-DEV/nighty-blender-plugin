---
name: nighty-blender-fix-model
description: Use when the creator's model file (a Tripo, Meshy or Rodin download, a store asset, their own export) needs fixing for a game through Nighty Blender 2: broken mesh, too many triangles, bad UVs, seams, baked-in light, wrong size, Roblox import.
metadata:
  author: NightyCode
  version: "2.0"
  origin: nighty-blender-v2
  as_of: 2026-11
  license: GPL-3.0-or-later
---

# Fixing model files with Nighty Blender 2

Turns a messy model file into a clean game asset: import it with a locked source copy, build a clean copy, rebake its colours, and pass a number gate at every step.

Nighty Blender 2 is a Nighty Vault plugin; its tools appear in Nighty Vault's MCP as `blender_*`. It has **no AI generation**: the model is a file the creator gives you (their own work, a store purchase, or a download they made with a 3D service such as Tripo or Meshy), or a mesh already in the scene. Never replace it with a model built in code unless the creator asks for that in their own words.

## The idea in one paragraph

Never edit the download into shape directly. `blender_import` keeps a locked `<name>_SOURCE` copy that no tool ever changes: it is the reference for `blender_check { what: "source" }` and your undo of last resort. Work on the imported copy: repair it, reduce it, give it new UVs, then **bake the dense original's colours onto the clean copy**. The rebake throws away the shredded texture layout of AI-made models, which is the real cause of most "colours don't meet" seams. `blender_mesh` ops `retopo` and `decimate` also keep the dense version hidden as the bake source (`keep_source: true`, the default), and running them again starts from it.

## Before you start

1. `blender_status` (paired, versions, the safety level the creator set, running jobs), `blender_scene`, and `blender_guide { topic: "workflow" }` once.
2. **Licence check (ask, then write it down).** Where did the file come from, and on which plan?
   - Tripo free plan: output is public and non-commercial. Ship only models made on a paid plan.
   - Meshy free plan: CC BY 4.0, so the game must credit Meshy.
   - Hunyuan3D 2.x open weights: the licence excludes the EU, the UK and South Korea, outputs included. Do not ship its outputs from there.
   - Store and Creator Store assets: their own licence; see nighty-roblox-asset-import.
   Record source, plan and date in the project's asset licence log (with Nighty Vault: `append_to_page`).
3. **Fast path first.** For a single model with no special needs: ask the options question with `blender_make_game_ready { ask: true, options: { made_for: "roblox" } }`, send its `question` as ONE message and wait; then `blender_make_game_ready { file: "<full path>", options: <their picks>, confirmed: true }` (or `object` for a mesh already imported) and `blender_job { action: "wait", id }` until done. It imports (with the `_SOURCE` copy), cleans, reduces to the exact count, unwraps, bakes, checks, exports and finishes. Use the 14 steps below when the fast path fails a gate, or when the creator wants control of each step.

## Download settings (step 0, saves half the work)

For the creator when they make the download themselves:

| Setting | Best choice for a Roblox prop | Why |
|---|---|---|
| Plan | Paid | Free outputs carry licence limits (above) |
| Topology | Tripo Smart Mesh, about 5,000 to 9,000 quads or 10,000 to 18,000 triangles; Meshy Remesh; Rodin Quad mode (8k or 18k preset) | Stays under 20,000 triangles after triangulation |
| Lighting | Tripo texture `delight` on; Meshy "Remove Lighting" (newer Meshy versions do it by themselves); Rodin **PBR, not "Shaded"** | Shaded means lighting painted into the colours |
| PBR | On | Gives colour, normal, roughness and metal maps |
| Texture size | 2K is plenty | Roblox PBR maps are used at 1024 in practice |
| Format | GLB (textures inside); FBX when you want to keep quads | GLB and OBJ may triangulate |

Meshy's own advice: triangles for static props, quads for animated characters.

## The 14 steps

Each step must pass before the next. On a fail: retry once with the listed fix; if it fails again, go back to the last checkpoint and ask the creator. If the same gate fails twice on a simple prop, say so: rebuilding it in code with the file as a reference (only if the creator asks), or a better download, is often faster than fixing.

| # | Step (tool) | Pass when | On fail |
|---|---|---|---|
| 0 | Download with the settings above | Paid plan; PBR maps present; under about 18k triangles | Download again with the vendor's remesh option |
| 1 | Import and triage: `blender_import { file, size, fixes }`, `blender_job { action: "wait", id }`. Read the triage report, then `blender_check { what: "mesh", full: true }`, `blender_look { mode: "material" }` and `blender_look { mode: "solid" }` from 6 views | Textures linked (no grey material); triangle, part and texture numbers written down; baseline pictures shown | Try the other format (GLB or FBX); centimetres: import again with `size` |
| 2 | Save point "imported": `blender_undo { checkpoint: "imported" }` (the `_SOURCE` copy is the deeper fallback); ask the creator to save the .blend | Set | - |
| 3 | `blender_mesh { op: "cleanup", size, size_axis, origin: "bottom" }` | `blender_check { what: "mesh" }`: 0 non-manifold edges, 0 flipped faces, 0 floaters, scale applied; the part-contact gate below passes. Compare piece counts with step 1: if a real small part vanished (an eye, a button), `blender_undo` and rerun with a smaller `floaters` value | `manifold: "voxel"` (it loses UVs and thin parts; the rebake brings colour back) |
| 4 | Reduce. Skip if already in budget with good UVs. Static prop: `blender_mesh { op: "decimate", faces }`. Animated or hand-edited later: `blender_mesh { op: "retopo", mode: "quads", faces }` | `blender_check { what: "mesh", budget }`: 10,000 for props, never over 20,000. `blender_check { what: "source" }`: drift within `tolerance_pct` (1% default); `blender_measure { reference: "<name>_SOURCE" }` for the overlap (start at a silhouette overlap of 0.97) | Quad remesh hangs or fails: `decimate`, or `engine: "quadriflow"`. Silhouette fails: more triangles |
| 5 | Shading: `blender_look { mode: "matcap" }`. Fix only if needed: `blender_mesh { op: "fix_shading", angle: 30 }` (normals out, smooth with sharp edges by angle; never the removed `use_auto_smooth`; modifier order rules in nighty-blender-modeling `references/version-notes.md`) | No black blotches or random facets; 0 flipped normals | Lower the angle; check normals again |
| 6 | `blender_mesh { op: "uv_unwrap", texture_size: "2K", margin_px: 16, method }` (`"seams"` for hard surfaces, `"smart"` for organic, `"xatlas"` for a tight pack) | `blender_check { what: "mesh" }`: UV overlap 0, all UVs in 0 to 1, low stretch, plus the UV gate below | Switch method; fewer, bigger islands |
| 7 | Save point "pre-bake": `blender_undo { checkpoint: "pre-bake" }`. Then `blender_texture { op: "clean_colors", objects: ["<low>"], picture: "<creator's picture>" }` (it works on the hidden dense version; `mode: "gentle"` for real texture detail) | Colours match the picture; no painted shadows in the albedo-only render | `mode: "gentle"` or `"restore"`; ask the creator |
| 8 | Measure the cage (below), then `blender_texture { op: "bake", parts: ["<low>"], from_high: true, maps: ["base_color", "normal", "roughness", "metallic", "ao"], size: 512 }` as a test, then the same at `size: "2K"`; then `blender_check { what: "textures" }` and the pixel checks below | No unbaked pixels; normal map passes the pixel checks; AO passes; no baked-in light; maps present | Rebake; if pixels stay unbaked, unwrap again with a bigger margin; if inverted spots stay put, fix the geometry |
| 9 | Seams: read the seam part of the textures check; `blender_texture { op: "fix_seams" }` for lines along UV seams | Seams pass (start at a mean colour difference under 2 and a 95th percentile under 5) | Unwrap again with fewer islands and rebake; repainting a patch needs the creator's OK |
| 10 | Compare: `blender_look { mode: "material" }` from the same 6 views as step 1, `blender_check { what: "source" }` and `blender_measure { reference: "<name>_SOURCE" }` | Same look as the source; **the creator approves** | `blender_undo { to: "pre-bake" }` |
| 11 | `blender_export { made_for: "roblox", size: "1K" }` (bake at 2K, export at 1K; a job), then `blender_check { what: "roundtrip" }` and `blender_check { what: "roblox" }` | One mesh, one material, four maps, no stray alpha in the colour map; the read-back matches | Fix the export setting; export again |
| 12 | `blender_check { what: "mesh" }` passes, then `blender_check { what: "final", names, notes }` | Finished (it refuses without a passing mesh check) | Give a written `reason`, or stop |
| 13 | Studio check: the creator imports with the 3D Importer (Upload to Roblox off while testing), then run the import audit from nighty-roblox-asset-import through the Studio MCP `execute_luau`, and `screen_capture` | SurfaceAppearance has all maps; AlphaMode Overlay or Opaque; size in studs right; CollisionFidelity Box or Hull; looks right in Studio | Check the maps by hand (colour, normal, roughness, metal) |

Skip `blender_mesh { op: "lods" }` for Roblox: Roblox builds its own mesh LODs.

## Gates in numbers

`blender_check` (mesh, textures, source, roundtrip, roblox) and `blender_measure` cover most of this. The rest is short read-only `blender_run_python` scripts in `references/gate-scripts.md` (they create nothing, or remove only what they created). All distances are fractions of the asset's bounding-box diagonal **D**, so one rule fits a coin and a castle.

**Part contact (step 3, and after any part is added or moved).** Gate separate props one at a time, never as one blob.
- Gap over 1% of D from every other part: **floating** (an error, unless listed in `allow_floating`).
- Gap at most 0.2% of D, or the surfaces intersect: **touching** (pass).
- Between the two: a near miss. Seat it (`blender_measure { pairs }`), do not leave it.
- Faces of two parts lying in the same plane within 0.01% of D: **z-fighting** in Studio. Move one part in or out by about 0.1% of D, or delete the hidden face.
- A closed part that is inside out, or inward-facing faces over 0.1% of a part's surface: error. Roblox culls back faces, so these show as holes.

**UV gate (step 6).**
- No face left unsolved: zero-area UV faces count 0. An unwrap can report success and leave some islands with their old UVs.
- Coverage of the 0 to 1 square: **0.70 or more** on props and hard surface. 0.55 to 0.65 is normal on creatures and organic shapes; below that on a prop is wasted texture.
- Padding = texture size / 128: 8 px at 1K, **16 px at 2K**, 32 px at 4K.
- Texel density: islands within about 20% of each other, except deliberate choices (face and front more, soles and undersides less). Targets: about 512 px/m for third-person Roblox props (5.12 px/cm), about 1,024 px/m for first-person views, about 2,048 px/m for a first-person held weapon.
- Size check: texture side ≈ density (px/m) × √(surface area in m² ÷ coverage). A 1 m crate (6 m², coverage 0.7) at 512 px/m needs about 1,500 px, so bake at 2K; exporting at 1K halves the density, which is fine at Roblox camera distances.

**Before the bake (step 8).**
- **Measure the cage instead of guessing.** Cast rays from the clean copy along its normals and record how far the source sits outside and inside it (script in the reference). The usual 0.5 to 2% of D is only a starting value. If the 99th percentile outside distance is bigger than 2% of D, the bake will miss or invert there: add triangles where the copy cuts inside the source, then measure again. One global distance fails on thin parts close to others (ears, fingers, straps).
- Mirrored or stacked islands: move the copies exactly one tile to the right (U + 1) before baking, or the last island baked overwrites the others.
- A 512 test bake first; the 2K bake only after the test passes the pixel checks.
- After the bake, the UVs are frozen: any UV change means a rebake.

**Pixel checks after the bake** (read inside the UV islands only):

| Map | Fail when | Note when |
|---|---|---|
| Normal | more than **2%** of pixels have blue below 0.5 (rays hit the far side); more than 25% exactly flat (rays missed); more than 2% with a vector length off by over 0.15 (wrong colour space or format) | over 0.2% blue-inverted |
| AO | more than 10% near black (something encloses the surface); more than 85% near white (distance too short); mean below 0.3 | - |

- If the inverted spots stay in the same place when the cage changes, the geometry is the cause (a hole, a thin wall, an overlap, a leftover inside shell): fix that, not the numbers.
- AO distance: about **0.2 × D**. Blender's fixed default suits only mid-sized objects. Samples: 16 for normals, 128 for AO.

**Re-import check (step 11).** An export is finished only after it reads back: `blender_check { what: "roundtrip", file }` exports (or takes the file you name), reads it back and compares size, triangles, scale, materials, UVs and maps. For details it does not report (bones, custom properties), script 5 in the reference does a manual read-back (it needs the "full" safety level).

**The GLB to FBX trap.** A glTF import stores metal and roughness in one packed image split by a Separate Color node. The FBX exporter cannot follow that node, so the FBX reads back at Metallic 0 and Roughness 0.5; colour, normal and emission survive. This is exactly the path of a GLB download going to Roblox as FBX. Rebaking (step 8) replaces the packed image; after export, check that the export folder holds roughness and metal as **separate greyscale images**, and in Studio that the SurfaceAppearance has all four maps. If a transform with negative scale was applied, flip the normals back (the winding flips).

## Roblox texture rules

- SurfaceAppearance takes ColorMap, NormalMap, RoughnessMap and MetalnessMap (plus an emissive mask). **There is no AO slot**: multiply AO into the colour map.
- Normal maps are OpenGL tangent space (a flat pixel is 128, 128, 255: the vector 0.5, 0.5, 1.0 rounds to 128). Blender bakes that format already.
- Roughness and metal are greyscale; metal should be 0 or 1 (`blender_import { fixes: ["metal"] }` snaps a guessed metal map to 0/1).
- One material per mesh. Keep alpha out of the colour map unless the model needs cut-outs: see-through pixels show the MeshPart colour under the default Overlay mode.
- Downloaded normal maps are often soft and blotchy: drop them and bake a fresh normal map from the dense source.
- Wrong or missing materials per part: `blender_texture { op: "assign_materials", parts: { "<part>": "steel" } }` (CC0 photo textures only after the creator agrees: `cc0_agree: true`).

## Baking facts worth knowing

- The clean copy is the **selected and active** object, the source is selected too. The bake writes into the Image Texture node that is **both selected and active** in each material (Blender manual; required since 5.0). A material without one bakes nothing. `blender_texture { op: "bake" }` sets this up; it matters only for a hand-written bake.
- Rays go from the low copy toward the source. For AI-made models the two surfaces almost touch: a cage extrusion of 0.5 to 2% of the model's diagonal is a good start, then measure (above).
- For AO, hide every other object from render, or it shades the asset.
- Operator defaults differ from the scene's bake settings: a hand-written bake passes every setting (margin type and size, clear, cage) explicitly.
- Blender has no metallic bake type. The usual trick is metallic into an Emission shader, baked as "Emit"; the same path is safer for base colour, because a diffuse-colour bake turns full-metal areas black.
- Bake margin: "Adjacent Faces" fills padding with the colour from across the seam; "Extend" repeats the island's border pixels. Pass the type explicitly instead of trusting a default. Margin about 16 px at 2048 (texture / 128).
- AO ignores scene lights and turns floaters and inside shells into black blotches: clean first.

## Machines check counts; the creator judges the look

| Step | Automatic? | Who checks |
|---|---|---|
| Weld, floaters, normals, small holes, scale, origin | Fully | Numbers, plus the list of removed pieces |
| Decimate to budget | Fully | Numbers plus the drift from `_SOURCE` |
| Quad remesh | Partly (can hang) | Fallback, then a look |
| UVs | Fully | Overlap, bounds, stretch |
| Rebake | Fully | Unbaked pixels, normal map, seams |
| Removing painted light | Automatic, then a look | It can wash out real dark paint |
| Repainting patches | Needs the creator | Results are random and can change the design |
| Symmetry, big holes, thin parts | Needs the creator | Risky guesses |
| Design mistakes (extra fingers, fused parts) | Needs the creator | A new download rather than a fix |
| Final style and readability in Studio | Needs the creator | Model judges agree with people only about two thirds of the time |

All thresholds here are starting values. No public source has published them for AI-asset cleanup. Tune them on the creator's first 5 to 10 models and save the tuned numbers (with Nighty Vault: `add_lesson`).

## Free tools (the creator installs them; never bundle or run installers)

| Tool | Job | Licence note |
|---|---|---|
| Blender | Almost every step | GPL; your meshes and textures do not become GPL |
| Instant Meshes | Quad remesh (`blender_mesh { op: "retopo", engine: "instant_meshes" }`) | BSD-3; the creator presses **Get Instant Meshes** in Nighty Vault's Nighty Blender card |
| QRemeshify | Quad remesh | GPL-3; decimate under 100k triangles first |
| Real-ESRGAN (ncnn-vulkan) | Upscale a blurry texture; fill padding first | BSD-3 |
| Marigold IID Lighting | Remove painted light from realistic textures, on rendered views | RAIL++-M, no territory limit |
| Hunyuan3D 2.x | - | Do not use in the EU, UK or South Korea |

If a helper is missing, tell the creator what to install and where; nothing is downloaded or installed without their yes.

## Finishing

Tell the creator: done, not done, not checked (for example "not checked in Studio"), risk. Save tuned thresholds and repeat mistakes (with Nighty Vault: `add_lesson`), and licence facts in the licence log.

## Deeper

- `references/gate-scripts.md`: read-only `blender_run_python` checks for part contact, UVs, the cage, baked pixels and a manual re-import.
- Nighty Blender's own guides: `blender_guide { topic: "workflow" }`, `"topology"`, `"texturing"`.
- If you use Nighty Vault, see the Library pages "Nighty Blender for 3D models", "Retopology and Decimation" (section "Choosing the method"), "Texturing and PBR Baking" (section "Baking in Blender with Cycles"), "Normal Maps and Detail Baking", "UV Unwrapping" and "Exporting and Validating Models for Roblox" (section "Hard limits").

<!-- SPDX-FileCopyrightText: 2026 NightyCode -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
