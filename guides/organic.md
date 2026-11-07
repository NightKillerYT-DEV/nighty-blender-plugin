# Organic shapes: import, or build stylized when asked
Characters, creatures, plants and rocks: imported from the person's file; how to build stylized ones when the person asks for code.

## Route
- Every new organic model (people, animals, trees, rocks, mushrooms, clouds): the person's file, `blender_import`, then `blender_make_game_ready` (workflow guide). Tell the person that faces and hands may need hand touch-up for animation.
- Stylized organic built from soft primitives: only when the person asks for a code build. Quick, light and clean.
- Mixed (a creature with armor the person wants built): import the body from the person's file, build the asked-for hard parts with the library and place them on it (`n.place_on`).

## Building stylized organic shapes
- Blobs: `n.sphere` (quad sphere, no poles) squashed with scale, then `n.displace(obj, strength, scale, seed)` for lumps. Merge a few overlapping blobs for foliage and clouds.
- Trunks, stems, horns, tentacles: `n.lathe` with a `n.spline` profile (flared base, thin top) or `n.pipe` along a bent path; branches as `n.pipe` from the trunk outward, starting inside the trunk.
- Caps and shells: `n.dome` (height squashes it), `n.lathe` for bells and mushroom caps.
- Rocks: quad sphere with few sides (`segments=12-16`), displaced, stretched, base cut flat (`n.boolean_cut` with a big box below), `n.shade_flat` for a faceted look; moss as a second material on faces pointing up.
- Spots and decorations: small flattened domes placed with `n.place_on` so they follow the surface.
- Smooth look: `n.smooth_by_angle(obj, 180)` or `n.subdivide(obj, 1)` on all-quad shapes. Faceted look: `n.shade_flat`, detail "low".

## Rules
- Silhouette first: 3-5 big masses with clear size differences (one big, two medium, a few small).
- Everything overlaps a little where it joins; the mesh check must show no floating parts.
- Colors: two or three shades per material (light top, darker underside) read better than one.
- Examples: tree_stylized, rock_lowpoly, mushroom_stylized, gem_crystal.
