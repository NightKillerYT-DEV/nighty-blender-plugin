# Props and furniture recipes
Only when the person asks you to build in code: how the common props are built (each has a checked example to adapt: blender_guide examples with its name and a style).

A new prop otherwise comes from the person's file: `blender_import`, then `blender_make_game_ready` (workflow guide). Realistic and stylized code builds follow the same steps; the surfaces and proportions differ.

## Containers
- Crate (crate_hero realistic, crate_wooden stylized): core box, `n.planks` with 4-6 mm gaps set inside the frame, 12 frame battens, diagonal braces, `n.corner_bracket` caps, `n.nails`, handles on plates, stencil with `n.text3d`.
- Chest (chest_hero): arched lid from an extruded arc with `n.groove` plank seams, gold bands as arch rings, rivets, lock plate with a keyhole, ring handles, feet, a few coins beside it.
- Barrel (barrel_wooden): `n.lathe` with a bulge, stave seams following the curve, blackened hoops, recessed head. Oil drum (oil_drum): one lathe profile holds chimes, hoops and the pressed ring; stencil text bent around it with `n.deform(text, "bend", ...)`.
- Ammo can (ammo_box), med kit (medkit), sci-fi crate (scifi_crate), power cell (power_cell): raised or sunk side panels (`n.inset`), dark corner bumpers that are also the feet, latches, vents with glow behind.

## Furniture
- Table (table_wooden): planked top with breadboard ends 0.72-0.76 m high, turned lathe legs, apron set back 5-10 mm.
- Chair (chair_wooden): seat 0.45 m; each back leg is one bent side profile rising into the back post; stretchers; slats.
- Bench (bench_park): cast side frames (one extruded profile with a raised rim and a window), slats from `n.planks`.
- Bookshelf (bookshelf): carcass, face frame, crown, kick plinth, books with seeded sizes (standing, stacked, leaning).
- Door (door_wooden): stiles, rails and raised panels as separate pieces with their own grain, jambs, casing, hinges, lever.

## Lights and small items
- Desk lamp (lamp_desk), street lamp (street_lamp), lantern (lantern_fantasy): lathe bases and shades, `n.pipe` arms and curls, glow bulbs or panes (`n.surface(name, "glow", color=..., glow=2-6)`), glass.
- Mug (mug_ceramic), potion (potion_bottle): one closed lathe profile for the hollow wall (up the outside, down the inside), `n.pipe` handle, liquid as its own lathe. Walls at least 6 mm.
- Coin (coin_gold), key (key_ornate), gem (gem_crystal): small sizes need detail "low"; make pickups bigger than life (a 12 cm coin) so their bevels and highlights read.

## Industrial and modular
- Pipes and valves (pipe_valve): `n.pipe` with bends, gasketed flanges with nuts, a hand wheel, a gauge, a support.
- Hydrant (fire_hydrant), traffic cone (traffic_cone), wheel (wheel_tire), gear (gear_cog: one extruded outline with computed teeth and lightening holes, no booleans).
- Modular kit (modular_wall, floor_tile_scifi, scifi_panel): sizes on a grid (0.25, 1 or 2 m), origin where a level designer expects it (a corner or the bottom center), nothing sticking over the grid edges, seams from the edge bevels.

## Rules that make props look finished
- Silhouette, layered secondary forms, a few strong details, value contrast (see workflow: the detail bar).
- Wood: one `n.surface` per grain direction (`grain="X"`, `"Y"`, `"Z"`) so the grain runs along every board.
- Hardware darker or lighter than what it holds (iron on pine, gold on dark wood, grey latches on white plastic).
- One collection per prop, parts named, on the ground, mesh check clean, inside its triangle budget.
