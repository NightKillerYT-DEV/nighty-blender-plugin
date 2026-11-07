# Topology and shape rules
Meshes that shade well, export cleanly and hold up close: the rules behind the mesh check.

## Faces
- Quads on curved surfaces and anything that bends or deforms.
- Flat n-gons are fine on flat faces (they shade flat with weighted normals); n-gons on curved faces are not.
- Triangles are fine in game exports (engines triangulate); avoid long thin slivers and fans on curved areas.
- Even density: small parts not much denser than big ones (`faces_per_m2` in the mesh check).
- Poles (3 or 5+ edges at a point) on flat areas, not on curved highlights.

## Closed and connected
- Every piece is a closed shell (no holes) unless it is a card, leaf or decal (`allow_open`).
- Every piece touches another piece or the ground: nothing floats (the mesh check lists floating parts).
- Parts may overlap a little where they join (a barrel 5 mm into the receiver). Don't leave a gap.
- No two pieces with faces on the same plane facing the same way and overlapping: they flicker. Set one back by 1 mm.
- One object per part that moves, swaps or gets its own material region; merge small fixed details (`n.merge_parts`).

## Round shapes
- Sides come from the size on screen: `n.segments(radius)`; detail low / medium / high. Never 8-sided cylinders.
- Explicit few sides only on purpose: hex nuts (6), faceted gems, low-poly rocks.
- Many tiny repeats (rivets, dots, wraps): pass `segments=12` or use detail "low" to keep the count down.
- Caps: flat n-gon caps for hard-surface (with bevel and weighted normals); `caps="quad"` for subdivision.

## Edges and shading
- Real objects have no razor edges: `n.bevel(part)` (even segments, 30 degree angle limit, harden normals, Weighted Normal).
- Bevel width about 1-3 % of the part's smallest size and below half of its narrowest groove or rounded corner. `n.bevel` lowers a width that would make faces overlap (it says the width it used).
- Smooth shading, sharp by angle (30 degrees). Flat shading only for a faceted low-poly style (`n.shade_flat`).
- Cut first, bevel after (`n.boolean_cut`, `n.hole`, `n.panel_cut`, `n.vents`, then `n.bevel`). The library keeps the modifier order.
- Fine details stay crisp: `n.mark_bevel(part)` before cutting, then `n.bevel(part, limit="weight")`.
- Parts that get cut: `n.box` + `n.bevel`, not `n.rounded_box` (cutting rounded corners leaves bent faces).
- Subdivision (`n.subdivide`) only on all-quad parts with support loops (a 2-segment bevel works as one).

## Booleans
- Cutters are closed meshes that pass fully through the surface (cut 1-2 mm deeper than needed).
- Avoid faces exactly on top of each other between the two meshes (same thickness, flush sides): make one 0.5-1 mm bigger or smaller. Blender 4.2's exact solver leaves slivers there.
- After a cut: `blender_check { what: "mesh" }`. Open edges after a cut mean the cutter was open or only touched the surface.
- `solver="auto"` picks the exact solver (or manifold on big meshes in Blender 5.x).

## Size, scale, origin
- Real meters; transforms applied (scale 1); on the ground; origin at the base center (`n.set_origin(obj, "bottom")`) or at a grid corner for modular pieces.
- Triangle budgets: background prop 200-2k, prop 2k-15k, hero weapon 8k-40k, character 5k-60k, Roblox mesh under 20k per part.
