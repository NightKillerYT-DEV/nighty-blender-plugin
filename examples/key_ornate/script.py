# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized ornate key: a chunky gold bow with a scalloped flower outline, a navy center holding a cut sapphire on
four spokes, collars and a knob on a thick shaft, and a toothed bit; lying flat like a pickup on the ground.
tags: key, skeleton key, old key, lock, door, item, pickup, quest, treasure, fantasy, medieval, gold, stylized, roblox
Oversized, chunky parts so it reads small on screen; flower outline from a polar formula, extruded with a hole.
budget: 3200 (a pickup item; low detail, chunky bevels)
"""
import math

import nighty as n

n.settings(detail="low", size=0.14, collection="Key")
gold = n.surface("Key Gold", "gold", color="#f4b93a", style="stylized", roughness=0.4)  # satin: flat faces stay gold
navy = n.surface("Key Navy", "plastic", color="#27324a", style="stylized")
gem = n.surface("Key Sapphire", "glow", color="#2a5cff", glow=1.0)   # a magic stone: saturated, lit from inside
H = 0.005    # half the key's thickness: everything is centered at this height so it lies flat
BX = -0.042  # the bow's center
parts = []


def keep(obj):
    parts.append(obj)
    return obj


def soft(obj, width):
    """A rounded 2-segment bevel: chunky edges for few triangles."""
    n.bevel(obj, width=width, segments=2, profile=0.6)


def flower(r, bump, lobes=4, count=24):
    """A scalloped round outline: radius r with lobes bumps of size bump."""
    return [(BX + (r + bump * math.cos(lobes * a)) * math.cos(a), (r + bump * math.cos(lobes * a)) * math.sin(a))
            for a in (2 * math.pi * k / count for k in range(count))]


# ---- bow: a flower ring, a navy center with a sapphire, four spokes between them
bow = n.extrude(flower(0.029, 0.0065), holes=[flower(0.018, 0.004)], depth=0.01, plane="XY", at=(0, 0, H),
                name="Bow")
soft(bow, 0.0022)
n.paint(bow, gold)
keep(bow)
spokes = [n.box((0.014, 0.004, 0.006), at=(BX + 0.015 * math.cos(a), 0.015 * math.sin(a), H), rot=(0, 0, math.degrees(a)))
          for a in (math.radians(45 + 90 * k) for k in range(4))]
keep(n.merge_parts(spokes, name="Spokes", weld=False))
n.paint("Spokes", gold)
center = n.cylinder(0.0105, 0.009, at=(BX, 0, H), name="BowCenter")
soft(center, 0.0018)
n.paint(center, navy)
keep(center)
stone = n.lathe([(0.0, 0.0), (0.0092, 0.0), (0.0092, 0.0022), (0.0055, 0.0055), (0.0, 0.0055)], segments=8,
                at=(BX, 0, H + 0.0042), name="Sapphire", material=gem)
n.shade_flat(stone)  # facets catch the light like a cut stone
keep(stone)

# ---- shaft with a knob and two collars, a toothed bit at the end
keep(n.cylinder(0.0055, 0.082, axis="X", at=(0.016, 0, H), name="Shaft", material=gold))
keep(n.sphere(0.0085, segments=12, at=(-0.0105, 0, H), name="Knob", material=gold))
for x in (0.0, 0.008):
    collar = n.cylinder(0.0078, 0.0045, axis="X", at=(x, 0, H), name="Collar")
    soft(collar, 0.0012)
    n.paint(collar, gold)
    keep(collar)
bit = n.extrude([(0.036, 0.003), (0.036, -0.026), (0.043, -0.026), (0.043, -0.019), (0.047, -0.019),
                 (0.047, -0.026), (0.053, -0.026), (0.053, -0.014), (0.057, -0.014), (0.057, -0.026),
                 (0.06, -0.026), (0.06, 0.003)], depth=0.008, plane="XY", at=(0, 0, H), name="Bit")
soft(bit, 0.0016)
n.paint(bit, gold)
keep(bit)
keep(n.sphere(0.0062, segments=12, at=(0.0585, 0, H), name="Tip", material=gold))

n.rotate(parts, -15, "Z")
n.ground(parts)
n.center(parts, "XY")
