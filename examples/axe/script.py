# SPDX-License-Identifier: GPL-3.0-or-later
"""Realistic bearded axe: a forged head whose cheeks taper to a ground cutting edge (bright steel against the dark
forged body), a hammer poll, an oval ash haft with a swell knob, and a ridged leather grip wrap.
tags: axe, bearded axe, hatchet, weapon, tool, melee, viking, medieval, wood, steel, forged, leather, realistic
0.65 m. The head is its side outline intersected with two tapering wedges (one per edge direction), so the blade
thins toward the whole cutting edge; the faces past the wedges' last kink are the ground edge (painted bright).
budget: 2500 (a small game prop / melee weapon)
"""
import math

import nighty as n

n.settings(detail="low", size=0.65, collection="Axe")
ash = n.surface("Axe Ash", "wood", color="#8c5f39", grain="Z", wear=0.15, dirt=0.35, size=0.4)
forged = n.surface("Axe Forged", "gunmetal", wear=0.12, dirt=0.45, size=0.3)
edge = n.surface("Axe Edge", "steel", wear=0.1, dirt=0.05, roughness=0.22, size=0.3)
leather = n.surface("Axe Leather", "leather", color="#4a2c1a", wear=0.2, dirt=0.3, size=0.3)
HZ = 0.575                  # the eye's center height on the haft
T = 0.0195                  # half the eye's thickness (the cheeks start thinner: a forged shoulder)
GRIND = 0.131               # where the ground edge bevel starts (along each wedge)


# ---- head, built around the eye at the origin: side outline (blade forward along +X, beard hanging down)
head = n.extrude([(-0.032, 0.026, 0.006), (-0.032, -0.026, 0.006), (0.012, -0.031, 0.008)]
                 + n.spline([(0.03, -0.036), (0.062, -0.052), (0.088, -0.078), (0.103, -0.092)], samples=3)
                 + [(0.11, -0.093, 0.003)]
                 + n.spline([(0.116, -0.088), (0.132, -0.055), (0.142, -0.01), (0.141, 0.03)], samples=4)
                 + [(0.134, 0.046, 0.003), (0.09, 0.038, 0.01), (0.03, 0.032, 0.008), (0.0, 0.031, 0.006)],
                 depth=2 * T + 0.002, name="AxeHead")


def wedge(start, turn):
    """Top view of the blade thickness: full at the eye, a shoulder, cheeks tapering to the grind line, then a
    steeper bevel to a 1 mm edge; turned about Y so it thins toward that part of the edge."""
    half = [(-0.06, T), (start - 0.008, T), (start, 0.0135), (GRIND, 0.0033), (GRIND + 0.01, 0.0006),
            (0.2, 0.0005)]
    outline = [(x, -y) for x, y in half] + [(x, y) for x, y in half[::-1]]
    return n.extrude(outline, depth=0.4, plane="XY", rot=(0, turn, 0))


n.boolean_intersect(head, wedge(0.034, 0))    # the middle and top of the edge
n.boolean_intersect(head, wedge(0.044, 25))   # the lower edge, down to the beard tip
u = (math.cos(math.radians(25)), -math.sin(math.radians(25)))


def in_grind(co):
    """Past the grind line of either wedge: the ground edge."""
    return co.x > GRIND - 0.002 or co.x * u[0] + co.z * u[1] > GRIND - 0.002


n.bevel(head, width=0.0006, angle=50)          # soften the forged outline (the grind lines are flatter)
ground = [p.index for p in head.data.polygons if in_grind(p.center)]
n.paint(head, forged)
n.paint(head, edge, faces=ground)
n.move(head, (0, 0, HZ))

# ---- haft: an oval ash handle with a swell knob at the end, its top just showing above the eye
haft = n.lathe(n.spline([(0.0, 0.0), (0.021, 0.004), (0.023, 0.03), (0.0165, 0.07), (0.0155, 0.3), (0.017, 0.48),
                         (0.0195, 0.55), (0.0195, HZ + 0.034), (0.0, HZ + 0.036)], samples=2), name="Haft")
haft.scale = (1.0, 0.72, 1.0)                 # real hafts are oval: they don't turn in the hand
n.apply_transforms(haft)
n.mark_bevel(haft)
n.hole(haft, 0.004, at=(0.0, 0.0, 0.016), axis="Y")   # lanyard hole through the knob
n.bevel(haft, width=0.0015, limit="weight")
n.paint(haft, ash)

# ---- leather grip wrap: raised turns over the throat
ridges = []
for k in range(9):          # each turn: a dip where it overlaps the last one, then the raised strap
    z = 0.085 + k * 0.015
    ridges += [(0.0184, z), (0.0198, z + 0.006)]
ridges.append((0.0184, 0.085 + 9 * 0.015))
wrap = n.lathe([(0.0, 0.085)] + ridges + [(0.0, ridges[-1][1])], name="GripWrap")
wrap.scale = (1.0, 0.72, 1.0)
n.apply_transforms(wrap)
n.paint(wrap, leather)

parts = [head, haft, wrap]
n.ground(parts)
n.center(parts, "XY")
