# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized crystal cluster and cut gem: six-sided purple crystals with glowing tips growing out of chunky slate
boulders, with pebbles and a faceted ruby lying in front.
tags: crystal, gem, gemstone, jewel, ruby, amethyst, magic, mineral, loot, fantasy, pickup, cave, stylized, roblox
Few sides on purpose (6-sided crystals, an 8-sided cut gem), flat shaded so every facet catches the light; each
crystal is a prism plus a lighter glowing tip. The rock has a few big beveled facets: the painted edge highlights
then read as carved edges (on a dense low-poly ball they would read as a wireframe).
budget: 1800 (a small prop; low poly by design)
"""
import nighty as n

n.settings(detail="low", size=0.4, collection="Crystals")
body = n.surface("Crystal Purple", "plastic", color="#7d3cf0", style="stylized", roughness=0.2)
tip = n.surface("Crystal Tip Glow", "glow", color="#c890ff", glow=1.2)
stone = n.surface("Crystal Rock", "stone", color="#5d5b73", style="stylized")
ruby = n.surface("Gem Ruby", "plastic", color="#e3203f", style="stylized", roughness=0.15)
parts = []


def keep(obj):
    parts.append(obj)
    return obj


def boulder(radius, at, scale, seed, name):
    """A faceted stylized boulder: a few big facets (a 7-sided ball, lightly displaced) with soft bevels, so the
    painted edge highlights fall on a few big edges like a carved rock."""
    b = n.sphere(radius, segments=7, kind="uv", at=at, name=name, material=stone)
    n.displace(b, strength=radius * 0.15, scale=radius * 1.5, octaves=1, seed=seed)
    b.scale = scale
    n.apply_transforms(b)
    n.bevel(b, width=radius * 0.12, segments=2, profile=0.6)
    return keep(b)


# ---- the rock: two lumps; pebbles around
boulder(0.12, (0.0, 0.0, 0.03), (1.3, 1.05, 0.6), 4, "Rock")
boulder(0.07, (-0.08, 0.05, 0.05), (1.1, 1.0, 1.0), 7, "Rock")
boulder(0.025, (0.16, -0.08, 0.01), (1.3, 1.0, 0.7), 2, "Pebble")
boulder(0.02, (-0.15, -0.07, 0.01), (1.2, 1.0, 0.7), 9, "Pebble")

# ---- crystals: (radius, length, x, y, root z, tilt x, tilt y); roots inside the rock
for r, h, x, y, z, tx, ty in ((0.034, 0.19, 0.0, 0.0, 0.07, 0, 0), (0.024, 0.13, 0.06, 0.02, 0.07, -10, 32),
                              (0.026, 0.15, -0.065, 0.03, 0.09, -12, -30), (0.018, 0.09, 0.02, -0.06, 0.06, 35, 10),
                              (0.02, 0.1, -0.04, -0.05, 0.06, 30, -18), (0.015, 0.075, 0.09, -0.02, 0.06, 20, 45)):
    prism = n.lathe([(0.0, 0.0), (r, 0.0), (r * 1.08, h * 0.6), (r, h), (0.0, h)], segments=6,
                    at=(x, y, z), rot=(tx, ty, 0), name="Crystal", material=body)
    n.shade_flat(prism)
    keep(prism)
    point = n.lathe([(0.0, h - 0.002), (r, h - 0.002), (0.0, h + r * 1.6)], segments=6, at=(x, y, z),
                    rot=(tx, ty, 0), name="CrystalTip", material=tip)
    n.shade_flat(point)
    keep(point)

# ---- a brilliant-ish cut ruby lying in front (pavilion, girdle, crown, table)
gem = n.lathe([(0.0, -0.022), (0.031, 0.0), (0.031, 0.004), (0.019, 0.015), (0.0, 0.015)], segments=8,
              at=(0.14, -0.13, 0.05), rot=(62, 0, 25), name="CutGem", material=ruby)
n.shade_flat(gem)
keep(gem)

for o in parts:            # every block, pebble and the gem rests on the ground on its own
    if o.name.startswith(("Rock", "Pebble", "CutGem")):
        n.ground(o)
n.center(parts, "XY")
