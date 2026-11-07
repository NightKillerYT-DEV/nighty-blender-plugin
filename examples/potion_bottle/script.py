# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized potion bottle: a big round flask with thick glass, glowing liquid with bubbles at the top, a chunky cork
under a red wax seal with drips, a gold neck collar, twine wraps and a paper tag hanging on a string.
tags: potion, bottle, flask, glass, liquid, magic, alchemy, fantasy, item, pickup, loot, stylized, cartoon, rpg, lathe
Exaggerated bulb and short neck; the glass is one hollow lathe (up the outside, over the lip, down the inside) and the
liquid follows the inner wall up to its level. Bright liquid against warm cork, red wax and gold.
budget: 5500 (a hero pickup item seen up close)
"""
import nighty as n

n.settings(detail="low", size=0.18, collection="Potion")
glass = n.surface("Potion Glass", "glass", color="#dff5ff")
liquid = n.surface("Potion Liquid", "glow", color="#7a12e6", glow=0.9)   # deep color, soft glow: stays saturated
cork = n.surface("Potion Cork", "wood", color="#c08a55", grain="Z", style="stylized")
# thin parts (string, twine, drips) stay realistic: the game look would paint them all as edge highlight
wax = n.surface("Potion Wax", "plastic", color="#c81d2e", wear=0.05, dirt=0.05, roughness=0.3)
gold = n.surface("Potion Gold", "gold", color="#f4b93a", style="stylized")
twine = n.surface("Potion Twine", "fabric", color="#8d5b30", wear=0.0, dirt=0.1)
paper = n.surface("Potion Tag", "painted_wood", color="#f0e0b4", style="painted")
parts = []


def keep(obj):
    parts.append(obj)
    return obj


# ---- glass: a hollow lathe with a 4 mm wall (radius, height)
bulb_out = n.spline([(0.03, 0.0), (0.052, 0.008), (0.064, 0.03), (0.066, 0.056), (0.059, 0.082), (0.041, 0.101),
                     (0.019, 0.113)], samples=2)
bulb_in = n.spline([(0.015, 0.11), (0.037, 0.098), (0.055, 0.08), (0.062, 0.056), (0.06, 0.032), (0.049, 0.012),
                    (0.028, 0.004)], samples=2)
neck = [(0.018, 0.12), (0.018, 0.139), (0.023, 0.141), (0.023, 0.149), (0.015, 0.15)]       # neck, lip, rim
inside = [(0.015, 0.148), (0.015, 0.12)] + bulb_in + [(0.0, 0.004)]
keep(n.lathe([(0.0, 0.0)] + bulb_out + neck + inside, segments=28, name="Bottle", material=glass))

# ---- liquid: the inner wall up to LEVEL, a hair inside it, with three bubbles floating on top
LEVEL = 0.07
wall = list(reversed(bulb_in))                         # bottom to top
prof = [(0.0, 0.0045)]
for (r0, z0), (r1, z1) in zip(wall, wall[1:]):
    if z0 < LEVEL:
        prof.append((r0 * 0.993, z0 + 0.0004))
        if z1 >= LEVEL:                                # where the wall crosses the level
            t = (LEVEL - z0) / (z1 - z0)
            prof.append(((r0 + (r1 - r0) * t) * 0.993, LEVEL))
prof.append((0.0, LEVEL))
keep(n.lathe(prof, segments=28, name="Liquid", material=liquid))
bubbles = [n.sphere(r, segments=8, at=(x, y, LEVEL), material=liquid) for r, x, y in
           ((0.007, 0.018, -0.012), (0.0045, 0.031, 0.006), (0.0035, -0.02, -0.022))]
keep(n.merge_parts(bubbles, name="Bubbles", weld=False))

# ---- cork, wax seal with drips
plug = n.cone(0.0148, 0.038, top=0.0175, segments=20, at=(0, 0, 0.147), name="Cork")   # at = center
n.chunky(plug, 0.6)
n.paint(plug, cork)
keep(plug)
seal = n.dome(0.0215, height=0.009, segments=20, at=(0, 0, 0.1655), name="WaxSeal")
drips = [n.capsule(0.0036, 0.014 + 0.006 * k, segments=8, axis="Z",
                   at=(0.0186 * c, 0.0186 * s, 0.162 - 0.003 * k))
         for k, (c, s) in enumerate(((1.0, 0.0), (-0.5, 0.866), (-0.5, -0.866)))]
keep(n.merge_parts([seal] + drips, name="WaxSeal", weld=False))
n.paint("WaxSeal", wax)

# ---- gold collar, twine wraps, a paper tag on a string
keep(n.torus(0.0195, 0.0042, segments=24, ring_segments=8, at=(0, 0, 0.1185), name="Collar", material=gold))
keep(n.merge_parts([n.torus(0.0186, 0.0019, segments=24, ring_segments=6, at=(0, 0, z)) for z in (0.127, 0.1315)],
                   name="Twine", weld=False))
n.paint("Twine", twine)
keep(n.pipe([(0.0, -0.0185, 0.129), (0.006, -0.036, 0.118), (0.012, -0.058, 0.096), (0.013, -0.066, 0.083)],
            radius=0.0011, bend=0.01, name="TagString", material=twine))
tag = n.rounded_box((0.034, 0.004, 0.042), radius=0.003, at=(0.013, -0.067, 0.066), rot=(-14, 0, 0), name="Tag")
n.boolean_cut(tag, n.cylinder(0.003, 0.02, axis="Y", at=(0.013, -0.067, 0.081)))   # the string's hole
n.paint(tag, paper)
keep(tag)
keep(n.dome(0.0075, height=0.0025, segments=12, axis=(0, -0.97, 0.24), at=(0.013, -0.0688, 0.062), name="TagStamp",
            material=wax))                                # a wax stamp on the tag

n.ground(parts)
n.center(parts, "XY")
