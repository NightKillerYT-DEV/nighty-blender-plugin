# Procedural prop recipes (tested)

Six Geometry Nodes recipes for Roblox props, built in studs and scaled to metres at the end. Each needs the helper kit from `gn-kit.md` in the same `blender_run_python` call. All six passed headless on Blender 5.2.3 LTS (Nov 2026): sizes within 5% of the spec, under the triangle target, 0 floating parts, 0 open edges, 0 n-gons, lowest point on z = 0, and seeds 0 to 5 on the random ones.

How to read each recipe:
- **Settings:** the exposed inputs, with defaults (studs unless noted).
- **Target:** the triangle target for its budget class, and what the defaults gave.
- **Checks:** the numbers to read after the bake, then what to look at.

## 1. Fence

Posts on a line every Post Spacing studs (count = ceil(Length ÷ spacing) + 1), rails as long boxes over the full length. Roughness gives each post a small random lean and height jitter.

- **Settings:** Length 16, Height 4, Post Spacing 4, Rails 2 (1 to 6), Seed, Roughness 0.3.
- **Target:** small prop, 600. Defaults: 84 tris (12 per box).
- **Checks:** X size = Length + 0.6 (post width), Z = Height (within 5%); rails touch every post (`blender_measure { pairs }` on a post and a rail); lowest point on 0 (the recipe grounds it after the lean). Look: front and top views, posts evenly spaced, no post outside the rails.
- **Variants:** pickets = more posts with Spacing 1; a gate = two short fences with a gap.

```python
def fence():
    t = Tree("NB_Fence")
    t.inp("Length", "float", 16.0, 2.0, 200.0)
    t.inp("Height", "float", 4.0, 1.0, 20.0)
    t.inp("Post Spacing", "float", 4.0, 1.0, 20.0)
    t.inp("Rails", "int", 2, 1, 6)
    t.inp("Seed", "int", 0)
    t.inp("Roughness", "float", 0.3, 0.0, 1.0, "Post lean and height jitter")
    L, H = t.g("Length"), t.g("Height")
    # posts: ceil(L / spacing) + 1 points from x=0 to x=L
    n = t.math("ADD", t.math("CEIL", t.math("DIVIDE", L, t.g("Post Spacing"))), 1.0)
    line = t.node("GeometryNodeMeshLine", {"mode": "END_POINTS"},
                  {"Count": n, "Start Location": (0, 0, 0), "End Location": t.xyz(L, 0, 0)})
    post = t.node("GeometryNodeMeshCube", ins={"Size": t.xyz(0.6, 0.6, H)})
    post_up = t.node("GeometryNodeTransform", ins={"Geometry": post.outputs[0], "Translation": t.xyz(0, 0, t.math("MULTIPLY", H, 0.5))})
    lean = t.math("MULTIPLY", t.g("Roughness"), 0.06)  # radians
    rot = t.node("FunctionNodeRandomValue", {"data_type": "FLOAT_VECTOR"},
                 {"Min": t.xyz(t.math("MULTIPLY", lean, -1.0), t.math("MULTIPLY", lean, -1.0), 0.0),
                  "Max": t.xyz(lean, lean, 0.0), "Seed": t.g("Seed")})
    hj = t.math("MULTIPLY", t.g("Roughness"), 0.08)
    sc = t.node("FunctionNodeRandomValue", {"data_type": "FLOAT"},
                {"Min": t.math("SUBTRACT", 1.0, hj), "Max": 1.0, "Seed": t.math("ADD", t.g("Seed"), 7.0)})
    posts = t.node("GeometryNodeInstanceOnPoints", ins={"Points": line.outputs[0], "Instance": post_up.outputs[0],
                                                        "Rotation": sock(rot.outputs, "Value"),
                                                        "Scale": t.xyz(1.0, 1.0, sock(sc.outputs, "Value"))})
    # rails: points up the fence between 35% and 80% of the height, each a long thin box over the full length
    rails_line = t.node("GeometryNodeMeshLine", {"mode": "END_POINTS"},
                        {"Count": t.g("Rails"), "Start Location": t.xyz(0, 0, t.math("MULTIPLY", H, 0.35)),
                         "End Location": t.xyz(0, 0, t.math("MULTIPLY", H, 0.8))})
    rail = t.node("GeometryNodeMeshCube", ins={"Size": t.xyz(L, 0.25, 0.4)})
    rail_mid = t.node("GeometryNodeTransform", ins={"Geometry": rail.outputs[0], "Translation": t.xyz(t.math("MULTIPLY", L, 0.5), 0.3, 0)})
    rails = t.node("GeometryNodeInstanceOnPoints", ins={"Points": rails_line.outputs[0], "Instance": rail_mid.outputs[0]})
    join = t.node("GeometryNodeJoinGeometry")
    t.link(posts.outputs[0], join.inputs[0])
    t.link(rails.outputs[0], join.inputs[0])
    real = t.node("GeometryNodeRealizeInstances", ins={"Geometry": join.outputs[0]})
    return t.finish(t.ground(real.outputs[0]))
```

## 2. Stairs

One block per step: block k spans depth k × D to (k + 1) × D and height 0 to (k + 1) × step height. An EXACT union joins them into one closed body with no hidden inner faces.

- **Settings:** Width 6, Steps 8, Step Height 1 (Roblox characters climb about 1 stud comfortably; keep 0.5 to 1.2), Step Depth 1.5.
- **Target:** small prop, 600. Defaults: 96 tris, 1 island.
- **Checks:** size = (Width, Steps × Depth, Steps × Step Height) within 5%; 0 open edges (a weld instead of a union breaks this); one island. Look: right view shows an even staircase profile. In Studio, walk up it with the default character.

```python
def stairs():
    t = Tree("NB_Stairs")
    t.inp("Width", "float", 6.0, 1.0, 40.0)
    t.inp("Steps", "int", 8, 1, 64)
    t.inp("Step Height", "float", 1.0, 0.25, 4.0)
    t.inp("Step Depth", "float", 1.5, 0.5, 6.0)
    D, Hs = t.g("Step Depth"), t.g("Step Height")
    line = t.node("GeometryNodeMeshLine", {"mode": "OFFSET"}, {"Count": t.g("Steps"), "Offset": (0, 0, 0)})
    i = t.node("GeometryNodeInputIndex").outputs[0]
    i1 = t.math("ADD", i, 1.0)
    # block k spans y in [k*D, (k+1)*D], z in [0, (k+1)*Hs]
    pos = t.xyz(0.0, t.math("MULTIPLY", t.math("ADD", i, 0.5), D), t.math("MULTIPLY", t.math("MULTIPLY", i1, Hs), 0.5))
    sp = t.node("GeometryNodeSetPosition", ins={"Geometry": line.outputs[0], "Position": pos})
    cube = t.node("GeometryNodeMeshCube", ins={"Size": t.xyz(t.g("Width"), D, 1.0)})
    inst = t.node("GeometryNodeInstanceOnPoints", ins={"Points": sp.outputs[0], "Instance": cube.outputs[0],
                                                       "Scale": t.xyz(1.0, 1.0, t.math("MULTIPLY", i1, Hs))})
    # one closed body: EXACT union removes the hidden inner faces (5.2's node defaults to FLOAT: always set it).
    # Instances go straight in: each one is its own operand.
    uni = t.node("GeometryNodeMeshBoolean", {"operation": "UNION", "solver": "EXACT"}, {"Self Intersection": True})
    t.link(inst.outputs[0], sock(uni.inputs, "Mesh 2"))
    return t.finish(sock(uni.outputs, "Mesh"))
```

## 3. Rock or boulder

An Ico Sphere pushed along its normals by 4D noise (W = Seed), the underside flattened so it sits, then fitted to the exact size with Bounding Box and grounded.

- **Settings:** Size X 4, Size Y 3, Size Z 2.5, Detail 3 (Ico subdivisions: 2 = 80 tris, 3 = 320), Seed, Roughness 0.35.
- **Target:** rock, 400. Defaults: 320 tris. Use Detail 2 (80 tris) for scatter rocks.
- **Checks:** size exactly as set (the fit makes it so); one island, 0 open edges; seeds 0 to 5 all pass. Look: silhouette view, it should not read as a ball; raise Roughness or squash Size Z if it does.

```python
def rock():
    t = Tree("NB_Rock")
    t.inp("Size X", "float", 4.0, 0.5, 40.0)
    t.inp("Size Y", "float", 3.0, 0.5, 40.0)
    t.inp("Size Z", "float", 2.5, 0.5, 40.0)
    t.inp("Detail", "int", 3, 1, 4, "Ico sphere subdivisions: 2 = 80 tris, 3 = 320")
    t.inp("Seed", "int", 0)
    t.inp("Roughness", "float", 0.35, 0.0, 1.0)
    ico = t.node("GeometryNodeMeshIcoSphere", ins={"Radius": 0.5, "Subdivisions": t.g("Detail")})
    noise = t.node("ShaderNodeTexNoise", {"noise_dimensions": "4D"},
                   {"W": t.g("Seed"), "Scale": 1.6, "Detail": 2.0})
    # push along the normal by (noise - 0.5) * roughness
    amt = t.math("MULTIPLY", t.math("SUBTRACT", sock(noise.outputs, "Fac"), 0.5), t.g("Roughness"))
    nrm = t.node("GeometryNodeInputNormal").outputs[0]
    off = t.node("ShaderNodeVectorMath", {"operation": "SCALE"})
    t.link(nrm, off.inputs[0])
    t.link(amt, sock(off.inputs, "Scale"))
    sp = t.node("GeometryNodeSetPosition", ins={"Geometry": ico.outputs[0], "Offset": off.outputs[0]})
    # flatten the underside so it sits: z = max(z, -0.3)
    pos = t.node("ShaderNodeSeparateXYZ")
    t.link(t.node("GeometryNodeInputPosition").outputs[0], pos.inputs[0])
    flat = t.xyz(pos.outputs[0], pos.outputs[1], t.math("MAXIMUM", pos.outputs[2], -0.3))
    sp2 = t.node("GeometryNodeSetPosition", ins={"Geometry": sp.outputs[0], "Position": flat})
    # fit to the requested size exactly, bottom on z = 0
    bb = t.node("GeometryNodeBoundBox", ins={"Geometry": sp2.outputs[0]})
    ext = t.node("ShaderNodeVectorMath", {"operation": "SUBTRACT"})
    t.link(sock(bb.outputs, "Max"), ext.inputs[0])
    t.link(sock(bb.outputs, "Min"), ext.inputs[1])
    want = t.xyz(t.g("Size X"), t.g("Size Y"), t.g("Size Z"))
    k = t.node("ShaderNodeVectorMath", {"operation": "DIVIDE"})
    t.link(want, k.inputs[0])
    t.link(ext.outputs[0], k.inputs[1])
    centre = t.node("ShaderNodeVectorMath", {"operation": "ADD"})
    t.link(sock(bb.outputs, "Max"), centre.inputs[0])
    t.link(sock(bb.outputs, "Min"), centre.inputs[1])
    cx = t.node("ShaderNodeSeparateXYZ")
    t.link(centre.outputs[0], cx.inputs[0])
    mz = t.node("ShaderNodeSeparateXYZ")
    t.link(sock(bb.outputs, "Min"), mz.inputs[0])
    move = t.xyz(t.math("MULTIPLY", cx.outputs[0], -0.5), t.math("MULTIPLY", cx.outputs[1], -0.5), t.math("MULTIPLY", mz.outputs[2], -1.0))
    t1 = t.node("GeometryNodeTransform", ins={"Geometry": sp2.outputs[0], "Translation": move})
    t2 = t.node("GeometryNodeTransform", ins={"Geometry": t1.outputs[0], "Scale": k.outputs[0]})
    return t.finish(t2.outputs[0])
```

## 4. Modular wall with windows

A slab with its origin at the left-bottom corner (x from 0 to Width), minus window cutters spaced so all piers are equal: pier = (Width − n × window width) ÷ (n + 1). EXACT difference, cutters twice the wall thickness so they pass fully through.

- **Settings:** Width 16, Height 12, Thickness 1, Windows 2 (0 to 8), Window Width 3, Window Height 4, Sill Height 3.5.
- **Target:** kit module, 800. Defaults: 52 tris.
- **Checks:** size = (Width, Thickness, Height); keep Width on the kit grid (4, 8 or 16 studs) so modules snap; piers must stay positive (n × window width < Width), Sill above 0 and Sill + Window Height below Height (a cutter flush with the top or bottom face is the classic boolean failure); 0 open edges. Look: front view, windows evenly spaced. A doorway variant (opening 4 wide, 7 to 8 tall) needs its cutter to start below the floor; that variant is not in the tested set.

```python
def wall():
    t = Tree("NB_Wall")
    t.inp("Width", "float", 16.0, 4.0, 64.0)
    t.inp("Height", "float", 12.0, 4.0, 40.0)
    t.inp("Thickness", "float", 1.0, 0.2, 4.0)
    t.inp("Windows", "int", 2, 0, 8)
    t.inp("Window Width", "float", 3.0, 1.0, 12.0)
    t.inp("Window Height", "float", 4.0, 1.0, 20.0)
    t.inp("Sill Height", "float", 3.5, 0.0, 20.0)
    W, H, T = t.g("Width"), t.g("Height"), t.g("Thickness")
    n, ww, wh, sill = t.g("Windows"), t.g("Window Width"), t.g("Window Height"), t.g("Sill Height")
    # slab with its origin at the left-bottom-centre (kit grid corner), then EXACT difference with window cutters
    slab = t.node("GeometryNodeMeshCube", ins={"Size": t.xyz(W, T, H)})
    slab = t.node("GeometryNodeTransform", ins={"Geometry": slab.outputs[0], "Translation": t.xyz(t.math("MULTIPLY", W, 0.5), 0, t.math("MULTIPLY", H, 0.5))})
    # equal piers: pier = (W - n*ww) / (n + 1); window k centre x = pier*(k+1) + ww*(k+0.5)
    pw = t.math("DIVIDE", t.math("SUBTRACT", W, t.math("MULTIPLY", n, ww)), t.math("ADD", n, 1.0))
    line = t.node("GeometryNodeMeshLine", {"mode": "OFFSET"},
                  {"Count": n,
                   "Start Location": t.xyz(t.math("ADD", pw, t.math("MULTIPLY", ww, 0.5)), 0, t.math("ADD", sill, t.math("MULTIPLY", wh, 0.5))),
                   "Offset": t.xyz(t.math("ADD", pw, ww), 0, 0)})
    # cutter passes fully through: 2x the wall thickness
    cutter = t.node("GeometryNodeMeshCube", ins={"Size": t.xyz(ww, t.math("MULTIPLY", T, 2.0), wh)})
    cutters = t.node("GeometryNodeInstanceOnPoints", ins={"Points": line.outputs[0], "Instance": cutter.outputs[0]})
    diff = t.node("GeometryNodeMeshBoolean", {"operation": "DIFFERENCE", "solver": "EXACT"})
    t.link(slab.outputs[0], sock(diff.inputs, "Mesh 1"))
    t.link(cutters.outputs[0], sock(diff.inputs, "Mesh 2"))
    return t.finish(sock(diff.outputs, "Mesh"))
```

## 5. Simple tree

An 8-sided trunk, a core canopy blob over the trunk top, and Blobs side blobs placed at 0.3 × Canopy from the core centre in random directions, each 0.22 to 0.3 × Canopy in radius, so every blob overlaps the core (nothing floats at any seed).

- **Settings:** Height 14, Canopy 8 (diameter), Trunk Radius 0.6, Blobs 5 (0 to 12), Seed, Detail 2 (Ico subdivisions per blob).
- **Target:** tree, 2,000. Defaults: 508 tris. Detail 1 gives a faceted low-poly look at about 170 tris.
- **Checks:** height within 5% of the setting (seeds 0 to 5 gave 13.6 to 14.6); canopy width about Canopy ± 1; 0 floating (blobs overlap the core). Look: four views, the canopy should not look like a stack of balls from the side; more Blobs or a lower Detail fixes most of it.

```python
def tree():
    t = Tree("NB_Tree")
    t.inp("Height", "float", 14.0, 4.0, 60.0)
    t.inp("Canopy", "float", 8.0, 2.0, 40.0, "Canopy diameter")
    t.inp("Trunk Radius", "float", 0.6, 0.2, 4.0)
    t.inp("Blobs", "int", 5, 0, 12)
    t.inp("Seed", "int", 0)
    t.inp("Detail", "int", 2, 1, 3)
    H, C = t.g("Height"), t.g("Canopy")
    trunk_h = t.math("SUBTRACT", H, t.math("MULTIPLY", C, 0.75))
    trunk = t.node("GeometryNodeMeshCylinder", ins={"Vertices": 8, "Radius": t.g("Trunk Radius"), "Depth": trunk_h})
    trunk = t.node("GeometryNodeTransform", ins={"Geometry": sock(trunk.outputs, "Mesh"), "Translation": t.xyz(0, 0, t.math("MULTIPLY", trunk_h, 0.5))})
    cz = t.math("ADD", trunk_h, t.math("MULTIPLY", C, 0.25))
    core = t.node("GeometryNodeMeshIcoSphere", ins={"Radius": t.math("MULTIPLY", C, 0.45), "Subdivisions": t.g("Detail")})
    core = t.node("GeometryNodeTransform", ins={"Geometry": core.outputs[0], "Translation": t.xyz(0, 0, cz)})
    # side blobs: random directions, 0.3 C from the core centre, radius 0.22-0.3 C, so each overlaps the core
    pts = t.node("GeometryNodePoints", ins={"Count": t.g("Blobs")})
    rv = t.node("FunctionNodeRandomValue", {"data_type": "FLOAT_VECTOR"}, {"Min": (-1, -1, -0.4), "Max": (1, 1, 0.8), "Seed": t.g("Seed")})
    nv = t.node("ShaderNodeVectorMath", {"operation": "NORMALIZE"})
    t.link(sock(rv.outputs, "Value"), nv.inputs[0])
    dv = t.node("ShaderNodeVectorMath", {"operation": "SCALE"})
    t.link(nv.outputs[0], dv.inputs[0])
    t.link(t.math("MULTIPLY", C, 0.3), sock(dv.inputs, "Scale"))
    at = t.node("ShaderNodeVectorMath", {"operation": "ADD"})
    t.link(dv.outputs[0], at.inputs[0])
    t.link(t.xyz(0, 0, cz), at.inputs[1])
    sp = t.node("GeometryNodeSetPosition", ins={"Geometry": pts.outputs[0], "Position": at.outputs[0]})
    blob = t.node("GeometryNodeMeshIcoSphere", ins={"Radius": 1.0, "Subdivisions": t.g("Detail")})
    rs = t.node("FunctionNodeRandomValue", {"data_type": "FLOAT"},
                {"Min": t.math("MULTIPLY", C, 0.22), "Max": t.math("MULTIPLY", C, 0.3), "Seed": t.math("ADD", t.g("Seed"), 11.0)})
    blobs = t.node("GeometryNodeInstanceOnPoints", ins={"Points": sp.outputs[0], "Instance": blob.outputs[0], "Scale": sock(rs.outputs, "Value")})
    join = t.node("GeometryNodeJoinGeometry")
    for g in (trunk.outputs[0], core.outputs[0], blobs.outputs[0]):
        t.link(g, join.inputs[0])
    real = t.node("GeometryNodeRealizeInstances", ins={"Geometry": join.outputs[0]})
    return t.finish(real.outputs[0])
```

## 6. Barrel (crate variant below)

A cylinder with 6 side segments, bulged in the middle by scale = 1 + Bulge × (1 − u²) where u runs from −1 at the bottom to 1 at the top, plus two hoops at 20% and 80% of the height sized to the bulged radius there (u = ±0.6) plus a small lip.

- **Settings:** Height 3, Radius 1, Bulge 0.12, Sides 12 (6 to 32).
- **Target:** small prop, 600. Defaults: 252 tris.
- **Checks:** height 3 within 5%; width about 2 × Radius × (1 + Bulge) plus the hoop lip; hoops touch the body (`blender_measure { pairs }`); symmetry passes (`blender_check { what: "mesh", symmetry: "X" }`). Look: front and top, the hoops must not float off the bulge.
- **Crate variant:** a Mesh Cube of Size (S, S, S) grounded, plus 12 edge planks as thin boxes instanced on the cube's edges (Mesh to Points on edge midpoints is easiest), joined and realized; target 300 to 600 tris. Not part of the tested set.

```python
def barrel():
    t = Tree("NB_Barrel")
    t.inp("Height", "float", 3.0, 1.0, 12.0)
    t.inp("Radius", "float", 1.0, 0.3, 6.0)
    t.inp("Bulge", "float", 0.12, 0.0, 0.4, "Extra radius at the middle, as a fraction")
    t.inp("Sides", "int", 12, 6, 32)
    H, R, B, S = t.g("Height"), t.g("Radius"), t.g("Bulge"), t.g("Sides")
    body = t.node("GeometryNodeMeshCylinder", ins={"Vertices": S, "Side Segments": 6, "Radius": R, "Depth": H})
    body = t.node("GeometryNodeTransform", ins={"Geometry": sock(body.outputs, "Mesh"), "Translation": t.xyz(0, 0, t.math("MULTIPLY", H, 0.5))})
    # bulge: scale XY by 1 + B * (1 - u^2), u = 2z/H - 1
    p = t.node("ShaderNodeSeparateXYZ")
    t.link(t.node("GeometryNodeInputPosition").outputs[0], p.inputs[0])
    u = t.math("SUBTRACT", t.math("DIVIDE", t.math("MULTIPLY", p.outputs[2], 2.0), H), 1.0)
    f = t.math("ADD", 1.0, t.math("MULTIPLY", B, t.math("SUBTRACT", 1.0, t.math("MULTIPLY", u, u))))
    bul = t.node("GeometryNodeSetPosition", ins={"Geometry": body.outputs[0],
                 "Position": t.xyz(t.math("MULTIPLY", p.outputs[0], f), t.math("MULTIPLY", p.outputs[1], f), p.outputs[2])})
    # two hoops at 20% and 80% height, radius = bulged radius there (u = +-0.6) + 0.06
    hoop_r = t.math("ADD", t.math("MULTIPLY", R, t.math("ADD", 1.0, t.math("MULTIPLY", B, 0.64))), 0.06)
    hoop = t.node("GeometryNodeMeshCylinder", ins={"Vertices": S, "Radius": hoop_r, "Depth": t.math("MULTIPLY", H, 0.06)})
    hl = t.node("GeometryNodeMeshLine", {"mode": "END_POINTS"},
                {"Count": 2, "Start Location": t.xyz(0, 0, t.math("MULTIPLY", H, 0.2)), "End Location": t.xyz(0, 0, t.math("MULTIPLY", H, 0.8))})
    hoops = t.node("GeometryNodeInstanceOnPoints", ins={"Points": hl.outputs[0], "Instance": sock(hoop.outputs, "Mesh")})
    join = t.node("GeometryNodeJoinGeometry")
    t.link(bul.outputs[0], join.inputs[0])
    t.link(hoops.outputs[0], join.inputs[0])
    real = t.node("GeometryNodeRealizeInstances", ins={"Geometry": join.outputs[0]})
    return t.finish(real.outputs[0])
```

<!-- SPDX-FileCopyrightText: 2026 NightyCode -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
