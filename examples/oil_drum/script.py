# SPDX-License-Identifier: GPL-3.0-or-later
"""Steel oil drum (55 gallon / 208 l): rolled chimes top and bottom, two rolling hoops, a recessed top head with a
pressed ring, a welded side seam, a painted band with stencil text wrapped around the drum, and two threaded bung
caps (2 inch and 3/4 inch) with wrench lugs.
tags: drum, oil drum, barrel, steel, metal, industrial, container, prop, 55 gallon, realistic
Real size (0.58 m wide, 0.88 m tall); one lathe profile carries the chimes, hoops and the head ring (no extra
parts to intersect); blue paint chipped on the hoops and chimes, grime collecting in the head.
budget: 6000 (a medium prop that repeats a lot in a level)
"""
import math

import nighty as n

n.settings(detail="low", size=0.9, collection="OilDrum")
paint = n.surface("Drum Paint", "painted_metal", color="#2b4a6c", wear=0.5, dirt=0.7, size=0.6)   # a used drum
band = n.surface("Drum Band", "painted_metal", color="#cdb36a", wear=0.5, dirt=0.7, size=0.6)
steel = n.surface("Drum Bungs", "steel", wear=0.2, dirt=0.5, size=0.4)
ink = n.surface("Drum Stencil", "painted", color="#1d2430", wear=0.0, dirt=0.4, roughness=0.8)

R, H, SEG = 0.282, 0.88, 36          # wall radius, height, sides (enough for a smooth silhouette)


def hoop(z):
    """A rolling hoop pressed out of the wall, as profile points (r, z)."""
    return [(R, z - 0.011), (R + 0.006, z - 0.006), (R + 0.009, z), (R + 0.006, z + 0.006), (R, z + 0.011)]


profile = ([(0.0, 0.012), (0.27, 0.012), (0.274, 0.003), (0.282, 0.0), (0.289, 0.004), (0.29, 0.014),
            (0.285, 0.021), (R, 0.028)]                                   # bottom head and rolled chime
           + hoop(0.293) + hoop(0.587)                                     # two rolling hoops
           + [(R, H - 0.028), (0.285, H - 0.021), (0.29, H - 0.014), (0.289, H - 0.004), (0.282, H),
              (0.274, H - 0.003), (0.27, H - 0.012),                       # top chime, down to the head
              (0.232, H - 0.012), (0.228, H - 0.007), (0.218, H - 0.007), (0.214, H - 0.012),   # pressed ring
              (0.0, H - 0.012)])
body = n.lathe(profile, segments=SEG, name="Body")   # the profile is already rounded: no bevel needed
n.paint(body, paint)
parts = [body]

# a painted band between the hoops: a ring 1 mm proud of the wall, same sides as the body (no flicker)
parts.append(n.tube(R + 0.001, 0.13, inner=R - 0.006, segments=SEG, at=(0, 0, 0.44), name="Band", material=band))

# stencil on the band: flat letters bent around the drum axis (bend angle = text width / radius)
for text, z, size in (("LUBRICATING OIL", 0.455, 0.042), ("208 L  SAE 30", 0.412, 0.026)):
    r = R + 0.0016
    label = n.text3d(text, size=size, depth=0.002, bevel=0, axis="-Y", at=(0, -r, z), name="Stencil")
    n.deform(label, "bend", math.degrees(n.bounds(label).size.x / r), axis="Z", apply=True)
    n.paint(label, ink)
    parts.append(label)

# welded side seam: a thin raised strip down the wall (hidden under the hoops where they cross it)
a = math.radians(-40)
parts.append(n.box((0.007, 0.003, H - 0.07), at=(R * math.sin(a), -R * math.cos(a), H / 2), rot=(0, 0, -40),
                   bevel=0.001, name="Seam", material=paint))


def bung(x, r, name):
    """A threaded bung: a flange ring pressed into the head and a cap with four wrench lugs."""
    z = H - 0.012
    flange = n.cylinder(r * 1.45, 0.006, at=(x, 0, z + 0.001), name=name)
    cap = n.cylinder(r, 0.013, at=(x, 0, z + 0.0065), name=name + "Cap")
    for rot in (0, 90):
        n.boolean_cut(cap, n.box((r * 2.4, r * 0.32, 0.008), at=(x, 0, z + 0.013), rot=(0, 0, rot)))
    n.bevel(flange, width=0.0012)
    n.bevel(cap, width=0.001)
    return n.merge_parts([flange, cap], name=name, weld=False)


for x, r, name in ((0.17, 0.03, "BungLarge"), (-0.19, 0.017, "BungSmall")):
    b = bung(x, r, name)
    n.paint(b, steel)
    parts.append(b)

n.ground(parts)
n.center(parts, "XY")
