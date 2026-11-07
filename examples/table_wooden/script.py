# SPDX-License-Identifier: GPL-3.0-or-later
"""Farmhouse dining table: a planked oak top with breadboard ends and dowel plugs, turned legs and an apron in
chipped charcoal paint (the wood shows through on the edges), square leg blocks where the apron joins.
tags: table, dining table, farmhouse table, furniture, wood, wooden, kitchen, interior, legs, turned, realistic
1.6 x 0.9 m, 0.76 m tall; the legs are one lathe profile each (foot, beads, vase swell) under a square block.
budget: 4000 (a furniture prop)
"""
import nighty as n

n.settings(detail="low", size=1.6, collection="Table")
oak_x = n.surface("Table Oak X", "wood", color="#9a7247", grain="X", wear=0.2, dirt=0.35, size=0.8)
oak_y = n.surface("Table Oak Y", "wood", color="#9a7247", grain="Y", wear=0.2, dirt=0.35, size=0.8)
paint = n.surface("Table Paint", "painted_wood", color="#2f3331", wear=0.22, dirt=0.3, size=0.6)
plug = n.surface("Table Plugs", "wood", color="#4a2e18", grain="Z", wear=0.0, dirt=0.2)

W, D, H, T = 1.6, 0.9, 0.76, 0.04       # top size, height, top thickness
BE = 0.075                              # breadboard end width

# top: five boards along X between two breadboard ends running across (grain along Y)
boards = n.planks((W - 2 * BE, D), count=5, thickness=T, gap=0.003, plane="XY", at=(0, 0, H - T / 2),
                  bevel=0.004, seed=2, name="TopBoards")
n.paint(boards, oak_x)
ends = [n.box((BE - 0.002, D, T), at=(s * (W / 2 - BE / 2), 0, H - T / 2), bevel=0.005) for s in (-1, 1)]
ends = n.merge_parts(ends, name="BreadboardEnds", weld=False)
n.paint(ends, oak_y)
plugs = [n.cylinder(0.008, 0.003, at=(s * (W / 2 - BE / 2), y, H + 0.0012)) for s in (-1, 1)
         for y in (-0.3, 0.0, 0.3)]
plugs = n.merge_parts(plugs, name="DowelPlugs", weld=False)
n.paint(plugs, plug)

# legs: a square block under the top (the apron joins it), then a turned leg below it
BLOCK, BZ = 0.07, 0.17                  # block size and height
LX, LY = W / 2 - 0.16, D / 2 - 0.08     # leg centers
TOPZ = H - T                            # the top's underside
turned = [(0.0, 0.0), (0.026, 0.0), (0.03, 0.014), (0.023, 0.05), (0.021, 0.19), (0.029, 0.215), (0.032, 0.235),
          (0.026, 0.258), (0.031, 0.33), (0.036, 0.43), (0.024, 0.5), (0.03, 0.52), (0.033, TOPZ - BZ + 0.01),
          (0.0, TOPZ - BZ + 0.01)]       # (radius, height): foot, bead, vase swell, neck, collar into the block
legs = []
for sx in (-1, 1):
    for sy in (-1, 1):
        leg = n.lathe(turned, at=(sx * LX, sy * LY, 0))
        n.bevel(leg, width=0.002)
        block = n.box((BLOCK, BLOCK, BZ - 0.001), at=(sx * LX, sy * LY, TOPZ - BZ / 2 - 0.0005), bevel=0.004)
        legs += [leg, block]
legs = n.merge_parts(legs, name="Legs", weld=False)
n.paint(legs, paint)

# apron: boards between the blocks (ends sunk into them), 2 mm under the top (the blocks 1 mm: no shared
# planes), with chamfered edges
AH, AT = 0.11, 0.022
az = TOPZ - 0.002 - AH / 2
apron = [n.box((2 * LX - 0.02, AT, AH), at=(0, sy * (LY + BLOCK / 2 - AT / 2 - 0.006), az)) for sy in (-1, 1)]
apron += [n.box((AT, 2 * LY - 0.02, AH), at=(sx * (LX + BLOCK / 2 - AT / 2 - 0.006), 0, az)) for sx in (-1, 1)]
for a in apron:
    n.chamfer(a, 0.004)
apron = n.merge_parts(apron, name="Apron", weld=False)
n.paint(apron, paint)

parts = [boards, ends, plugs, legs, apron]
n.ground(parts)
n.center(parts, "XY")
