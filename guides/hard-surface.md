# Hard-surface recipe: weapons, machines, vehicles
Only when the person asks you to build in code: parts with the library and the detail kit, checked one by one, bevels and surfaces. Examples: rifle_ar_hero, blaster_hero, pistol_stylized.

A new weapon or machine otherwise comes from the person's file: `blender_import`, then `blender_make_game_ready` (workflow guide). This recipe is for code builds the person asked for, and for small add-ons to a generated model (a sight, a rail, a strap).

## Plan
1. Reference: the person's picture (`blender_reference` load; a gun lying along X shows its side in the front view) or real-life sizes.
   Pistol 0.18-0.22 m long, SMG 0.5-0.6, rifle 0.85-1.0, sniper 1.1-1.3; barrel radius 6-12 mm; grip 0.1 m tall.
2. Parts list with sizes and a budget: receiver / body, barrel, handguard, muzzle, grip, trigger guard, trigger, magazine, stock, sights / rail, small parts. A hero weapon fits in 15000-20000 triangles.
3. Orientation: length along X (muzzle at +X), up is Z, thickness along Y. The front view then shows the side profile.

## Build order
1. Big forms from side profiles: `n.extrude(outline, depth, plane="XZ")`, outline points `(x, z, corner_radius)`. Stocks, grips, bodies, magazines (`n.spline` for curves).
2. Round parts: barrel `n.cylinder(r, length, axis="X")`, muzzle `n.tube` / `n.cone`, scope `n.lathe(profile, axis="X")`, handguard `n.tube`.
3. Place parts relative to each other: `n.align`, `n.snap`, `n.place_on`. Let parts overlap a few mm where they join.
4. Mark the outline: `n.mark_bevel(part)` before any cut.
5. Secondary forms (the kit): `n.panel_cut` (panel lines), `n.inset` (raised or sunk panels), `n.plate` (a plate with a label), chamfered plates and a darker chassis layered on the body, `n.grille` (a recess with bars, a glow box behind it), `n.vents` (vents, serrations, M-LOK slots), `n.groove` (seams), `n.hole`, `n.rail`, `n.pipe` (trigger guards, hoses), `n.cable` (hoses with clips).
6. A few strong small details: `n.bolts_along` / `n.bolts_around`, pins, `n.text3d` or `n.plate(text=...)` for stamped letters.
7. Finish: `n.bevel(part, width, limit="weight")` (0.8-1.8 mm on a real gun), `n.chamfer` for industrial edges, `n.chunky` for stylized ones. Surfaces per part with `n.surface` + `n.paint`.
8. Check: `blender_check { what: "mesh" }`, `blender_measure`, `blender_look` (matcap + wireframe), then the studio look (material, hero view).

## Realistic (CoD, Valorant)
- Real proportions, bevels 0.8-1.8 mm, many controls but each one simple (pins, release, selector, charging handle).
- Value contrast: black or dark-grey metal against tan (FDE) or wood furniture; a black-on-black gun reads as a blob.
- Surfaces: `n.surface("Receiver", "painted_metal", color="#33363b", wear=0.15, size=0.35)` (cerakote: dark grey sheen, chips to bare metal), "polymer" for furniture, "gunmetal" / "steel" for barrels and small parts, "rubber" for pads, "glass", "glow" for dots and lights.
- Wear 0.1-0.25. Higher wear outlines every edge. `size=` smaller than the asset makes the wear finer (a rifle wears in thin lines).

## Stylized (Fortnite, big Roblox games)
- Chunky proportions (barrel x1.5, bigger muzzle and sights), `n.chunky` edges, fewer and bigger details.
- Layers: a light shell over a dark chassis, grey plates with vents standing out of the shell, orange armor, pistons and blocks on the sides.
- Color blocks: light body, dark frame, one accent, one glow (`n.surface(name, "glow", color=..., glow=4-12)`).
- Surfaces: `style="stylized"` with "plastic", "steel", "gold"; avoid "painted_metal" (it chips to silver).

## Vehicles and machines
- Body from side and top profiles (extrude the side, cut the top shape with a second extrude as `n.boolean_intersect`), wheels from `n.lathe` + `n.radial` spokes, panel lines where parts meet, bolts at joints.

## Common mistakes
- Floating parts (a magazine 2 mm under the magwell): the mesh check lists them; align or snap them.
- Boxes without bevels, every part the same color, or the same lightness.
- Thin walls (a 3 mm tube) under realistic wear: the whole part turns to bare metal. Walls of 6 mm or more, or solid parts.
- A vent floor exactly on a neighbor's face: same-plane flicker. Make the vent 0.5 mm shallower.
- Mirroring with a negative scale turns a part inside out: mirror the outline points instead.
- Knurling and dozens of screws: thousands of triangles nobody sees. Let the material carry them.
- Wrong scale (a 3 m pistol): measure.
