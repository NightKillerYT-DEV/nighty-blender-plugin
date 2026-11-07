# The nighty library
Every function of `import nighty as n` (inside run_python), with its arguments and an example.

Meters, Z up, front is -Y, right is +X. Shapes are centered on `at`, keep scale 1 and get enough sides for their
size (`n.settings(detail, size)` sets how fine). Most functions take objects or their names, alone or in a list.
`n.help()` lists everything inside Blender; `n.help("cylinder")` shows one.


## Settings, sides, objects, bounds

### n.settings(detail=None, size=None, collection=None)
Global defaults for everything made after it. Returns the current settings.

detail: "low" | "medium" | "high" (how many sides round shapes get, bevel segments).
size: the asset's overall size in meters (a pistol 0.25, a rifle 0.9, a crate 0.6, a door 2.1).
collection: name of the collection new objects go into (default: the active one).

    n.settings(detail="high", size=0.9, collection="Rifle")

### n.segments(radius, detail=None, size=None, arc=360.0)
Sides for a circle (or an arc, degrees) of this radius: enough for how big it shows, a multiple of 4.

n.segments(0.0095)           # a rifle barrel (asset size 0.9 m) at medium detail -> 20
n.segments(0.3, "low")       # a big barrel (size 1 m) at low detail -> 32

### n.bevel_segments(detail=None)
Bevel segments of a detail level (even, so corners stay quads): low 2, medium 4, high 6.

### n.get(name)
An object by name (or the object itself). Raises a clear error when it doesn't exist.

### n.objects(kind='MESH', collection=None, visible=True)
Objects in the scene (or a collection) of a type ("MESH", "ALL"), skipping Nighty's helpers.

### n.collection(name, parent=None)
A collection by name, made and linked under the scene (or parent) when missing.

coll = n.collection("Rifle")

### n.bounds(objs, evaluated=True)
World bounds of objects (with modifiers by default), from their vertices.

b = n.bounds(body); print(b.size, b.top)

### n.Bounds
A world-space box: .min .max .size .center (Vectors), .top .bottom (z), .corners().

### n.to_list(objs)
One object, a name, or a list of them -> a list of objects.

### n.update()
Updates matrices and modifiers (after moving things, before measuring).


## Shapes

### n.box(size=1.0, at=(0, 0, 0), rot=None, bevel=None, name='Box', material=None, collection=None, parent=None)
A box of size (x, y, z) meters (or one number), centered on at. bevel: a width in meters adds n.bevel().

lid = n.box((0.6, 0.4, 0.04), at=(0, 0, 0.42), bevel=0.004, name="Lid")

### n.rounded_box(size=1.0, radius=None, segments=None, at=(0, 0, 0), rot=None, name='RoundedBox', material=None, collection=None, parent=None)
A box with truly rounded edges and corners (real geometry, all quads), plus weighted normals.

radius: edge radius in meters (default 12% of the smallest side). segments: even numbers keep corners quads.

    cushion = n.rounded_box((0.45, 0.45, 0.08), radius=0.03, name="Cushion")

### n.cylinder(radius=0.5, depth=1.0, segments=None, axis='Z', caps='ngon', at=(0, 0, 0), rot=None, bevel=None, name='Cylinder', material=None, collection=None, parent=None)
A cylinder with enough sides for its size. caps: "ngon" (flat), "quad" (grid of quads), "fan", "none".

barrel = n.cylinder(0.011, 0.42, axis="X", name="Barrel", bevel=0.001)

### n.tube(radius=0.5, depth=1.0, thickness=None, inner=None, segments=None, axis='Z', at=(0, 0, 0), rot=None, bevel=None, name='Tube', material=None, collection=None, parent=None)
A hollow pipe (outer wall, inner wall, ring ends; all quads). thickness or inner radius.

sleeve = n.tube(0.02, 0.1, thickness=0.004, axis="X", name="Sleeve")

### n.cone(radius=0.5, depth=1.0, top=0.0, segments=None, axis='Z', caps='ngon', at=(0, 0, 0), rot=None, bevel=None, name='Cone', material=None, collection=None, parent=None)
A cone (top=0, a pointed tip) or a truncated cone (top = top radius). caps as cylinder.

tip = n.cone(0.02, 0.05, top=0.008, axis="X", name="MuzzleTip")

### n.sphere(radius=0.5, segments=None, kind='quad', at=(0, 0, 0), rot=None, name='Sphere', material=None, collection=None, parent=None)
A sphere. kind "quad": all quads, no poles (best for subdivision and deforming); "uv": rings with poles.

segments: sides around the middle (default from size).

    knob = n.sphere(0.015, name="Knob")

### n.dome(radius=0.5, height=None, segments=None, axis='Z', caps='ngon', at=(0, 0, 0), rot=None, name='Dome', material=None, collection=None, parent=None)
Half a quad sphere standing on its flat side (origin at the base center); height squashes it.

rivet = n.dome(0.004, height=0.002, name="Rivet")

### n.capsule(radius=0.25, depth=1.0, segments=None, axis='Z', at=(0, 0, 0), rot=None, name='Capsule', material=None, collection=None, parent=None)
A pill: total length depth (>= 2 radius), all quads, no poles. The straight middle gets square quads at
high detail only (they matter for deforming, not for the shape): light at low and medium.

    grip = n.capsule(0.016, 0.12, axis="Z", name="Grip")

### n.torus(radius=0.5, thickness=0.1, segments=None, ring_segments=None, axis='Z', arc=360.0, at=(0, 0, 0), rot=None, name='Torus', material=None, collection=None, parent=None)
A ring (donut): radius to the tube's center, thickness = tube radius. arc < 360 makes an open bend with flat ends.

hoop = n.torus(0.29, 0.006, name="Hoop")

### n.plane(size=1.0, at=(0, 0, 0), rot=None, cuts=0, axis='Z', name='Plane', material=None, collection=None, parent=None)
A flat grid of quads (open: for decals, leaves, cards). size (x, y) or one number; cuts per side.

sign = n.plane((0.4, 0.25), axis="-Y", name="Sign")

### n.lathe(profile, segments=None, axis='Z', caps='ngon', at=(0, 0, 0), rot=None, name='Lathe', material=None, collection=None, parent=None)
Spins a side profile around the axis: profile = [(radius, height), ...] from bottom to top.

A point with radius 0 closes that end in a point; open ends get caps ("ngon", "quad", "fan" or "none").
A profile that ends where it starts makes a closed ring (a hollow wall: up the outside, down the inside).
Use n.spline() for smooth curves; corners sharper than 30 degrees stay sharp.

    body = n.lathe(n.spline([(0, 0), (0.06, 0.005), (0.07, 0.08), (0.03, 0.15), (0.02, 0.2)]), name="Vase")

### n.pipe(points, radius=0.02, segments=None, bend=None, caps='ngon', closed=False, at=(0, 0, 0), rot=None, name='Pipe', material=None, collection=None, parent=None)
A round tube along a 3D path (points relative to at). bend: corner radius (default 2 x radius).

Quads all along, even width through bends. closed=True joins the ends into a loop.

    handle = n.pipe([(-0.1, 0, 0), (-0.1, 0, 0.06), (0.1, 0, 0.06), (0.1, 0, 0)], radius=0.008, name="Handle")

### n.extrude(outline, depth=0.1, plane='XZ', holes=None, at=(0, 0, 0), rot=None, bevel=None, name='Extrude', material=None, collection=None, parent=None)
A flat 2D outline made solid: outline [(u, v) or (u, v, corner_radius)], depth along the plane's normal.

plane: "XZ" (u = x, v = z, thickness along Y: side profiles), "XY" (top shapes, thickness along Z),
"YZ" (u = y, v = z, thickness along X). holes: more outlines cut through. Flat caps, quad sides.

    blade = n.extrude([(0, 0), (0.04, 0), (0.035, 0.7), (0.0, 0.78), (-0.035, 0.7), (-0.04, 0)],
                      depth=0.006, plane="XZ", bevel=0.002, name="Blade")

### n.extrude_image(path, depth=0.02, width=None, height=None, plane='XZ', threshold=0.5, simplify=0.004, smooth=0, invert=False, keep='all', at=(0, 0, 0), rot=None, bevel=None, name='Silhouette', material=None, collection=None, parent=None)
A solid from a picture's silhouette (holes included): outline_from_image + extrude, joined in one object.

keep: "all" or "largest". Good for blades, keys, signs, logos and side profiles to model against.

    key = n.extrude_image("C:/refs/key.png", depth=0.004, width=0.07, plane="XY", bevel=0.0006, name="Key")

### n.outline_from_image(path, width=None, height=None, threshold=0.5, simplify=0.004, smooth=0, invert=False, max_res=400, min_area=0.002)
Outlines of the shape in a picture (transparent background, or a plain one), in meters, centered.

Returns [{"outline": [(u, v), ...], "holes": [[...], ...]}, ...] biggest first. width / height: the shape's
size in meters (default width 1). simplify: allowed error as a fraction of the picture; smooth: rounding passes.

    shapes = n.outline_from_image("C:/refs/sword.png", height=0.9)

### n.outline_from_curve(curve, samples=None)
2D outlines (x, y in the curve's own space) of a curve object's closed splines, for extrude / lathe.

loops = n.outline_from_curve("ProfileCurve"); n.extrude(loops[0], depth=0.03)

### n.spline(points, samples=None, closed=False)
A smooth curve through 2D or 3D points (Catmull-Rom). samples: points per span (default from detail).

profile = n.spline([(0.0, 0), (0.05, 0.01), (0.045, 0.12), (0.015, 0.16)])   # for n.lathe

### n.fillet(points, radius=None, closed=True, count=None)
Rounds corners of a 2D outline. Points (x, y) or (x, y, r): r is that corner's radius (0 = sharp).

outline = n.fillet([(0, 0, 0), (0.3, 0, 0.02), (0.3, 0.1, 0.02), (0, 0.1, 0)])

### n.rounded_rect(width, height, radius=None, center=(0.0, 0.0))
A rounded rectangle outline in 2D (for extrude / panel shapes).

### n.circle_points(radius, count=None, center=(0.0, 0.0), start=0.0, arc=360.0)
Points of a circle or arc in 2D: [(x, y), ...]. count defaults to the detail level.


## Finishing and editing

### n.bevel(obj, width=None, segments=None, angle=30.0, profile=0.5, harden=True, weighted=True, limit='auto', clamp=True, safe=True)
Rounded edges the hard-surface way: Bevel (angle limit, harden normals) + Weighted Normal, smooth shading.

width: meters (default from the part's size). segments: default from the detail level (even = quad corners);
a bevel too narrow to show (under 1/1000 of n.settings size) gets 1, under 2.5/1000 at most 2 (game triangles
go where they read).
limit: "angle" (edges sharper than angle), "weight" (edges marked with n.mark_bevel), "auto" (weight when the
part had fine cuts like knurling made after marking, else angle).
safe: when the bevel would make faces overlap (wider than a groove or a small rounded corner), the width is
lowered until it doesn't (the modifier's width tells what was used). Calling it again updates the same bevel;
booleans and mirrors added later still go before it.

    n.bevel(receiver, width=0.0015)

### n.mark_bevel(obj, angle=30.0, weight=1.0, clear=True)
Gives the edges sharper than angle a bevel weight, so n.bevel(obj, limit="weight") bevels only them.
Mark the big edges first, cut small details after: the details stay crisp. Returns how many were marked.

    n.mark_bevel(blade); n.boolean_cut(blade, fuller); n.bevel(blade, width=0.002, limit="weight")

### n.weighted_normals(obj, weight=50, keep_sharp=True)
Weighted Normal modifier (last in the stack): flat faces shade flat, bevels shade round.

### n.smooth_by_angle(obj, angle=30.0)
Smooth shading with edges sharper than angle (degrees) kept sharp (Blender 4.1+ replacement of auto smooth).

### n.shade_flat(obj)
Flat shading (faceted look for stylized low poly).

### n.mirror(obj, axis='X', bisect=False, merge=True, clip=True, about=None, apply=False)
Mirror across the object's own axis (or another object's): model one half, get both.

n.mirror(half_body, "X", bisect=True)

### n.array(obj, count, offset=(0.1, 0, 0), merge=False, apply=False)
Copies in a row: offset is the step in meters (x, y, z). merge welds touching copies.

n.array(slat, 6, offset=(0, 0.08, 0))

### n.radial(obj, count, axis='Z', center=None, angle=360.0, weld=False)
Copies around an axis, joined into the same mesh (bolts on a flange, gear teeth, barrel staves).

center: world point the axis goes through (default the world origin). The object's mesh is changed.

    n.radial(bolt, 8, axis="Y", center=flange.location)

### n.subdivide(obj, levels=2, render_levels=None)
Subdivision Surface (Catmull-Clark). Use with quads and bevels as support loops.

### n.solidify(obj, thickness=0.01, offset=-1.0, apply=False)
Gives a surface thickness (meters). offset -1 grows inward, 1 outward.

### n.displace(obj, strength=0.05, scale=1.0, octaves=4, seed=0, roughness=0.5)
Bumps the surface along its normals with fractal noise (rocks, ground, bark). Changes the mesh.

strength: meters at most; scale: size of the bumps in meters.

    n.displace(rock, strength=0.06, scale=0.35, seed=3)

### n.deform(obj, kind='taper', amount=0.3, axis='Z', apply=False)
Simple Deform: kind "taper" | "bend" | "twist" | "stretch". amount: factor, or degrees for bend / twist.

### n.boolean_cut(target, cutter, op='difference', solver='auto', apply=True, keep_cutter=False, cleanup_after=True)
Boolean with cleanup. op "difference" (cut), "union", "intersect". solver "auto" | "exact" | "fast" | "manifold".

apply=True bakes it (the cutter is deleted unless keep_cutter); apply=False keeps a live modifier and turns the
cutter into a hidden wire helper. Check the result with n.is_manifold().

    slot = n.box((0.05, 0.1, 0.01), at=(0.1, 0, 0.04))
    n.boolean_cut(receiver, slot)

### n.boolean_union(target, other, solver='auto', apply=True)
Fuses other into target (one watertight shell).

### n.boolean_intersect(target, other, solver='auto', apply=True)
Keeps only where target and other overlap.

### n.hole(target, radius, at=None, axis='Z', depth=None, segments=None, apply=True)
Drills a round hole through (or depth meters into) target, along axis, centered at the world point at.

n.hole(plate, 0.004, at=(0.05, 0, 0.1), axis="Y")

### n.panel_cut(target, side='-Y', center=None, size=(0.1, 0.1), groove=None, depth=None, radius=None, shape='rect', apply=True)
Cuts a panel line (a thin groove around a rectangle or circle) into a flat side of target.

side: "+X" ... "-Z" (the face of the bounds it goes on). center: (u, v) world position on that face
(-Y / +Y: (x, z); -X / +X: (y, z); -Z / +Z: (x, y)); default the face's middle. size: (width, height) or a
diameter for shape="circle". groove / depth: meters (default from the asset size).

    n.panel_cut(hull, "-Y", center=(0.05, 0.12), size=(0.12, 0.06), radius=0.008)

### n.vents(target, side='-Y', center=None, count=5, slot=(0.06, 0.008), gap=None, depth=None, direction='v', apply=True)
Cuts a row of rounded slots into a flat side (vents, serrations, M-LOK slots).

slot: (size along u, size along v) of one slot in meters (u / v as in panel_cut: -Y / +Y face: u = x, v = z).
direction: "v" stacks the slots along v, "u" lines them up along u. gap: space between slots.

    n.vents(cover, "+Z", center=(0, 0.02), count=6, slot=(0.08, 0.008))            # stacked vent slots
    n.vents(slide, "-Y", center=(-0.08, 0.026), count=6, slot=(0.004, 0.03), direction="u")   # serrations

### n.apply_modifiers(obj, upto=None)
Bakes modifiers into the mesh: all of them, or those up to and including the one named upto.

### n.cleanup(obj, merge=None, loose=True, normals=True)
Welds doubles, removes degenerate faces and loose bits, fixes normals. Returns what changed.

n.cleanup(part)   # after imports or hand edits

### n.is_manifold(obj, evaluated=True)
True when every edge has exactly two faces (a closed, watertight surface).


## Placing parts

### n.align(obj, target, *relations, gap=0.0, offset=(0, 0, 0))
Places obj against target. Axes no relation names are centered on target (use "keep_x" etc. to keep).

relations: "on_top", "below", "front", "back", "left", "right" (outside, touching; gap in meters),
"flush_top", "flush_bottom", "flush_front", "flush_back", "flush_left", "flush_right" (edges lined up),
"center" (all axes), "center_x" / "center_y" / "center_z", "keep_x" / "keep_y" / "keep_z".
obj and target may be lists (moved / measured together).

    n.align(scope, receiver, "on_top", "flush_back", gap=0.002)
    n.align(lid, body, "on_top")

### n.snap(obj, onto, direction='-Z', gap=0.0, max_distance=10.0)
Moves obj along direction until it touches onto's surface (ray cast from obj's facing points).

n.snap(bolt, hull, "-Y")       # push a bolt onto a curved side

### n.place_on(obj, target, direction='-Z', up='Z', offset=0.0, max_distance=10.0)
Moves obj's origin onto target's surface (a ray from obj along direction) and turns obj so its up axis
follows the surface there. For spots on a mushroom cap, bolts on a curved hull, decals.

    spot = n.dome(0.01, height=0.003, at=(0.03, 0.02, 0.5)); n.place_on(spot, cap, "-Z")

### n.stack(objs, axis='Z', gap=0.0, align_to='center')
Puts objects one after another along axis (the first stays), centered on the first across the other axes.

n.stack([base, column, cap], "Z")

### n.distribute(objs, axis='X', spacing=None, start=None)
Spaces objects evenly along axis: spacing = gap between them (meters), or between the first and last.

### n.ground(objs, z=0.0)
Puts objects (together) on the ground: their lowest point at z (default 0).

### n.center(objs, axes='XY', at=(0, 0, 0))
Centers objects (together) on at along the given axes.

### n.move(objs, delta)
Moves objects (top-level ones; children follow) by delta (x, y, z) meters.

### n.rotate(objs, degrees, axis='Z', pivot=None)
Turns objects together around an axis ("X", "Y", "Z" or (x, y, z)) through pivot (default: their middle).

n.rotate([blade, guard, grip], 25, "Z")

### n.apply_transforms(objs, location=False, rotation=True, scale=True)
Bakes rotation / scale (and location) into the mesh, like Ctrl+A, without operators. Children keep place.

### n.scale_to(objs, size, axis='max', ground_it=False)
Scales objects (together, around their center) so their size along axis ("x", "y", "z", "max") is size m,
then applies the scale. For imported or generated models.

    n.scale_to(gen_mesh, 1.8, "z", ground_it=True)    # 1.8 m tall

### n.set_origin(obj, where='bottom')
Moves the object's origin without moving its mesh: "bottom" (center of the base), "center", "top", or (x, y, z).

n.set_origin(lamp, "bottom")


## Parts and merging

### n.part(obj, name=None, collection=None, role=None)
Names a part and moves it into a collection (made when missing). role: a tag kept on the object.

n.part(barrel, "Barrel", collection="Rifle")

### n.parent(child, parent_obj, keep_transform=True)
Parents child (or a list) to parent_obj, keeping where they are.

### n.duplicate(obj, at=None, rot=None, linked=False, name=None, mirror_x=False)
A copy of an object (its own mesh unless linked), optionally moved / turned (degrees) / mirrored across X=0.

right_leg = n.duplicate(left_leg, at=(0.25, 0.2, 0.2))

### n.delete(objs)
Deletes objects and their meshes when nothing else uses them.

### n.merge_parts(objs, name=None, weld=True, distance=1e-05, keep=False)
Joins parts into one mesh object (modifiers applied, materials kept), optionally welding touching vertices.

The first object becomes the merged one (its origin stays). keep=True leaves the originals.
Parts that only overlap stay separate shells; use n.boolean_union for one watertight piece.

    gun = n.merge_parts([receiver, barrel, grip, stock], name="Rifle")

### n.group(objs, collection)
Puts objects into one collection (made when missing). Returns the collection.


## Ready-made details

### n.bolt(radius=0.005, height=None, kind='hex', axis='Z', at=(0, 0, 0), washer=False, segments=None, name='Bolt', material=None, collection=None, parent=None)
A bolt head standing on at, pointing along axis. kind: "hex" (six sides, chamfered), "round" (dome),
"socket" (round with a hex recess). washer adds a thin ring under it.

    n.bolt(0.004, kind="hex", axis="-Y", at=(0.1, -0.2, 0.3))

### n.rivets(points, radius=0.003, axis='Z', height=None, segments=None, name='Rivets', material=None, collection=None, parent=None)
Round rivets (domes) at several surface points, as one object.

n.rivets([(x, -0.2, 0.05) for x in (-0.2, 0, 0.2)], radius=0.004, axis="-Y")

### n.rail(length=0.2, width=0.021, height=0.0094, slot=0.0052, pitch=0.01, axis='X', at=(0, 0, 0), name='Rail', material=None, collection=None, parent=None)
An accessory rail (dovetail profile with cross slots), lying along axis ("X" or "Y") on top of at.

n.rail(0.18, at=(0.05, 0, 0.065))

### n.handle(width=0.12, height=0.04, radius=0.006, axis='Z', at=(0, 0, 0), along=None, name='Handle', material=None, collection=None, parent=None)
A U-shaped bar handle: feet on the surface at at, arching height out along axis, width along along
(default: X, or Y when axis is X). For crates, chests, doors, drawers.

    n.handle(0.14, 0.035, 0.007, axis="-Y", at=(0, -0.3, 0.25))

### n.text3d(body, size=0.05, depth=0.005, axis='-Y', at=(0, 0, 0), bevel=None, resolution=None, font=None, align='CENTER', name='Text', material=None, collection=None, parent=None)
Raised 3D letters as a mesh, facing along axis (-Y = readable from the front). Decals are better for
printed text; use this for embossed or cut letters. bevel: meters (0 = none); resolution: curve steps per
letter segment (default from the detail level; fewer = lighter).

    n.text3d("NIGHTY", size=0.04, depth=0.004, axis="-Y", at=(0, -0.201, 0.3))


## Detail kit (secondary and tertiary detail)

### n.bolts_along(start, end, count, radius=0.004, kind='hex', axis='Z', washer=False, segments=None, name='Bolts', material=None, parent=None)
count bolt heads evenly from start to end (both included), standing on the surface and facing axis.

n.bolts_along((-0.25, -0.2, 0.05), (0.25, -0.2, 0.05), 6, radius=0.005, axis="-Y")

### n.bolts_around(center, ring_radius, count, radius=0.004, kind='hex', axis='Z', start_angle=0.0, washer=False, segments=None, name='Bolts', material=None, parent=None)
count bolt heads on a circle (a flange, a hub) around center, in the plane facing axis.

n.bolts_around((0, 0, 0.3), 0.09, 8, radius=0.006, axis="Z")

### n.nails(points, radius=0.0035, axis='Z', segments=None, name='Nails', material=None, parent=None)
Flat round nail heads at surface points, facing axis (one object). Small heads (under 1 % of n.settings
size) get 8 sides, about 30 triangles each: nobody counts a nail's sides in a game.

    n.nails([(x, -0.3, 0.1) for x in (-0.2, 0, 0.2)], axis="-Y")

### n.groove(target, points, width=0.002, closed=False, apply=True)
A panel seam: a half-round groove along a path of points on target's surface (width meters).

n.groove(body, [(-0.1, -0.02, 0.0), (0.1, -0.02, 0.0)], width=0.0015)

### n.grille(target, side='-Y', center=None, size=(0.1, 0.06), count=6, bar=None, depth=None, radius=None, name='Grille', material=None)
A recessed opening with bars across it (vents, speaker grilles, intakes). Cuts target; returns the bars.

side / center / size as n.panel_cut: (u, v) on that face (-Y / +Y: u = x, v = z). Bars run along u.

    bars = n.grille(body, "-Y", center=(0.05, 0.1), size=(0.12, 0.05), count=5)

### n.knurl(target, side='-Y', center=None, size=(0.04, 0.08), pitch=0.004, depth=0.0008, pattern='diamond', apply=True)
A grip texture cut into a flat side: pattern "diamond" (crossed grooves) or "lines". The part's edges are
marked first, so a later n.bevel rounds them and leaves the knurling crisp.

    n.knurl(grip, "-Y", center=(-0.09, -0.07), size=(0.035, 0.07), pitch=0.0035)

### n.cable(points, radius=0.006, sag=0.0, clips=0, clip_radius=None, segments=None, name='Cable', material=None, clip_material=None)
A cable / hose through points, hanging down by sag (a share of each span), with clips around it.

Returns the cable (and makes "<name>Clips" when clips > 0).

    n.cable([(0, 0, 0.3), (0.3, 0, 0.32), (0.5, 0.1, 0.1)], radius=0.005, sag=0.12, clips=3)

### n.planks(size=(0.6, 0.5), count=5, thickness=0.02, gap=0.005, plane='XZ', at=(0, 0, 0), bevel=None, jitter=0.0015, split=0, seed=0, name='Planks', material=None)
Boards side by side with gaps (along u, stacked along v of the plane, thickness along its normal), each a
little different; split > 0 cuts some rows into two boards with a seam. One object, one island per board.

    front = n.planks((0.56, 0.56), count=4, thickness=0.018, plane="XZ", at=(0, -0.29, 0.3), split=1)

### n.corner_bracket(target, corner=(1, -1, 1), size=0.08, thickness=0.004, nails_per_face=1, nail_radius=None, name='Bracket', material=None, nail_material=None)
A metal corner piece wrapping one corner of target's bounds (three faces), nailed on each face.

corner: (+-1, +-1, +-1) which corner. Returns the bracket (nails become "<name>Nails").

    n.corner_bracket(crate, (1, -1, 1), size=0.09, material=iron)

### n.inset(obj, side='+Z', amount=0.01, depth=-0.003, min_dot=0.995)
Insets the faces facing side (a border of amount meters) and pushes the inner part out (depth > 0) or in
(depth < 0): raised or sunk panels on boxes, lids, plates. Changes the mesh.

    n.inset(lid, "+Z", amount=0.015, depth=-0.004)

### n.stitches(points, length=0.006, gap=0.004, radius=0.0011, name='Stitches', material=None, parent=None)
Thread stitches along a path on a surface (leather wraps, pouches, seats): little capsules, half sunk.

n.stitches([(-0.04, -0.016, -0.03), (-0.06, -0.016, -0.11)], length=0.005)

### n.plate(size=(0.08, 0.04), thickness=0.003, text=None, rim=None, axis='-Y', at=(0, 0, 0), name='Plate', material=None, text_material=None)
An emblem / name plate: a rounded plate with a raised rim and optional raised text, facing axis.

n.plate((0.09, 0.035), text="NIGHTY", axis="-Y", at=(0, -0.301, 0.4))

### n.chamfer(obj, width=None)
A flat 45-degree chamfer on the sharp edges (one segment, weighted normals): hard industrial edges.

### n.subd_crisp(obj, width=None, levels=2)
Smooth subdivision with tight support loops on the sharp edges: soft shapes with crisp highlights.

### n.chunky(obj, amount=1.0, segments=4)
Stylized chunky edges: a big, soft bevel (about 7 % of the part's smallest side x amount). segments 2 for
small parts in a tight triangle budget.

### n.taper(obj, amount=0.3, axis='Z')
Narrows the part toward the +axis end (amount 0..1; negative widens). Stylized shapes, legs, handles.

### n.outline(obj, thickness=None, color=(0.02, 0.02, 0.03))
A cartoon outline: an inverted shell (its own object tagged "outline", parented to obj, a snapshot of the
current shape). Renders in Cycles and EEVEE; verify_mesh skips it, look draws it with its object.

    n.outline(chest, 0.004)


## Surfaces (procedural materials)

### n.surface(name, kind='steel', color=None, style='realistic', wear=0.35, dirt=0.25, roughness=None, grain=None, glow=None, size=None)
A material named name (made or rebuilt in place) of a library kind, shared by every part you paint with it.

color: the paint / plastic / anodizing / glow color, or a wood / leather / stone tone ('#rrggbb'); metals keep
their real color (stylized: tinted too). style: "realistic", "stylized" (game look) or "painted" (hand-painted).
wear 0.1 new .. 0.7 battered; dirt 0.1 clean .. 0.6 grimy (stylized keeps both low).
roughness: overrides the clean roughness. grain: "X" / "Y" / "Z", the direction wood grain and brushing run
(default X). glow: emission strength for "emissive" (default 8). size: the asset size in meters (default
n.settings size): wear width and dirt reach follow it.

    steel = n.surface("Bolts", "steel")
    neon = n.surface("Core", "emissive", color="#2fe0ff", glow=12)

### n.surfaces()
The material kinds: [(key, label, metal or not, takes a color)].


## Quick materials

### n.material(name, color=(0.8, 0.8, 0.8), metallic=0.0, roughness=0.5, emission=None, strength=1.0, alpha=1.0, transmission=0.0, coat=0.0, variation=0.0, scale=None)
A Principled material (made or updated by name). color: linear RGB(A) or "#hex".

emission: a color for glowing parts (strength in W/m2-ish units, 1-20). transmission 1 = glass.
variation 0..1: soft noise in color and roughness so surfaces don't look flat (scale: noise size, meters).

    steel = n.material("Steel", "#9aa3ad", metallic=1, roughness=0.35)
    glow = n.material("Glow", "#33ccff", emission="#33ccff", strength=8)

### n.paint(objs, mat, faces=None)
Gives objects a material (a material, its name, or a color). faces: indices that get it (others keep theirs).

n.paint([body, lid], wood)
n.paint(body, "#202020")

### n.hex_color(value)
"#ff8800" / "ff8800" -> linear RGBA (what node colors want).


## Checks and measurements

### n.verify(objs=None, allow_open=False, budget=None, symmetry='X', uv=True, allow_floating=(), evaluated=True)
The quality report of verify_mesh: topology, normals, loose and floating parts, UVs, scale.

objs: objects (default every visible mesh). allow_open: open surfaces are fine (planes, leaves).
budget: maximum triangles over all objects. Returns {"pass", "errors", "warnings", "objects", "floating"}.

    rep = n.verify([body, lid]); print(rep["pass"], rep["errors"])

### n.measure(objs)
Sizes in meters: {"name": {"size": [x, y, z], "min", "max", "center"}} plus "all" for the group.

n.measure([body, barrel])["all"]["size"]

### n.distance(a, b)
How far apart two objects are: closest surface distance (0 when touching / overlapping), center distance,
and the gap per axis between their bounds (negative = overlapping on that axis).

### n.compare(objs, reference)
How well objects match a reference / ghost object: size ratios, bounds overlap (IoU) and the average surface
distance both ways (as meters and as a share of the reference's size).


## Version shims (n.compat)

### n.compat.at_least(major, minor=0, patch=0)
True when this Blender is at least that version. at_least(5) -> 5.0 or newer.

### n.compat.enum_items(struct, prop)
The identifiers of a static enum, e.g. enum_items(bpy.types.BooleanModifier, "solver").

### n.compat.eevee_id()
The EEVEE engine id of this Blender: BLENDER_EEVEE_NEXT before 5.0, BLENDER_EEVEE from 5.0.

### n.compat.set_engine(scene, name)
Sets the render engine by a plain name ("eevee", "cycles", "workbench") or an id. Returns the id set.

### n.compat.boolean_solvers()
The boolean solvers this Blender has: 4.2: FAST, EXACT; 5.x: FLOAT, EXACT, MANIFOLD.

### n.compat.boolean_solver(name='exact')
A solver id for a plain name: "exact", "fast" / "float" (renamed in 5.0), "manifold" (5.x; else EXACT).

### n.compat.compositor_tree(scene, create=True)
The scene's compositor node tree (4.x: scene.node_tree with use_nodes; 5.x: compositing_node_group).

### n.compat.fcurves(target)
F-curves of an action, or of an object's / ID's current action (legacy and layered actions).

### n.compat.find_fcurve(target, data_path, index=0)
One F-curve by data path and index, or None.

### n.compat.keyframe(obj, data_path, frame, value=None, index=-1)
Sets (when value is given) and keys a property: keyframe(obj, "location", 10, (0, 0, 1)).

### n.compat.ensure_nodes(idblock)
Turns nodes on for a material / world / light where that is still a switch (always on in 5.x).

### n.compat.node(tree, node_type)
The first node of a type (types are not translated, names are): node(tree, "BSDF_PRINCIPLED").

### n.compat.principled(material)
The Principled BSDF of a material (nodes turned on first).

### n.compat.socket(node_, name)
An input socket by name, accepting old names (Emission -> Emission Color, Specular -> Specular IOR Level...).

### n.compat.set_input(node_, name, value)
Sets an input's default value if the socket exists (old names accepted). Returns True when set.

### n.compat.set_transparent(material, blended=True)
Transparency for EEVEE: surface_render_method (4.2+) or blend_method (older).

### n.compat.shade_smooth(mesh, angle=None)
Smooth shading; with an angle (degrees) edges sharper than it are marked sharp (4.1+ "smooth by angle").

### n.compat.shade_flat(mesh)
Flat shading.

### n.compat.sculpt_brush_type_attr()
The brush attribute naming the sculpt tool: sculpt_tool (4.x) or sculpt_brush_type (5.x).

### n.compat.set_view_transform(scene, name='Standard')
Sets the color view transform when it exists (Standard, AgX, Filmic...). Returns True when set.

### n.compat.studio_light(kind, prefer)
A studio light file name of a kind ("matcap", "world", "studio") that exists here, from a preference list.

### n.compat.studio_light_path(kind, name)
The full path of a studio light file (e.g. kind "world", name "forest.exr").

### n.compat.temp_override(**kwargs)
bpy.context.temp_override (4.0+), for the few operators that need a context.
