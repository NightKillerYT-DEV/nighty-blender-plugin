# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized tree: a chunky tapered trunk with root flares and a knot hole, three tapered branches, and big puffy
foliage clumps in three greens (light lumps high, dark lumps low), like the trees of big stylized games.
tags: tree, oak, stylized, cartoon, fortnite, roblox, foliage, nature, plant, environment, forest, low poly
Each clump is a few overlapping noise-bumped quad spheres in three greens (big lumps mid, small ones light or dark),
so the crown reads in layers from far away. Warm bark against cool greens.
budget: 7000 (a world tree; repeated many times, so far LODs come from the make_lods tool)
"""
import math

import nighty as n

n.settings(detail="low", size=3.0, collection="Tree")
bark = n.surface("Tree Bark", "wood", color="#7b4c2a", grain="Z", style="stylized")
hole = n.surface("Tree Hole", "wood", color="#2c1a0e", grain="Z", style="stylized")
leaf = n.surface("Tree Leaves", "plastic", color="#4f9f36", wear=0.0, dirt=0.0, roughness=0.75)
leaf_top = n.surface("Tree Leaves Light", "plastic", color="#86c94a", wear=0.0, dirt=0.0, roughness=0.75)
leaf_dark = n.surface("Tree Leaves Dark", "plastic", color="#2f6f2b", wear=0.0, dirt=0.0, roughness=0.8)
parts = []


def keep(obj):
    parts.append(obj)
    return obj


# ---- trunk with a flared foot, roots running into the ground, a knot hole
trunk = n.lathe(n.spline([(0.34, 0.0), (0.25, 0.1), (0.19, 0.38), (0.165, 1.0), (0.14, 1.5), (0.11, 1.95)],
                         samples=2) + [(0.0, 2.0)], segments=16, name="Trunk", material=bark)
keep(trunk)
roots = []
for k in range(5):                                       # thick, short, low roots that sink into the ground
    a = math.radians(k * 72 + 20)
    d = (math.cos(a), math.sin(a))
    start, end = (d[0] * 0.1, d[1] * 0.1, 0.24), (d[0] * 0.46, d[1] * 0.46, 0.012)
    v = [e - s for s, e in zip(start, end)]
    mid = [(s + e) / 2 for s, e in zip(start, end)]
    roots.append(n.cone(0.14, math.sqrt(sum(c * c for c in v)), top=0.022, segments=16, axis=tuple(v),
                        at=tuple(mid)))
keep(n.merge_parts(roots, name="Roots", weld=False))
n.paint("Roots", bark)
knot_at = (0.0, -0.172, 0.8)
keep(n.torus(0.05, 0.022, segments=12, ring_segments=6, axis="-Y", at=knot_at, name="KnotRim", material=bark))
keep(n.dome(0.05, height=0.012, segments=12, axis="-Y", at=(0.0, -0.165, 0.8), name="KnotHole", material=hole))

# ---- three tapered branches from the trunk up to the side clumps
tips = []
branches = []
for angle, z0, reach, rise in ((25, 1.25, 0.8, 0.65), (150, 1.45, 0.75, 0.6), (265, 1.6, 0.65, 0.5)):
    a = math.radians(angle)
    start = (0.0, 0.0, z0)
    end = (math.cos(a) * reach, math.sin(a) * reach, z0 + rise)
    v = [e - s for s, e in zip(start, end)]
    mid = [(s + e) / 2 for s, e in zip(start, end)]
    branches.append(n.cone(0.085, math.sqrt(sum(c * c for c in v)), top=0.04, segments=16, axis=tuple(v),
                           at=tuple(mid)))
    tips.append(end)
keep(n.merge_parts(branches, name="Branches", weld=False))
n.paint("Branches", bark)

# ---- foliage clumps: a big mid-green lump, light lumps on its upper sides, dark lumps low (three readable tones)
clumps = [((0.0, 0.0, 2.3), 0.78)] + [((x, y, z + 0.18), 0.58) for x, y, z in tips] + [((0.3, 0.32, 2.05), 0.5)]
LUMPS = (("Foliage", leaf, 0.0, 0.0, 0.0, 1.0, 20), ("FoliageLight", leaf_top, 0.45, 0.2, 0.42, 0.55, 16),
         ("FoliageLight", leaf_top, -0.38, -0.28, 0.45, 0.5, 16), ("FoliageDark", leaf_dark, 0.42, -0.45, -0.3, 0.55, 16),
         ("FoliageDark", leaf_dark, -0.5, 0.35, -0.25, 0.5, 16))
groups = {}
for k, ((x, y, z), r) in enumerate(clumps):
    for j, (name, mat, dx, dy, dz, f, seg) in enumerate(LUMPS):
        rr = r * f
        lump = n.sphere(rr, segments=seg, at=(x + dx * r, y + dy * r, z + dz * r))
        n.displace(lump, strength=rr * 0.13, scale=rr * 0.9, octaves=2, seed=k * 5 + j)
        groups.setdefault(name, (mat, []))[1].append(lump)
for name, (mat, objs) in groups.items():
    obj = n.merge_parts(objs, name=name, weld=False)
    n.smooth_by_angle(obj, 180)                          # soft, puffy shading all over
    n.paint(obj, mat)
    keep(obj)

n.ground(parts)
n.center(parts, "XY")
