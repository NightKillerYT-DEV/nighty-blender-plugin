# Blender version notes and failure catalogue

Version traps for `blender_run_python` code in Blender 4.2 LTS to 5.x, plus a symptom to cause to fix list. Use only when the creator asked for code (Path B or C). Nighty Blender's own guide (`blender_guide { topic: "blender-api" }`) wins when it disagrees: it ships with the add-on version the creator runs.

## Rules for every script

1. Prefer the data API (`bpy.data`, `bmesh`) over operators (`bpy.ops.*`). Operators need the right context and fail with "poll() failed" without it.
2. Never trust default names. `new_obj = bpy.data.objects.new(...)` returns the real name (Blender adds `.001` on clashes); keep that reference.
3. Find shader nodes by type, never by name (names are localized): `next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")`.
4. Never hardcode enum identifiers. Read them: `[i.identifier for i in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]`. Assign a render engine inside `try/except TypeError`; the error lists the valid values.
5. Guard socket names: `if "Emission Color" in bsdf.inputs: ...`.
6. Material colours go on shader node inputs. `material.diffuse_color` changes only the viewport.
7. **Never delete a failing line to make an error go away.** Find the renamed API instead (`blender_guide { api: "bpy.types.<Type>" }`, or read `bl_rna` of the running Blender).
8. Work inside a new collection. Never reset factory settings or clear the scene in the creator's open file.
9. Flush bmesh: `bm.to_mesh(mesh)` then `bm.free()`, or the mesh stays empty.
10. Seed randomness per asset (from its name), not once per script.

## Renames and removals

| Version | Old | New |
|---|---|---|
| 4.0 | Principled inputs `Emission`, `Specular`, `Subsurface`, `Clearcoat`, `Sheen`, `Transmission` | `Emission Color` + `Emission Strength`, `Specular IOR Level`, `Subsurface Weight`, `Coat Weight`, `Sheen Weight`, `Transmission Weight` |
| 4.0 | Bevel weight and crease as mesh properties | Generic attributes `bevel_weight_edge` and `crease_edge` |
| 4.1 | `mesh.use_auto_smooth` (removed; old scripts crash) | See "Smooth by Angle and Weighted Normal" below |
| 4.2 | EEVEE engine id `BLENDER_EEVEE` | `BLENDER_EEVEE_NEXT` in 4.2 to 4.5 |
| 4.2 | `material.blend_method` | `material.surface_render_method` (old Opaque and Alpha Clip map to the deferred method; read the enum) |
| 4.5 | Boolean solvers EXACT and FAST only | `MANIFOLD` added (fast, but every operand must be manifold: each edge on exactly two faces) |
| 5.0 | EEVEE engine id `BLENDER_EEVEE_NEXT` | `BLENDER_EEVEE` again. Code that runs on 4.2 to 5.x reads the enum and picks the one that exists |
| 5.0 | Boolean solver `FAST` | Renamed `FLOAT` (modifier and operator). `EXACT` stays the default and the safe choice |
| 5.0 | Compositor through `scene.node_tree` | `scene.node_tree` removed: `scene.compositing_node_group = bpy.data.node_groups.new(name, "CompositorNodeTree")`; `scene.use_nodes` is deprecated and always True |
| 5.0 | `action.fcurves`, `action.groups`, `action.id_root` | Removed with the legacy Action API. F-curves live in channelbags: `bpy_extras.anim_utils.action_get_channelbag_for_slot(action, slot)` to read, `action_ensure_channelbag_for_slot(action, slot)` to create |
| 5.0 | Bake writes to the active Image Texture node | The target Image Texture node must be **selected and active** in every material (see fix-model "Baking facts") |
| 5.2 | Geometry Nodes modifier inputs as custom properties (`md["Socket_2"]`, `md["Socket_2_use_attribute"]`) | Real RNA properties: `md.properties.inputs.<identifier>` (for example `.type = "ATTRIBUTE"`); check its fields with `dir()`, then call `obj.update_tag()`. Checked on 5.2.3: `md["Socket_N"] = v` raises `TypeError`; the input has `.value`, `.type`, `.attribute_name`. Helper: nighty-blender-procedural `references/gn-kit.md` |
| 5.2 | Geometry Nodes Mesh Boolean default solver | `FLOAT` in a new node (checked on 5.2.3): always set `solver = "EXACT"` |

Checked against the official Blender release notes for 4.2, 4.5, 5.0 and 5.2 (Nov 2026). Still read the enum or `bl_rna` in the creator's Blender: point releases move things.

### Smooth by Angle and Weighted Normal (4.1+)

- `object.shade_auto_smooth` adds a **Smooth by Angle modifier that is pinned last** (`use_pin_to_last = True`). Any modifier you add afterwards, Weighted Normal included, lands **above** it, and `modifiers.move` silently refuses to move past a pinned modifier.
- Weighted Normal reads sharp edges (Keep Sharp) and writes custom normals, so it must run **after** the sharpness is set. The correct stack is: cuts and booleans → bevel → (Mirror) → sharpness → **Weighted Normal last**.
- Easiest way to get that order: do not use the modifier. Run `object.shade_smooth_by_angle(angle=...)` once (it writes the `sharp_edge` attribute and adds no modifier), then add Weighted Normal at the bottom. Since 4.1 Weighted Normal no longer needs Auto Smooth turned on.
- If a Smooth by Angle modifier is already there, set its `use_pin_to_last = False` and move Weighted Normal below it.

### More traps

- `bmesh.ops.bevel` has no useful defaults: always pass `segments` and `profile`.
- `uv.unwrap` without `method=` uses whatever the operator default is in that version; always pass it (`"ANGLE_BASED"`, `"CONFORMAL"`, or `"MINIMUM_STRETCH"` from 4.3). It returns FINISHED even when some islands fail: count zero-area UV faces afterwards.
- `matrix_world` is stale after you change location or scale until `bpy.context.view_layer.update()`.
- New shape keys: set every key's `value` to 0 before export, or the mesh deforms at rest.
- Blender 5.1 ships Python 3.13 and NumPy 2: `np.ptp(a)`, not `a.ptp()`.

### Live-call discipline (`blender_run_python`)

- One logical change per call, so one `blender_undo` takes it back.
- Long jobs (big bakes, quad remesh of a dense mesh) go through the tools' own job system (`blender_texture { op: "bake" }`, `blender_mesh { op: "retopo" }`, then `blender_job { action: "wait", id }`), never one long `blender_run_python`.
- A call that timed out has an unknown outcome: read the scene (`blender_scene`) and the jobs (`blender_job { action: "list" }`) before you try again; never resend blindly.

## Export traps

| Trap | Fix |
|---|---|
| glTF export without applying modifiers drops bevels and weighted normals | Apply modifiers on export (`blender_export` does this) |
| glTF drops vertex colours unless exported as the active set | Export the active colour attribute |
| FBX arrives 100 times too big in Roblox | Apply Scalings "FBX Unit Scale"; or use `blender_export { made_for: "roblox" }` |
| Model arrives rotated or scaled | Apply rotation and scale before export |
| AO bake comes out black | Hide other objects from render; remove floaters and inside shells first |

## Failure catalogue (symptom, cause, fix)

| Symptom | Likely cause | Fix |
|---|---|---|
| Parts look joined in the front view but float in the side view | Placed by eye | `blender_measure { pairs }` for gaps; seat by bounding-box maths or `n.place_on` |
| Object at the wrong size, but "looked right" | Visual self-check | Compare with the spec using `blender_measure` before every look |
| Goofy, lumpy creature | Built from stacked primitives | Lofts or skin for big masses, then fuse into one body; inserts for small parts |
| Dark patches, black blotches | Flipped normals, inside faces | `blender_mesh { op: "cleanup" }`, then `blender_look { mode: "matcap" }` |
| Faceted curves in close-ups | Too few radial steps | 20 to 24 steps on hero curves, or accept and say so |
| Emblem or gem slightly off-centre | Centred by eye | Centre from the parent's bounds; check with `blender_check { what: "mesh", symmetry: "X" }` |
| Folded or self-crossing sweep | Profile points out of order, inset of a rounded outline | Keep profile points ordered; inset the sharp outline, then round it |
| Script "succeeds" but shapes are missing | Exceptions swallowed | Catch only the expected error, count and print every skip |
| `KeyError` on a socket | Renamed input | Use the new name, guard with `in node.inputs` |
| Poll error from an operator | No viewport context | Use the data or bmesh API, or `bpy.context.temp_override` with an explicit object |

<!-- SPDX-FileCopyrightText: 2026 NightyCode -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
