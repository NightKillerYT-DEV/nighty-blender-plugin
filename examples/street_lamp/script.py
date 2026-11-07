# SPDX-License-Identifier: GPL-3.0-or-later
"""Victorian street lamp: a bolted plinth, a square cast base with recessed panels and an inspection door, a
turned pole with collars, a ladder bar with ball ends, and a four-pane lantern with a pyramid roof and finial.
tags: street lamp, lamp post, lamppost, light, city, street, outdoor, victorian, emissive, prop, cast iron, realistic
3.9 m tall; the pole is one lathe profile (collars are bumps in it), square parts are 4-sided cones turned 45 deg.
budget: 3800 (a tall street prop)
"""
import nighty as n

n.settings(detail="low", size=3.9, collection="StreetLamp")
iron = n.surface("Lamp Iron", "painted_metal", color="#171a1b", wear=0.12, dirt=0.45, size=1.2)
steel = n.surface("Lamp Bolts", "steel", wear=0.2, dirt=0.5, size=0.6)
glow = n.surface("Lamp Glass", "glow", color="#ffc477", glow=2.5)    # low glow: the warm color still shows


def square(bottom, top, z0, z1, name):
    """A square frustum standing from z0 to z1 (sides bottom / top meters), axis-aligned."""
    return n.cone(bottom * 0.7071, z1 - z0, top=top * 0.7071, segments=4, rot=(0, 0, 45), at=(0, 0, (z0 + z1) / 2),
                  name=name)


# plinth with a bolt in each corner, then the square base with a recessed panel on every side
plinth = n.box((0.46, 0.46, 0.08), at=(0, 0, 0.04), name="Plinth")
n.chamfer(plinth, 0.01)
bolts = n.merge_parts([n.bolt(0.014, kind="hex", axis="Z", at=(x, y, 0.08)) for x in (-0.18, 0.18)
                       for y in (-0.18, 0.18)], name="PlinthBolts", weld=False)
base = n.box((0.3, 0.3, 0.72), at=(0, 0, 0.08 + 0.36), name="Base")
for side in ("+X", "-X", "+Y", "-Y"):
    n.inset(base, side, amount=0.035, depth=-0.01)
n.bevel(base, width=0.006)
door = n.rounded_box((0.17, 0.016, 0.42), radius=0.006, at=(0, -0.143, 0.46), name="Door")   # in the front panel
hinges = n.merge_parts([n.cylinder(0.009, 0.06, at=(-0.085, -0.151, z)) for z in (0.33, 0.59)], name="Hinges",
                       weld=False)
keyhole = n.bolt(0.011, kind="socket", axis="-Y", at=(0.06, -0.151, 0.46), name="DoorLock")
cap = square(0.36, 0.3, 0.8, 0.86, "BaseCap")
n.bevel(cap, width=0.006)
shoulder = square(0.3, 0.16, 0.86, 0.98, "BaseShoulder")
n.bevel(shoulder, width=0.005)

# the pole: one turned profile (radius, height) with collars, tapering up to the lantern seat
pole = n.lathe([(0.0, 0.97), (0.07, 0.97), (0.085, 1.0), (0.085, 1.05), (0.07, 1.09), (0.066, 1.6), (0.078, 1.63),
                (0.078, 1.68), (0.062, 1.71), (0.052, 2.75), (0.066, 2.78), (0.066, 2.84), (0.05, 2.87),
                (0.046, 3.18), (0.075, 3.2), (0.075, 3.23), (0.0, 3.23)], name="Pole")
n.bevel(pole, width=0.004)
ladder = n.cylinder(0.016, 0.62, axis="Y", at=(0, 0, 2.81), name="LadderBar")
balls = n.merge_parts([n.sphere(0.03, at=(0, y, 2.81)) for y in (-0.31, 0.31)], name="LadderBalls", weld=False)

# lantern: a tapered seat, four glowing panes between corner posts and frame rails, a pyramid roof, a finial
seat = square(0.1, 0.3, 3.23, 3.33, "LanternSeat")
n.bevel(seat, width=0.004)
glass = n.box((0.27, 0.27, 0.38), at=(0, 0, 3.33 + 0.19), name="Glass")
frame = []
for x in (-0.14, 0.14):
    for y in (-0.14, 0.14):
        frame.append(n.box((0.024, 0.024, 0.4), at=(x, y, 3.52), bevel=0.003))
for z in (3.345, 3.7):
    for s in (-1, 1):
        # rails end inside the corner posts; X and Y rails differ in length and height so no faces coincide
        frame.append(n.box((0.29, 0.018, 0.03), at=(0, s * 0.14, z), bevel=0.003))
        frame.append(n.box((0.018, 0.28, 0.028), at=(s * 0.14, 0, z), bevel=0.003))
frame = n.merge_parts(frame, name="LanternFrame", weld=False)
roof = square(0.44, 0.05, 3.72, 3.9, "Roof")
n.bevel(roof, width=0.005)
eave = square(0.42, 0.42, 3.71, 3.725, "Eave")
finial = n.lathe([(0.0, 3.9), (0.03, 3.9), (0.035, 3.93), (0.022, 3.96), (0.03, 3.99), (0.0, 4.06)], name="Finial")

n.paint([plinth, base, door, hinges, cap, shoulder, pole, ladder, balls, seat, frame, roof, eave, finial], iron)
n.paint([bolts, keyhole], steel)
n.paint(glass, glow)

parts = [plinth, bolts, base, door, hinges, keyhole, cap, shoulder, pole, ladder, balls, seat, glass, frame, roof,
         eave, finial]
n.ground(parts)
n.center(parts, "XY")
