# Texturing: materials per part, wear, decals, bake, export
How to make textures that are sharp, physically right and game-ready (the opposite of smeared, blurry textures).

## One material library, two ways in
- In code while modeling: `mat = n.surface(name, kind, color=, style=, wear=, dirt=, roughness=, grain=, glow=, size=)`
  then `n.paint(parts, mat)`. With tools: `blender_texture { op: "assign_materials" }` (below). Same kinds, same wear and dirt, same bake.
- style "realistic" (wear and dirt from the real geometry), "stylized" (game look: soft gradient, painted edge
  highlights, clean, metals stay metal), "painted" (light and shadow painted into the colors).
- Thin parts: realistic wear reads walls under about 5 mm as edges (the whole part goes bare metal), the stylized
  look paints parts under about 5 mm light. Make them thicker, or wear=0 for strings and wires.
- Flat shiny stylized metal (gold) can look dark: roughness 0.4-0.55. Glow 2-6 with a saturated color; brighter
  washes out.

## Order
1. The options first (`blender_make_game_ready { menu: true }` = the menu to ask the person: Mesh, Detail, Textures,
   Texture type, Size, Made for, or a preset like "Realistic weapon" / "Roblox prop"). Every step reads the answer.
2. Parts with their own names and clean UVs (topology step), on the ground, mesh check clean.
3. `blender_texture { op: "assign_materials", parts: { Barrel: "steel", Grip: "polymer", Stock: "wood" } }`. `parts: {}` lists the library.
   A part can take `{ material, color, wear, dirt, roughness }`. Assigning again is instant (one part, one material).
4. `blender_texture { op: "decal" }` for every logo, warning label, serial number or text. Never paint text into a material.
5. op stylize only for a hand-painted look (or `style: "stylized"` in assign_materials).
6. Look with Cycles (wear and dirt come from the real geometry; they show in Cycles and after the bake).
7. op bake (a job: `blender_job { action: "wait" }`), then `blender_check { what: "textures" }` (read the picture),
   then `blender_export { made_for }`. Lines along UV seams in game: op fix_seams.

## Picking materials
- Metal or not is a fact, never a guess: metallic is exactly 0 or 1 per material. Painted metal is paint (0) with
  bare metal (1) only where the paint is chipped.
- Guns: receiver / slide gunmetal or dark painted_metal (cerakote reads better than black anodized), barrel steel,
  handguard / grip polymer or rubber, furniture wood or tan polymer, sights aluminum or anodized_aluminum, lenses
  glass, lights emissive. Props: painted_metal, wood, rubber, plastic.
- Colors for paint, plastic, fabric, anodized and emissive come from `color` ('#rrggbb'); other materials keep
  their real color.
- Wear 0.1-0.25 new, 0.3-0.45 used, 0.5-0.7 battered. Dirt 0.1-0.3 indoor / weapons, 0.4-0.6 environment.

## Decals and text
- `blender_texture { op: "decal", part, text: "NB-7", side: "left", size: 0.08, offset: [0.02, 0.01], color: "#e8e4d8" }`;
  `image: "C:/logo.png"` for a picture (PNG with transparency). `outline: 0.06` for text on busy surfaces.
- The decal follows its projector (an Image empty, parented to the part): move it, then bake again.
- `remove: "NB-7"` takes it off.

## Bake and check
- One texture set for all parts (UVs are packed into one atlas; the person's UV map stays as the second one).
- Size: 1K small props / Roblox, 2K weapons and characters, 4K hero assets only.
- The texture check must pass: blur, metallic 0/1, no lighting in the albedo (PBR), no unbaked pixels, seams,
  normal map. The final check reads its report. If it fails: fix the cause (UVs, materials), bake again.
- A high poly next to the low (`<part>_high`, or `high: { Part: "Part_high" }`) gives the normal and AO maps.
- An imported model after retopo: its dense original is the high poly. Bake with `from_high: true` carries the
  model's own colors, roughness and metallic onto the low poly (then give metal parts real materials if they look off).
- Ragged texture colors (op `clean_colors`, make_game_ready option `colors`): some textures have ragged borders, dark halos, stray
  bands and painted highlights. Auto cleans them on the dense surface before retopo: mostly flat colors (stylized,
  plastic) -> one flat color per region with crisp borders; real detail (wood grain) -> colors kept, only metal (0 / 1)
  and roughness per region. Force with `clean` / `keep`; `restore` brings the model's own material back. Bake again
  after running it by hand. The regions also pick the materials per part (wood body, brass latch).

## Engines (blender_export made_for)
- roblox: one MeshPart (joined), studs (1 stud = 0.28 m), SurfaceAppearance maps Color / Normal (OpenGL) /
  Roughness / Metalness / Emissive mask, 1024 px, under 20,000 triangles per mesh.
- unity: FBX in meters, URP Metallic+Smoothness map and HDRP Mask Map, OpenGL normal.
- unreal: FBX (imports in cm), ORM texture (occlusion R, roughness G, metallic B), DirectX normal.
- godot / gltf: .glb with everything inside (base color, normal, ORM, emission).
- blender: a .blend with the materials (procedural or baked) and the maps.
