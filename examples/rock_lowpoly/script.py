# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized rocks: a cluster of chunky chiseled boulders with big flat facets, soft chamfered edges that catch the
light, mossy tops, and a few pebbles around them.
tags: rock, stone, boulder, cliff, low poly, lowpoly, stylized, cartoon, fortnite, roblox, nature, environment, moss
Each rock is a coarse quad sphere (24 faces) sliced by random planes (big flat chiseled faces, not noise bumps),
squashed, cut flat underneath and chamfered; faces looking straight up get moss. Cool grey stone, warm moss.
budget: 1100 (a scatter prop; dozens in a scene)
"""
import math
import random

import nighty as n

n.settings(detail="low", size=1.2, collection="Rocks")
# flat colors with soft cavity dirt (the game look's edge paint would also line every low-poly crease)
stone = n.surface("Rock Stone", "plastic", color="#5e5b56", wear=0.0, dirt=0.35, roughness=0.85)
stone_dark = n.surface("Rock Stone Dark", "plastic", color="#4a4744", wear=0.0, dirt=0.35, roughness=0.85)
moss = n.surface("Rock Moss", "plastic", color="#3d6a20", wear=0.0, dirt=0.2, roughness=0.9)
parts = []


def rock(size, stretch, at, seed, mat=stone, segments=8, name="Rock"):
    """A chiseled boulder about size meters across, stretched (x, y, z), standing at (x, y)."""
    r = n.sphere(0.5, segments=segments, name=name)
    rnd = random.Random(seed)
    for v in r.data.vertices:                         # a little irregular...
        v.co *= rnd.uniform(0.88, 1.1)
    for k in range(8):                                # ...then sliced by planes: big chiseled faces
        a, tilt = 2 * math.pi * (k + rnd.uniform(-0.3, 0.3)) / 8, rnd.uniform(-0.2, 0.9)
        c = math.sqrt(1 - tilt * tilt)
        nx, ny, nz, d = math.cos(a) * c, math.sin(a) * c, tilt, rnd.uniform(0.33, 0.42)
        for v in r.data.vertices:
            t = v.co.x * nx + v.co.y * ny + v.co.z * nz - d
            if t > 0:
                v.co.x, v.co.y, v.co.z = v.co.x - nx * t, v.co.y - ny * t, v.co.z - nz * t
    r.data.update()
    r.scale = (size * stretch[0], size * stretch[1], size * stretch[2])
    n.apply_transforms(r)
    floor = -0.5 * size * stretch[2] * 0.55
    for v in r.data.vertices:                         # cut the bottom flat so it sits on the ground
        v.co.z = max(v.co.z, floor)
    r.data.update()
    r.location = (at[0], at[1], -floor)
    n.paint(r, mat)
    n.paint(r, moss, faces=[p.index for p in r.data.polygons if p.normal.z > 0.86])
    n.bevel(r, width=size * 0.03, segments=1, angle=20)    # chamfers: light catches them
    n.shade_flat(r)                                    # every facet reads as a chiseled plane
    parts.append(r)
    return r


rock(0.8, (1.25, 1.0, 0.85), (0.0, 0.0), seed=3, name="RockBig")
rock(0.48, (1.1, 0.95, 1.05), (0.5, -0.2), seed=7, mat=stone_dark, name="RockMid")
rock(0.3, (1.2, 1.0, 0.8), (0.24, -0.46), seed=11, name="RockSmall")
pebbles = [rock(s, (1.3, 1.0, 0.7), (x, y), seed=20 + k, name="Pebble")
           for k, (s, x, y) in enumerate(((0.12, -0.45, -0.3), (0.09, -0.32, -0.42), (0.1, 0.72, 0.18)))]
parts[-3:] = [n.merge_parts(pebbles, name="Pebbles", weld=False)]

n.ground(parts)
n.center(parts, "XY")
