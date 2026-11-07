---
name: nighty-blender-procedural
description: Use when the creator asks for procedural or code-built Roblox props in Blender with Geometry Nodes (fences, stairs, rocks, walls with windows, trees, barrels, kit pieces) through Nighty Blender 2, with settings in studs and triangle budgets.
metadata:
  author: NightyCode
  version: "2.0"
  origin: nighty-blender-v2
  as_of: 2026-11
  license: GPL-3.0-or-later
---

# Procedural Roblox props with Geometry Nodes

Builds parametric props (one node group, many variants) in the creator's Blender through Nighty Blender, measured in studs and kept under the triangle budget. Six tested recipes live in `references/recipes.md`; the helper code they share is in `references/gn-kit.md`.

## The first rule still holds

- This is **building in code**. Use it only when the creator asks for it in their own words ("make it procedural", "a fence I can change the length of", "build a wall kit in code"). "Make me a fence" alone goes to nighty-blender-modeling Path A: ask for their model file and import it. Nighty Blender 2 has no AI generation.
- Always through Nighty Blender's `blender_*` tools in Nighty Vault's MCP: `blender_run_python` to build, then `blender_measure`, `blender_look`, `blender_check { what: "mesh" }`. Never through another Blender MCP that happens to be connected.
- Start with `blender_status` (paired, the safety level) and `blender_scene`.
- New work goes into its own collection. Never clear the scene, never reset factory settings, never delete the creator's objects.

## Geometry nodes, bmesh or modifiers?

| Use | When | Example |
|---|---|---|
| **Geometry nodes** | The prop has settings the creator will change (length, count, seed), many variants come from one recipe, or parts repeat along a line or grid | Fence of any length, stairs with N steps, a wall module with 0 to 4 windows, a rock with a seed |
| **bmesh** (Python, one mesh) | One fixed shape with exact vertex control: a custom profile, a hand-placed bevel, a carved detail | A sword guard, a sign with a cut-out shape |
| **Modifiers** (Bevel, Mirror, Array, Weighted Normal) | A finished base mesh needs a standard, non-destructive finish | Micro bevel on a crate, mirroring a symmetric prop |
| **The creator's file** (`blender_import`) | Organic or detailed models that do not repeat: creatures, statues, a hero tree | Anything the creator did not ask to build in code |

Geometry nodes pay off when the second and third variant cost nothing. A one-off shape is faster in bmesh. Mixing is fine: a GN prop can be baked to a mesh (below) and then get modifiers.

## How to build a node group safely (Blender 4.2 LTS to 5.x)

Use the helper `Tree` class from `references/gn-kit.md`. It already does all of this; the rules are here so you can fix it when Blender changes.

1. **Create or rebuild in place.** `bpy.data.node_groups.new(name, "GeometryNodeTree")`. If a group with that name exists, clear its nodes and `interface` and rebuild, so every object that uses it updates. Set `ng.is_modifier = True` (4.0+), or it will not show in the modifier's group list.
2. **Interface sockets** go through `ng.interface.new_socket(name=..., in_out="INPUT" or "OUTPUT", socket_type="NodeSocketFloat" / "NodeSocketInt" / "NodeSocketGeometry")`. Always pass keywords: in 5.x every argument after `name` is keyword-only. The returned item takes `default_value`, `min_value`, `max_value` and `description`. One `Geometry` output is required.
3. **Nodes by type id, never by display name.** `nodes.new("GeometryNodeMeshCube")`, and find existing ones by `n.bl_idname` or `n.type`. Display names are translated in some Blender languages.
4. **Sockets by name, preferring an available one.** Some nodes keep several sockets with the same name and hide the unused ones (Random Value in 4.2 has three `Min` inputs; 5.2 builds only the ones for the chosen type). Pick the first socket whose `enabled` is true. Mesh Line's `Offset` shows the label "End Location" in End Points mode, so also match `label`.
5. **Set enum properties before linking inputs.** Changing `data_type` or `mode` rebuilds a node's sockets. Some settings moved from node properties to menu input sockets in 5.x (Transform Geometry `Mode`, Triangulate methods, Merge by Distance `Mode`). Try the property first, then the socket.
6. **Check every link.** `links.new(a, b)` returns a link; fail if it is `None` or `is_valid` is false (a type mismatch shows as a red link and no error from Python).
7. **Booleans: set the solver.** In 5.2 the Mesh Boolean node defaults to `FLOAT` (the old Fast). Set `solver = "EXACT"` every time. Feed instances straight into `Mesh 2`: each instance counts as its own operand. Cutters pass fully through the target.
8. **Seeds:** one exposed `Seed` input, and a different offset per Random Value node (`Seed + 7`, `Seed + 11`), or scale and rotation move together.

### Setting the modifier's inputs (changed in 5.2)

| Blender | How |
|---|---|
| 4.2 to 5.1 | `md[identifier] = value` (identifier like `Socket_2`, read from `ng.interface.items_tree`) |
| 5.2+ | `getattr(md.properties.inputs, identifier).value = value`. The old `md[...]` raises `TypeError` (checked on 5.2.3) |

Both: then `obj.update_tag()`. The kit's `set_input(obj, md, "Seed", 4)` picks the right one by checking for `md.properties`. Find the identifier by the input's name, never by guessing `Socket_N`.

Other version notes: Mesh Boolean `FAST` became `FLOAT` in 5.0; Math uses `CEIL`, not `CEILING`; Ico Sphere subdivisions 2 = 80 triangles, 3 = 320. More traps: nighty-blender-modeling `references/version-notes.md`.

## Exposing settings

- Expose what the creator will change, with sane `min_value` and `max_value`: **sizes in studs** (Length, Height, Width), **counts** (Steps, Rails, Windows, Blobs), **Seed**, and one **Roughness** (0 to 1) for irregularity.
- **Build in studs, scale once at the end.** The whole tree works in studs; one Transform Geometry at the very end scales by 0.28 (1 stud = 0.28 m). The creator thinks in studs, the export gets metres, and `blender_export { made_for: "roblox" }` turns it back into studs.
- **Fit to spec in the tree** when a shape is random: measure it with Bounding Box and scale or move it, so the size input is exact (the rock recipe does this).
- **Ground it:** the lowest point sits on z = 0 (Bounding Box Min, then translate). Random lean or noise otherwise dips below the floor.
- Put the origin where the spec says: bottom centre for floor props, a grid corner for kit pieces (the wall recipe starts at x = 0).
- Name the group `NB_<Prop>` and the object `PRP_<prop>`.

## Realize, bake and keep the budget

1. **Realize instances** before the end (Realize Instances node). Instances are cheap in Blender but export, `blender_measure` and bounding boxes may not see them.
2. **Triangulate** at the end of the tree (the kit's `finish` does it), so the count you read is the count Roblox gets and the export has no n-gons.
3. **Bake to a mesh for export:** `bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))`, set it as the object's data, then remove the modifier (the kit's `bake_to_mesh`). No operator, so no context errors. Keep the node group: re-bake after changing a setting.
4. **Count triangles on the baked mesh** and compare with the class budget below before any `blender_look`.
5. Keep extra polish out of the tree when it costs triangles: one Ico Sphere subdivision more is 4 times the triangles; bevel segments multiply fast.

| Recipe | Budget class | Target | Ceiling | Tested result (defaults) |
|---|---|---|---|---|
| Fence 16 studs | Small prop | 600 | 1,500 | 84 tris |
| Stairs 8 steps | Small prop | 600 | 1,500 | 96 tris |
| Rock 4 × 3 × 2.5 | Rock | 400 | 1,000 | 320 tris |
| Wall 16 × 12, 2 windows | Kit module | 800 | 2,000 | 52 tris |
| Tree 14 studs | Tree | 2,000 | 5,000 | 508 tris |
| Barrel 3 studs | Small prop | 600 | 1,500 | 252 tris |

## The working loop

1. **Spec first** (a few lines in chat): the prop, its size in studs, the settings to expose, the budget class, the origin. Same as nighty-blender-modeling Stage 0.
2. **One `blender_run_python` call** with the kit plus one recipe: build the group, attach it to a new object in a new collection, set the inputs, bake, and return `report(obj)` as `result`. One logical change per call.
3. **Numbers gate** (all must pass):
   - `blender_measure`: sizes ÷ 0.28 within 5% of the spec in studs (organic shapes like the tree canopy: height within 5%, width noted);
   - triangles at or under the class target, never over the ceiling; `blender_check { what: "mesh", budget }` agrees;
   - `blender_check { what: "mesh" }`: no floating parts, no open edges, no n-gons, no flipped normals;
   - lowest point on z = 0 (`min_z` in the report).
4. **Look gate:** `blender_look` with the four default views in solid, then `wireframe: true` for density. Ask: does it read as the thing from the game camera?
5. **Seed sweep** for anything random: build seeds 0 to 5 and run the numbers gate on each. A recipe that floats at one seed is broken.
6. Show the creator one `blender_look` sheet and the settings list. Changes: set inputs, re-bake, re-check. Set `blender_undo { checkpoint }` before a big change.
7. Finish with nighty-blender-modeling "Quality gate" and "Finishing" (UVs, materials, `blender_export`). UVs, textures and the game mesh for baked GN props: `blender_make_game_ready { object }` or nighty-blender-fix-model.

The `blender_run_python` "safe" level allows no `import` lines: `bpy`, `bmesh`, `mathutils`, `math`, `random` and `nighty` are already loaded there, so drop the kit's `import` line if it is refused.

## Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| `TypeError ... id properties not supported` when setting an input | 5.2 moved modifier inputs | `set_input` (uses `md.properties.inputs`) |
| Input changes nothing | No `update_tag()`, or the wrong `Socket_N` | Read the identifier from `items_tree` by name, then `obj.update_tag()` |
| `enum "X" not found` | Name differs (CEIL, FLOAT) or the setting moved to a socket | Read the error's list; `set_enum` tries property then socket |
| Red link, wrong output, no error | Linked to a hidden duplicate socket | Pick the available socket; check `link.is_valid` |
| Boolean leaves holes or slivers | Default FLOAT solver, or a cutter flush with a face | `solver = "EXACT"`; cutters 2 × thicker than the wall |
| Stacked boxes leave hidden inner faces | Joined, not unioned | EXACT Union, or keep separate closed parts that overlap |
| Merge by Distance made the mesh non-manifold | Separate boxes welded at shared corners | Do not weld separate closed parts; union them instead |
| Size or bounding box looks wrong before baking | Instances not realized | Realize Instances, then measure the baked mesh |
| Props sink a little | Random rotation pushed corners below 0 | Ground with Bounding Box Min at the end |

## Deeper

- `references/gn-kit.md`: the helper code (Tree, set_input, bake_to_mesh, report) and the headless test harness.
- `references/recipes.md`: fence, stairs, rock, modular wall with windows, simple tree, barrel: parameters, triangle targets, checks and code.
- nighty-blender-modeling: spec, blockout gates, quality gate, finishing. nighty-blender-fix-model: UVs, bakes, export checks.
- Some techniques (ideas, not text or code) were learned from scenario-labs/skills (MIT, (c) 2026 Scenario Inc.); see CREDITS.md in the Nighty Blender repository.

<!-- SPDX-FileCopyrightText: 2026 NightyCode -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
