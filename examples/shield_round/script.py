# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized round shield: blue and cream painted planks over a dark backing disc, two iron straps crossing the face,
a thick iron rim with gold rivets, a big iron boss on a gold flange, back battens and a grip.
tags: shield, round shield, viking, buckler, wood, iron, fantasy, medieval, armor, weapon, stylized, fortnite, roblox
Layers that read from the side: backing, planks, straps, rim, flange, boss; clear color blocks and chunky edges.
Each plank is an outline clipped to the circle (no booleans); the gaps show the dark backing behind them.
budget: 6500 (a hand-held shield; low detail, chunky bevels)
"""
import math

import nighty as n

n.settings(detail="low", size=0.62, collection="Shield")
blue = n.surface("Shield Blue", "painted_wood", color="#2f62c0", grain="Z", style="stylized")
cream = n.surface("Shield Cream", "painted_wood", color="#eadbb2", grain="Z", style="stylized")
back = n.surface("Shield Backing", "wood", color="#4a2b17", style="stylized")
iron = n.surface("Shield Iron", "steel", color="#6f7a8a", style="stylized")
gold = n.surface("Shield Gold", "gold", color="#f4b93a", style="stylized")
wood = n.surface("Shield Wood", "wood", color="#8a5530", style="stylized")
R, T, GAP, COUNT = 0.29, 0.022, 0.007, 6
parts = []


def keep(obj):
    parts.append(obj)
    return obj


# ---- planks clipped to the circle, alternating colors; a dark disc behind fills the gaps
width = (2 * R - (COUNT - 1) * GAP) / COUNT
planks = []
for i in range(COUNT):
    x0 = -R + i * (width + GAP)
    xs = [x0 + width * k / 6 for k in range(7)]
    top = [(x, math.sqrt(max(0.0, R * R - x * x))) for x in xs]
    plank = n.extrude([(x, -z) for x, z in reversed(top)] + top, depth=T, at=(0, -0.004, 0),
                      material=cream if i % 2 else blue)
    n.bevel(plank, width=0.003, segments=2)
    planks.append(plank)
keep(n.merge_parts(planks, name="Planks", weld=False))
keep(n.cylinder(R - 0.006, 0.012, segments=48, axis="Y", at=(0, T / 2, 0), name="Backing", material=back))

# ---- iron straps across the face, held by gold rivets
FACE = -T / 2 - 0.004               # the planks' front face
straps = []
for rot, dy in ((0, 0.0), (90, -0.0012)):    # the vertical strap lies 1 mm over the other (no z-fighting)
    strap = n.box((2 * R - 0.02, 0.008, 0.046), at=(0, FACE - 0.003 + dy, 0), rot=(0, rot, 0))
    n.chamfer(strap, 0.002)
    straps.append(strap)
keep(n.merge_parts(straps, name="Straps", weld=False))
n.paint("Straps", iron)
pts = [(c * 0.2, FACE - 0.007 - (0.0012 if s else 0.0), s * 0.2) for c, s in ((1, 0), (-1, 0), (0, 1), (0, -1))]
keep(n.merge_parts([n.bolt(0.011, kind="round", axis="-Y", at=p) for p in pts], name="StrapRivets", weld=False))
n.paint("StrapRivets", gold)

# ---- thick rim with gold rivets around it
keep(n.torus(R + 0.004, 0.02, segments=48, ring_segments=8, axis="Y", at=(0, -0.004, 0), name="Rim",
             material=iron))
rim_rivets = []
for k in range(12):
    a = math.radians(15 + k * 30)
    rim_rivets.append(n.bolt(0.009, kind="round", axis="-Y", at=(R * math.cos(a), -0.0235, R * math.sin(a))))
keep(n.merge_parts(rim_rivets, name="RimRivets", weld=False))
n.paint("RimRivets", gold)

# ---- boss: a gold flange and a big iron dome
flange = n.cylinder(0.115, 0.01, segments=32, axis="Y", at=(0, FACE - 0.011, 0), name="BossFlange")
n.chunky(flange, 0.8)
n.paint(flange, gold)
keep(flange)
keep(n.dome(0.088, height=0.062, segments=32, axis="-Y", at=(0, FACE - 0.015, 0), name="Boss", material=iron))

# ---- back: two battens and a grip
battens = [n.box((0.42, 0.016, 0.05), at=(0, T / 2 + 0.0135, z)) for z in (-0.11, 0.11)]
for b in battens:
    n.chamfer(b, 0.003)
keep(n.merge_parts(battens, name="Battens", weld=False))
n.paint("Battens", wood)
keep(n.handle(0.13, 0.04, 0.011, axis="+Y", at=(0, T / 2 + 0.006, 0), name="Grip", material=wood))

n.ground(parts)
n.center(parts, "XY")
