# Gate scripts for `blender_run_python`

Short read-only checks that back the numbers in "Gates in numbers". Each one reads the scene, returns a `result` dictionary and changes nothing, except the re-import check, which removes exactly what it imported. Scripts 1 to 4 use only what `blender_run_python` already provides (`bpy`, `bmesh`, `mathutils`, `math`, `random`), so they run at the "safe" level. Script 5 reads a file, which only the "full" level allows: use `blender_check { what: "roundtrip" }` first, and script 5 only for what that check does not report. The safety level is the creator's to set in Blender's Nighty tab: if script 5 is refused, tell them what it needs and let them decide.

Replace the names in CAPITALS. Report the numbers to the creator before you change anything.

## 1. Part contact: floating, touching, z-fighting

Gate one prop at a time. The parts must be separate objects; for loose parts inside one object, check a copy after `blender_mesh { op: "split_parts" }`, or rely on the floating count of `blender_check { what: "mesh" }`.

```python
NAMES = ["BODY", "PART_A", "PART_B"]
dg = bpy.context.evaluated_depsgraph_get()

def world_mesh(name):
    ob = bpy.data.objects[name]
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    verts = [ob.matrix_world @ v.co for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons]
    ev.to_mesh_clear()
    return verts, polys, mathutils.bvhtree.BVHTree.FromPolygons(verts, polys)

parts = {n: world_mesh(n) for n in NAMES}
allv = [v for p in parts.values() for v in p[0]]
lo = mathutils.Vector([min(v[i] for v in allv) for i in range(3)])
hi = mathutils.Vector([max(v[i] for v in allv) for i in range(3)])
D = (hi - lo).length

def gap(a, b):
    va, _, ta = parts[a]
    vb, _, tb = parts[b]
    if ta.overlap(tb):
        return 0.0  # surfaces cross: touching
    d1 = min((tb.find_nearest(v)[3] for v in va), default=float("inf"))
    d2 = min((ta.find_nearest(v)[3] for v in vb), default=float("inf"))
    return min(d1, d2)

def coplanar_faces(a, b):
    va, pa, _ = parts[a]
    _, _, tb = parts[b]
    count = 0
    for poly in pa:
        pts = [va[i] for i in poly]
        centre = sum(pts, mathutils.Vector()) / len(pts)
        loc, other_normal, _, _ = tb.find_nearest(centre, 0.0001 * D)
        if loc is not None and abs(mathutils.geometry.normal(pts).dot(other_normal)) > 0.999:
            count += 1
    return count

report = {}
for a in NAMES:
    others = [b for b in NAMES if b != a]
    g = min((gap(a, b) for b in others), default=0.0)
    if g <= 0.002 * D:
        state = "touching"
    elif g > 0.01 * D:
        state = "floating"
    else:
        state = "near miss"
    z = {b: coplanar_faces(a, b) for b in others}
    report[a] = {"gap_pct_of_D": round(100 * g / D, 3), "state": state,
                 "zfight_faces": {b: n for b, n in z.items() if n}}
result = {"D_m": round(D, 4), "parts": report}
```

Pass: every part "touching" (or listed as floating on purpose), and no `zfight_faces`.

## 2. UV gate: unsolved faces, coverage, texel density

Run after `blender_check { what: "mesh" }` shows UV overlap 0 (overlap would count twice in the coverage).

```python
NAME, TEX = "CLEAN_COPY", 2048
ob = bpy.data.objects[NAME]
bm = bmesh.new()
bm.from_mesh(ob.data)
bm.transform(ob.matrix_world)
uv = bm.loops.layers.uv.active
area3d = uv_total = 0.0
zero = 0
dens = []
for f in bm.faces:
    p = [l[uv].uv for l in f.loops]
    a_uv = 0.5 * abs(sum(p[i - 1].x * p[i].y - p[i].x * p[i - 1].y for i in range(len(p))))
    a3 = f.calc_area()
    area3d += a3
    uv_total += a_uv
    if a_uv < 1e-9:
        zero += 1
    elif a3 > 1e-12:
        dens.append(TEX * math.sqrt(a_uv / a3))  # pixels per metre
bm.free()
dens.sort()

def pct(q):
    return dens[int(q * (len(dens) - 1))] if dens else 0.0

result = {
    "zero_area_uv_faces": zero,
    "coverage": round(uv_total, 3),
    "px_per_m": {"p10": round(pct(0.1)), "median": round(pct(0.5)), "p90": round(pct(0.9))},
    "spread_p90_over_p10": round(pct(0.9) / max(pct(0.1), 1e-9), 2),
    "side_needed_at_512_px_per_m": round(512 * math.sqrt(area3d / max(uv_total, 1e-9))),
}
```

Pass: `zero_area_uv_faces` 0; coverage 0.70 or more on props (0.55 or more on creatures); spread near 1.2 (a starting value: per-face numbers include stretch, so look at which islands are off before repacking).

## 3. Measure the cage before baking

```python
LOW, HIGH = "CLEAN_COPY", "SOURCE"
dg = bpy.context.evaluated_depsgraph_get()
src = bpy.data.objects[HIGH]
ev = src.evaluated_get(dg)
me = ev.to_mesh()
hv = [src.matrix_world @ v.co for v in me.vertices]
tree = mathutils.bvhtree.BVHTree.FromPolygons(hv, [tuple(p.vertices) for p in me.polygons])
ev.to_mesh_clear()
D = (mathutils.Vector([max(v[i] for v in hv) for i in range(3)])
     - mathutils.Vector([min(v[i] for v in hv) for i in range(3)])).length

low = bpy.data.objects[LOW]
mw = low.matrix_world
nm = mw.to_3x3().inverted_safe().transposed()
limit = 0.05 * D
outside, inside, missed = [], [], 0
verts = low.data.vertices
step = max(1, len(verts) // 20000)
for i in range(0, len(verts), step):
    v = verts[i]
    co = mw @ v.co
    n = (nm @ v.normal).normalized()
    hit_out = tree.ray_cast(co, n, limit)[0]
    hit_in = tree.ray_cast(co, -n, limit)[0]
    if hit_out is not None:
        outside.append((hit_out - co).length)
    if hit_in is not None:
        inside.append((hit_in - co).length)
    if hit_out is None and hit_in is None:
        missed += 1

def p99(xs):
    xs = sorted(xs)
    return xs[int(0.99 * (len(xs) - 1))] if xs else 0.0

ext = 1.2 * p99(outside)
result = {
    "D_m": round(D, 4),
    "outside_p99_pct_of_D": round(100 * p99(outside) / D, 3),
    "inside_p99_pct_of_D": round(100 * p99(inside) / D, 3),
    "missed_pct": round(100 * missed / max(1, len(range(0, len(verts), step))), 2),
    "suggested_cage_extrusion_m": round(ext, 5),
    "suggested_max_ray_distance_m": round(ext + 1.2 * p99(inside), 5),
}
```

Read it: `outside_p99_pct_of_D` over 2 means the usual cage is too small there; `missed_pct` over about 1 means parts of the copy are far from the source (wrong part, big simplification). `blender_texture { op: "bake" }` picks its own distances, so when the numbers are off, fix the copy (more triangles where it cuts inside) and measure again, or tell the creator.

## 4. Pixel checks on a baked map

Works on any baked image. Images over 512 px are checked on a scaled copy, which this script removes again (a full 2K pixel copy is too big for plain Python).

```python
IMAGE, LOW, KIND = "BAKED_IMAGE", "CLEAN_COPY", "normal"  # KIND: "normal" or "ao"
src = bpy.data.images[IMAGE]
img = src
if max(src.size) > 512:
    img = src.copy()
    img.scale(512, 512)
w, h = img.size
px = img.pixels[:]  # flat RGBA, row 0 is the bottom (V = 0)

me = bpy.data.objects[LOW].data
uvl = me.uv_layers.active.data
me.calc_loop_triangles()
tris = [[uvl[i].uv.copy() for i in t.loops] for t in me.loop_triangles]

def area(a, b, c):
    return 0.5 * abs((b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y))

areas = [area(*t) for t in tris]
total = sum(areas) or 1.0
rnd = random.Random(1)
vals = []
for (a, b, c), ar in zip(tris, areas):
    for _ in range(max(1, round(ar / total * 100000))):
        r1, r2 = rnd.random(), rnd.random()
        if r1 + r2 > 1:
            r1, r2 = 1 - r1, 1 - r2
        p = a + (b - a) * r1 + (c - a) * r2
        x = min(w - 1, int((p.x % 1.0) * w))
        y = min(h - 1, int((p.y % 1.0) * h))
        k = 4 * (y * w + x)
        vals.append(px[k:k + 3])
if img is not src:
    bpy.data.images.remove(img)

n = len(vals)
if KIND == "normal":
    result = {
        "blue_inverted_pct": round(100 * sum(1 for r, g, b in vals if b < 0.5) / n, 2),
        "exactly_flat_pct": round(100 * sum(1 for r, g, b in vals
                                  if abs(r - 0.5) < 0.004 and abs(g - 0.5) < 0.004 and b > 0.996) / n, 2),
        "bad_length_pct": round(100 * sum(1 for r, g, b in vals
                                if abs(math.sqrt((2*r-1)**2 + (2*g-1)**2 + (2*b-1)**2) - 1) > 0.15) / n, 2),
    }
else:
    result = {
        "black_pct": round(100 * sum(1 for v in vals if v[0] < 0.05) / n, 2),
        "white_pct": round(100 * sum(1 for v in vals if v[0] > 0.95) / n, 2),
        "mean": round(sum(v[0] for v in vals) / n, 3),
    }
```

Thresholds are in the SKILL.md table. Scaling averages neighbouring pixels, so `bad_length_pct` can read a little high on a scaled copy; check a failure on the 512 test bake itself.

## 5. Re-import check after export (full level)

Imports the exported file, reports, then removes exactly the datablocks the import added. `blender_check { what: "roundtrip" }` covers the usual numbers; use this for bones, custom properties and per-material links.

```python
PATH = r"FULL_PATH_THAT_BLENDER_EXPORT_REPORTED.fbx"
kinds = ("objects", "meshes", "materials", "images", "armatures", "actions")
before = {k: set(getattr(bpy.data, k)) for k in kinds}
try:
    bpy.ops.import_scene.fbx(filepath=PATH)
except (AttributeError, RuntimeError):
    bpy.ops.wm.fbx_import(filepath=PATH)  # the newer built-in importer
new = {k: set(getattr(bpy.data, k)) - before[k] for k in kinds}

report = {}
for ob in new["objects"]:
    if ob.type != "MESH":
        report[ob.name] = {"type": ob.type, "scale": [round(s, 4) for s in ob.scale]}
        continue
    me = ob.data
    mats = {}
    for m in me.materials:
        if not (m and m.node_tree):
            continue
        bsdf = next((nd for nd in m.node_tree.nodes if nd.type == "BSDF_PRINCIPLED"), None)
        mats[m.name] = {
            "images": sorted(nd.image.name for nd in m.node_tree.nodes if nd.type == "TEX_IMAGE" and nd.image),
            "metal_linked": bool(bsdf and bsdf.inputs["Metallic"].is_linked),
            "rough_linked": bool(bsdf and bsdf.inputs["Roughness"].is_linked),
            "normal_linked": bool(bsdf and bsdf.inputs["Normal"].is_linked),
        }
    report[ob.name] = {
        "size": [round(d, 4) for d in ob.dimensions],
        "scale": [round(s, 4) for s in ob.scale],
        "tris": sum(len(p.vertices) - 2 for p in me.polygons),
        "uv_maps": len(me.uv_layers),
        "materials": mats,
    }

for k in kinds:  # objects first, then their data
    coll = getattr(bpy.data, k)
    for item in new[k]:
        try:
            coll.remove(item)
        except ReferenceError:
            pass
result = report
```

Compare with the scene and with what `blender_export` reported: same size (within 1 mm, or the reported studs), same triangle count, scale 1, one mesh, one material, one UV map. `metal_linked` and `rough_linked` false is the GLB to FBX loss; for a Roblox export the four SurfaceAppearance maps may be written as separate image files instead, so then check the export folder for separate greyscale roughness and metal images.

<!-- SPDX-FileCopyrightText: 2026 NightyCode -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
