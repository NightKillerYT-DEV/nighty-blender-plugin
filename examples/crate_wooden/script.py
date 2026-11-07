# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized wooden crate: chunky dark frame, warm planks with gaps sitting inside it, a diagonal brace on the front
and back, dark iron corner brackets with big nails, and iron handles on the sides.
tags: crate, box, wood, wooden, container, storage, loot, prop, planks, stylized, cartoon, fortnite, roblox
Exaggerated frame (12 % of the size), clear value steps: light planks, dark frame, darker iron; game look.
budget: 7000 (a common world prop; many can stand in a scene)
"""
import math

import nighty as n

S = 0.6      # outer size (m)
B = 0.075    # frame beam width: chunky on purpose
E = 0.02     # how far the planks sit inside the frame
T = 0.02     # plank thickness
n.settings(detail="low", size=S, collection="Crate")
plank_x = n.surface("Crate Planks X", "wood", color="#d69a55", grain="X", style="stylized")
plank_y = n.surface("Crate Planks Y", "wood", color="#d69a55", grain="Y", style="stylized")
frame_x = n.surface("Crate Frame X", "wood", color="#7e4c2a", grain="X", style="stylized")
frame_y = n.surface("Crate Frame Y", "wood", color="#7e4c2a", grain="Y", style="stylized")
frame_z = n.surface("Crate Frame Z", "wood", color="#7e4c2a", grain="Z", style="stylized")
inner = n.surface("Crate Inner", "wood", color="#4a2c16", style="stylized")
iron = n.surface("Crate Iron", "iron", color="#4b505b", style="stylized")
h = S / 2
parts = []


def keep(obj):
    parts.append(obj)
    return obj


# ---- core (keeps the planks connected and hides the inside) and planks on all faces but the bottom
face = h - E - T                                    # the core's half size
keep(n.box(2 * face, at=(0, 0, h), name="Core", material=inner))
span = S - 2 * B + 0.03                             # planks run a little under the frame
pl = []
for s in (-1, 1):
    pl.append(n.planks((span, span), count=3, thickness=T, gap=0.012, plane="XZ", at=(0, s * (face + T / 2), h),
                       seed=1 + s, material=plank_x))
    pl.append(n.planks((span, span), count=3, thickness=T, gap=0.012, plane="YZ", at=(s * (face + T / 2), 0, h),
                       seed=4 + s, material=plank_y))
pl.append(n.planks((span, span), count=3, thickness=T, gap=0.012, plane="XY", at=(0, 0, h + face + T / 2), seed=9,
                   material=plank_x))
keep(n.merge_parts(pl, name="Boards", weld=False))

# ---- frame: a beam along each of the 12 edges, chunky soft edges
beams = []
c = h - B / 2
for a in (-1, 1):
    for b in (-1, 1):
        beams.append(n.box((S - 2 * B, B, B), at=(0, a * c, h + b * c), material=frame_x))
        beams.append(n.box((B, S - 2 * B, B), at=(a * c, 0, h + b * c), material=frame_y))
        beams.append(n.box((B, B, S), at=(a * c, b * c, h), material=frame_z))
for beam in beams:
    n.bevel(beam, width=0.009, segments=2, profile=0.6)
keep(n.merge_parts(beams, name="Frame", weld=False))

# ---- diagonal braces lying on the front and back planks, between the frame beams
inside = S - 2 * B
length = inside * math.sqrt(2) - 0.02
braces = []
for s in (-1, 1):
    brace = n.box((length, 0.016, 0.07), at=(0, s * (h - E + 0.0075), h), rot=(0, 45 * s, 0))
    n.bevel(brace, width=0.006, segments=2, profile=0.6)
    braces.append(brace)
keep(n.merge_parts(braces, name="Braces", weld=False))
n.paint("Braces", frame_x)

# ---- iron corner brackets with one big nail per face (light nails: 8-sided domes are plenty at this size)
shape = n.box(S, at=(0, 0, h), name="BracketShape")
brk = [n.corner_bracket(shape, (x, y, z), size=0.1, thickness=0.008, nails_per_face=0, name="Bracket",
                        material=iron)
       for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
nails = []
for axis in range(3):                                # one nail in the middle of each bracket face
    for x in (-1, 1):
        for y in (-1, 1):
            for z in (-1, 1):
                p = [x * (h - 0.05), y * (h - 0.05), h + z * (h - 0.05)]
                p[axis] = (x, y, z)[axis] * (h + 0.008) + (h if axis == 2 else 0)
                d = [0, 0, 0]
                d[axis] = (x, y, z)[axis]
                nails.append(n.nails([tuple(p)], radius=0.011, axis=tuple(d), segments=8))
n.delete(shape)
keep(n.merge_parts(brk, name="Brackets", weld=False))
keep(n.merge_parts(nails, name="BracketNails", weld=False))
n.paint("BracketNails", iron)

# ---- side handles on iron plates
for sx in (-1, 1):
    plate = n.box((0.01, 0.2, 0.06), at=(sx * (h - E + 0.004), 0, h + 0.1), name="HandlePlate")
    n.chamfer(plate, 0.003)
    n.paint(plate, iron)
    keep(plate)
    keep(n.handle(0.16, 0.045, 0.011, axis=(sx, 0, 0), at=(sx * (h - E + 0.009), 0, h + 0.1), name="Handle",
                  material=iron))

n.ground(parts)
n.center(parts, "XY")
