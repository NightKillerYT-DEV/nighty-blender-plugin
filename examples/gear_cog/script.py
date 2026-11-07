# SPDX-License-Identifier: GPL-3.0-or-later
"""Industrial spur gear on a keyed shaft: 24 teeth with tapered flanks, a web with six lightening holes, a raised
hub with a keyway and a set screw, four socket bolts, and the steel shaft and key it drives.
tags: gear, cog, machine, mechanical, steampunk, industrial, engineering, part, prop, shaft, realistic
The whole gear is ONE extruded outline (teeth computed with math) with its holes passed to n.extrude: clean, light
geometry with no booleans. Machine-blue paint worn to bare steel on the teeth; polished shaft, black-oxide bolts.
budget: 5000 (a machine part / pickup prop)
"""
import math

import nighty as n

n.settings(detail="low", size=0.32, collection="Gear")
paint = n.surface("Gear Paint", "painted_metal", color="#3b566e", wear=0.3, dirt=0.4, size=0.2)
shaft_mat = n.surface("Gear Shaft", "steel", roughness=0.25, wear=0.15, dirt=0.3, size=0.2)
oxide = n.surface("Gear Oxide", "gunmetal", wear=0.2, dirt=0.3, size=0.2)
parts = []

T = 0.03                                   # gear thickness (along Y: the gear stands, facing -Y)
ROOT, TIP, N = 0.138, 0.158, 24            # root and tip radius, tooth count
BORE, KEY = 0.022, 0.006                   # bore radius, half the keyway width


def gear_outline():
    """Teeth as (x, z) points: root gap, flank, tip, flank, for each tooth."""
    pts = []
    p = 2 * math.pi / N
    mid = ROOT + (TIP - ROOT) * 0.45
    for k in range(N):
        c = k * p
        for r, a in ((ROOT, c - 0.5 * p), (ROOT, c - 0.29 * p), (mid, c - 0.21 * p), (TIP, c - 0.12 * p),
                     (TIP, c + 0.12 * p), (mid, c + 0.21 * p), (ROOT, c + 0.29 * p)):
            pts.append((r * math.sin(a), r * math.cos(a)))      # 7 points a tooth: the chamfer does the rest
    return pts


def bore_outline():
    """The bore with a keyway notch at the top."""
    t1 = math.acos(KEY / BORE)
    pts = [(BORE * math.cos(t1 - i * (2 * math.pi - 2 * (t1 - math.pi / 2) - math.pi) / 23 - 0.0),
            BORE * math.sin(t1 - i * (2 * math.pi - 2 * (t1 - math.pi / 2) - math.pi) / 23)) for i in range(24)]
    return pts + [(-KEY, BORE + 0.0065), (KEY, BORE + 0.0065)]


holes = [n.circle_points(0.0515, count=32)]   # the gear is pressed on the hub (0.5 mm overlap, no shared faces)
for k in range(6):                         # lightening holes in the web
    a = 2 * math.pi * k / 6 + math.pi / 6
    holes.append(n.circle_points(0.024, count=20, center=(0.095 * math.cos(a), 0.095 * math.sin(a))))
gear = n.extrude(gear_outline(), depth=T, plane="XZ", holes=holes, name="Gear")
n.chamfer(gear, 0.0008)
n.paint(gear, paint)
parts.append(gear)

# raised hub on both faces, same bore and keyway, a set screw hole on top
hub = n.extrude(n.circle_points(0.052, count=32), depth=T + 0.032, plane="XZ", holes=[bore_outline()], name="Hub")
n.mark_bevel(hub)
n.hole(hub, 0.0045, at=(0, 0, 0.052), axis="Z", depth=0.012)
n.bevel(hub, width=0.0015, limit="weight")
n.paint(hub, paint)
parts.append(hub)
parts.append(n.bolts_around((0, -(T + 0.032) / 2, 0), 0.037, 4, radius=0.0055, kind="hex", axis="-Y",
                            start_angle=45, name="HubBolts", material=oxide))

# keyed shaft through the bore
shaft = n.cylinder(BORE - 0.0005, 0.16, axis="Y", at=(0, 0.01, 0), name="Shaft")
n.chamfer(shaft, 0.0015)
n.paint(shaft, shaft_mat)
parts.append(shaft)
key = n.box((2 * KEY - 0.0003, 0.07, 0.0085), at=(0, 0.0, BORE + 0.002), name="Key")
n.chamfer(key, 0.0008)
n.paint(key, oxide)
parts.append(key)

n.ground(parts)
n.center(parts, "XY")
