# Blender 4.2 to 5.x: what changed in the Python API
Most broken scripts are API drift. Use the nighty helpers (n.compat) or these replacements.

| Old code that breaks | Use |
|---|---|
| `scene.render.engine = "BLENDER_EEVEE"` on 4.x / `"BLENDER_EEVEE_NEXT"` on 5.x | `n.compat.set_engine(scene, "eevee")` |
| Boolean `solver = "FAST"` (5.0 renamed it FLOAT; 5.x adds MANIFOLD) | `n.compat.boolean_solver("fast")`, or `n.boolean_cut(..., solver="auto")` |
| `scene.node_tree` / `scene.use_nodes` for the compositor (5.0: `scene.compositing_node_group`) | `n.compat.compositor_tree(scene)` |
| `action.fcurves` (5.0: layered actions, slots and channelbags) | `n.compat.fcurves(obj)`, `n.compat.find_fcurve(obj, "location", 2)`, `n.compat.keyframe(obj, "location", frame, value)` |
| `mesh.use_auto_smooth`, `auto_smooth_angle` (removed in 4.1) | `n.smooth_by_angle(obj, 30)` (`mesh.set_sharp_from_angle`) |
| `mesh.calc_normals_split()` (removed in 4.1) | `mesh.corner_normals` |
| Principled sockets "Emission", "Specular", "Subsurface", "Transmission", "Clearcoat", "Sheen" (renamed in 4.0) | "Emission Color", "Specular IOR Level", "Subsurface Weight", "Transmission Weight", "Coat Weight", "Sheen Weight"; `n.compat.set_input(node, name, value)` accepts both |
| `material.blend_method` (EEVEE Next) | `n.compat.set_transparent(material)` (`surface_render_method`) |
| `brush.sculpt_tool` (5.x: `sculpt_brush_type`) | `getattr(brush, n.compat.sculpt_brush_type_attr())` |
| `scene["cycles"]` dict access to add-on properties (5.0) | `scene.cycles.samples` |
| `bgl`, `Image.bindcode` (removed) | the `gpu` module |
| UV selection on mesh UV layers (5.0 moved it to BMesh) | edit UVs through `bmesh` loops |
| `material.use_nodes = True` needed on 4.x, always on in 5.x | `n.compat.ensure_nodes(material)` |

## Other gotchas
- Look nodes up by type, never by name (names are translated): `n.compat.node(tree, "BSDF_PRINCIPLED")`.
- Never hardcode dynamic enums; read them: `n.compat.enum_items(bpy.types.BooleanModifier, "solver")`.
- Material colors live on shader node inputs; `material.diffuse_color` is only the viewport color (`n.material` sets both).
- `obj.dimensions` and `matrix_world` are stale right after making or moving objects: call `n.update()` or use `n.bounds(obj)`.
- 5.x `mathutils` Vectors are float32: compare with a tolerance (1e-6), not `==`.
- Blender 5.1+ runs Python 3.13; 4.2 runs 3.11. numpy is there in both.
- Operators need a context; prefer data API calls (the nighty helpers never need one). If you must: `with bpy.context.temp_override(object=obj, active_object=obj): ...`.
- bmesh: call `bm.verts.ensure_lookup_table()` before indexing; `bm.free()` after `bm.to_mesh(mesh)`.
- Object mode: edit-mode data is not saved to the mesh until you leave edit mode; build meshes with bmesh in object mode.
