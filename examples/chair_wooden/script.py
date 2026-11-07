# SPDX-License-Identifier: GPL-3.0-or-later
"""Wooden dining chair: back legs cut from one bent side profile that rise into the back posts, tapered front legs,
apron and H-stretchers, a solid seat with an upholstered leather pad, a curved crest rail and three back slats.
tags: chair, seat, furniture, wood, wooden, dining chair, interior, cushion, leather, walnut, realistic
Seat at 0.46 m, 0.95 m tall; walnut with the grain running along every part (legs Z, rails X, seat Y).
budget: 2800 (a furniture prop seen up close)
"""
import math

import nighty as n

n.settings(detail="low", size=0.95, collection="Chair")
wood = dict(color="#6e4528", wear=0.15, dirt=0.3, size=0.5)
leg_wood = n.surface("Chair Walnut Z", "wood", grain="Z", **wood)
rail_wood = n.surface("Chair Walnut X", "wood", grain="X", **wood)
seat_wood = n.surface("Chair Walnut Y", "wood", grain="Y", **wood)
leather = n.surface("Chair Leather", "leather", color="#3a2419", wear=0.2, dirt=0.25, size=0.5)

SW, SD, T = 0.46, 0.44, 0.024          # seat width, depth, board thickness
SZ = 0.46                              # top of the seat board
lx, ly = SW / 2 - 0.035, SD / 2 - 0.03  # leg centers
BOT = SZ - T                           # the seat board's underside: legs end here, rails 2 mm lower

# back legs: one side profile per leg (y, z, corner radius): splayed foot, straight under the seat, leaning back
LW = 0.038                              # the legs' front-to-back width
center = [(ly + 0.035, 0.0), (ly, BOT - 0.05), (ly + 0.08, 0.95)]
back_legs = []
for sx in (-1, 1):
    rear = [(y + LW / 2, z, 0.0 if i != 1 else 0.12) for i, (y, z) in enumerate(center)]
    front = [(y - LW / 2, z, 0.0 if i != 1 else 0.12) for i, (y, z) in enumerate(center)]
    prof = rear + front[::-1]
    prof[2] = (prof[2][0], prof[2][1], 0.008)   # round the top of the post a little
    prof[3] = (prof[3][0], prof[3][1], 0.008)
    leg = n.extrude(prof, depth=0.036, plane="YZ", at=(sx * lx, 0, 0))
    n.bevel(leg, width=0.003)
    back_legs.append(leg)

# front legs: square, tapering from 38 mm under the seat to 28 mm at the floor (4-sided cones turned 45 degrees)
front_legs = []
for sx in (-1, 1):
    leg = n.cone(0.028 * 0.7071, BOT, top=0.038 * 0.7071, segments=4, rot=(0, 0, 45), at=(sx * lx, -ly, BOT / 2))
    n.bevel(leg, width=0.003)
    front_legs.append(leg)
legs = n.merge_parts(back_legs + front_legs, name="Legs", weld=False)
n.paint(legs, leg_wood)

# seat board with an upholstered leather pad on top
seat = n.rounded_box((SW + 0.02, SD + 0.02, T), radius=0.008, at=(0, 0.0, SZ - T / 2), name="Seat")
n.paint(seat, seat_wood)
pad = n.rounded_box((SW - 0.03, SD - 0.06, 0.034), radius=0.014, at=(0, -0.01, SZ + 0.015), name="Pad")
n.paint(pad, leather)

# apron boards (ends sunk into the legs) and H-stretchers low between the legs. Parts that cross each other in
# sight are separate objects: the material's edge wear would mark the joint inside one object
AH = 0.07
az = BOT - 0.002 - AH / 2
rails = [n.box((2 * lx - 0.02, 0.02, AH), at=(0, sy * ly, az), bevel=0.003) for sy in (-1, 1)]
rails += [n.box((0.02, 2 * ly - 0.02, AH), at=(sx * lx, 0, az), bevel=0.003) for sx in (-1, 1)]
rails += [n.box((0.02, 2 * ly + 0.01, 0.022), at=(sx * lx, 0.003, 0.15), bevel=0.003) for sx in (-1, 1)]
rails = n.merge_parts(rails, name="Rails", weld=False)
cross = n.box((2 * lx - 0.01, 0.02, 0.022), at=(0, 0.0, 0.15), bevel=0.003, name="CrossStretcher")
n.paint([rails, cross], rail_wood)

# the back: a crest rail curved in plan, a lower rail and three slats, all leaning with the posts
dy, dz = center[2][0] - center[1][0], center[2][1] - center[1][1]
lean = math.degrees(math.atan2(dy, dz))


def on_back(h):
    """A point h meters up the back posts' center line (from the seat board's underside)."""
    t = (h - (BOT - 0.05)) / dz
    return (0.0, center[1][0] + dy * t, h)


arc = [(x, 0.018 * (1 - (x / lx) ** 2)) for x in [lx * (i / 6.0) for i in range(-6, 7)]]
crest = n.extrude(arc + [(x, y - 0.024) for x, y in arc[::-1]], depth=0.075, plane="XY", at=on_back(0.875),
                  rot=(-lean, 0, 0), name="Crest")
n.bevel(crest, width=0.004)
lower = n.box((2 * lx, 0.02, 0.04), at=on_back(0.6), rot=(-lean, 0, 0), bevel=0.003)
_, sy, sz = on_back(0.7275)
slats = [n.box((0.05, 0.012, 0.25), at=(x, sy + 0.002, sz), rot=(-lean, 0, 0), bevel=0.003)   # inside the crest's curve
         for x in (-0.1, 0.0, 0.1)]
back = n.merge_parts([crest, lower], name="BackRails", weld=False)
slats = n.merge_parts(slats, name="BackSlats", weld=False)
n.paint(back, rail_wood)
n.paint(slats, leg_wood)                # upright parts: grain along Z

parts = [legs, seat, pad, rails, cross, back, slats]
n.ground(parts)
n.center(parts, "XY")
