# SPDX-License-Identifier: GPL-3.0-or-later
"""Traffic cone: a 70 cm PVC cone with a flared foot and a rolled, open top, two raised reflective bands, on a
square rubber base with a stepped, raised center pad.
tags: traffic cone, cone, road, street, construction, safety, prop, environment, lathe, orange, realistic
One lathe profile makes the whole cone (foot flare, wall, top lip, hollow top); the bands are closed lathe rings
standing 2.5 mm proud of the wall; the base is an extruded rounded square with an inset pad.
budget: 2700 (a small street prop)
"""
import nighty as n

n.settings(detail="low", size=0.7, collection="TrafficCone")
pvc = n.surface("Cone PVC", "plastic", color="#ff5a1a", wear=0.2, dirt=0.6, size=0.4)   # a cone that has seen a road
reflect = n.surface("Cone Reflective", "plastic", color="#eceeee", roughness=0.22, wear=0.15, dirt=0.45, size=0.4)
rubber = n.surface("Cone Rubber", "rubber", wear=0.2, dirt=0.6, size=0.4)

# base: a rounded square slab with two steps up to the pad the cone stands on
BASE = 0.03
base = n.extrude(n.rounded_rect(0.38, 0.38, 0.05), depth=BASE, plane="XY", at=(0, 0, BASE / 2), name="Base")
n.inset(base, "+Z", amount=0.018, depth=0.005)          # a step around the rim
n.inset(base, "+Z", amount=0.022, depth=0.005)          # the raised center pad
TOP = BASE + 0.01
n.bevel(base, width=0.003)
n.paint(base, rubber)

# the cone: foot flare, straight wall, rolled lip and a hollow top, in one profile (radius, height)
Z0, R0, Z1, R1 = TOP + 0.022, 0.158, 0.688, 0.036


def r_at(z):
    """The wall's radius at height z."""
    return R0 + (R1 - R0) * (z - Z0) / (Z1 - Z0)


cone = n.lathe([(0.176, TOP - 0.002), (0.172, TOP + 0.008), (R0, Z0), (R1, Z1), (0.041, Z1 + 0.004),
                (0.041, 0.70), (0.027, 0.70), (0.024, 0.655), (0.0, 0.655)], name="Cone")
n.bevel(cone, width=0.002)
n.paint(cone, pvc)


def band(z1, z2):
    """A reflective sleeve between two heights: 2.5 mm outside the wall, 3 mm sunk into it."""
    return [(r_at(z1) - 0.003, z1), (r_at(z1) + 0.0025, z1), (r_at(z2) + 0.0025, z2), (r_at(z2) - 0.003, z2),
            (r_at(z1) - 0.003, z1)]


bands = n.merge_parts([n.lathe(band(0.53, 0.635), caps="none"), n.lathe(band(0.39, 0.465), caps="none")],
                      name="Bands", weld=False)
n.paint(bands, reflect)

parts = [base, cone, bands]
n.ground(parts)
n.center(parts, "XY")
