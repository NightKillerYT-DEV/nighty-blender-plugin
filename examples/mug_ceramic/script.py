# SPDX-License-Identifier: GPL-3.0-or-later
"""Realistic stoneware mug of coffee on a saucer: one lathe profile for the walls (up the outside, over the rounded
lip, down the inside), dipped glaze with the raw clay foot showing, a curved handle, the coffee, a saucer with a well.
tags: mug, cup, coffee, tea, ceramic, stoneware, kitchen, tableware, saucer, prop, lathe, drink, realistic
8.6 cm wide, 9.5 cm tall; walls 6.5 mm thick (thin walls read as worn edges in realistic materials). The raw foot is
the same mesh: faces below the dip line get the clay material (n.paint with faces=).
budget: 5000 (a small game prop: mug and saucer, 48 sides so close-ups stay round)
"""
import nighty as n

n.settings(detail="low", size=0.15, collection="Mug")
glaze = n.surface("Mug Glaze", "ceramic", color="#24507d", roughness=0.12, wear=0.05, dirt=0.1)
clay = n.surface("Mug Clay", "ceramic", color="#b7a184", roughness=0.85, wear=0.05, dirt=0.25)
cream = n.surface("Saucer Glaze", "ceramic", color="#ece6da", roughness=0.15, wear=0.0, dirt=0.15)
coffee = n.surface("Mug Coffee", "ceramic", color="#2a170c", roughness=0.04, wear=0.0, dirt=0.0)
SIDES = 48
WELL = 0.008                # the saucer's well floor: the mug stands on it
DIP = 0.022                 # the glaze stops here: raw clay below

# saucer: foot ring, a sloped rim, a well for the mug (solid profile from the center out and back)
saucer = n.lathe(n.fillet([(0.0, 0.003, 0), (0.03, 0.003, 0), (0.032, 0.0, 0), (0.04, 0.0, 0),
                           (0.043, 0.004, 0.002), (0.074, 0.013, 0.004), (0.076, 0.017, 0.002),
                           (0.071, 0.0175, 0.002), (0.047, WELL + 0.002, 0.004), (0.043, WELL, 0.002),
                           (0.0, WELL, 0)], closed=False, count=2), segments=SIDES, name="Saucer", material=cream)

# mug: outside up from the foot (a point at the dip line), over the rounded lip, down the inside to the bottom
profile = n.fillet([(0.0, 0.003, 0), (0.033, 0.003, 0), (0.035, 0.0, 0), (0.04, 0.0, 0.002),
                    (0.042, 0.008, 0.005), (0.0422, DIP, 0), (0.043, 0.095, 0.003), (0.0365, 0.095, 0.003),
                    (0.0365, 0.014, 0.006), (0.0, 0.011, 0)], closed=False, count=2)
body = n.lathe(profile, segments=SIDES, name="Mug", material=glaze)
raw = [p.index for p in body.data.polygons
       if p.center.z < DIP - 1e-4 and (p.center.z < 0.0035 or p.center.length > 0.0375)]
n.paint(body, clay, faces=raw)   # the outside below the dip line and the underside
body.location = (0, 0, WELL)
drink = n.cylinder(0.0366, 0.004, segments=SIDES, at=(0, 0, WELL + 0.084), name="Coffee", material=coffee)
handle = n.pipe([(0.041, 0.0, WELL + 0.08), (0.068, 0.0, WELL + 0.077), (0.071, 0.0, WELL + 0.032),
                 (0.041, 0.0, WELL + 0.024)], radius=0.0065, bend=0.016, name="Handle", material=glaze)

parts = [saucer, body, drink, handle]
n.ground(parts)
n.center(parts, "XY")
