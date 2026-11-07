# SPDX-License-Identifier: GPL-3.0-or-later
"""Park bench: cast-iron side frames (and a middle one) with recessed panels and a round window, painted dark
green and chipped, oak seat and back slats with carriage bolts, scrolled armrests, bolted foot plates.
tags: bench, park bench, seat, furniture, outdoor, street, wood, cast iron, city prop, realistic
1.5 m long, seat at 0.45 m; one side profile makes every frame (front leg, seat rail, leaning back support).
budget: 7000 (a medium street prop)
"""
import math

import nighty as n

n.settings(detail="low", size=1.5, collection="Bench")
iron = n.surface("Bench Iron", "painted_metal", color="#1f3127", wear=0.1, dirt=0.4, size=0.6)
oak = n.surface("Bench Oak", "wood", color="#94693f", grain="X", wear=0.2, dirt=0.45)
steel = n.surface("Bench Bolts", "steel", wear=0.2, dirt=0.4, size=0.5)

FX = 0.66                        # the end frames' x (the middle frame stands at 0)
SEAT_Z, ST = 0.43, 0.028         # top of the seat rail, slat thickness
# side profile (y, z, corner radius): front leg, seat rail, back leg rising into the back support (front = -Y)
# (corners rounder than the panel inset below, so the inset never folds)
profile = [(-0.27, 0.0, 0.01), (-0.19, 0.0, 0.01), (-0.175, 0.37, 0.03), (0.125, 0.37, 0.03), (0.115, 0.0, 0.01),
           (0.195, 0.0, 0.01), (0.37, 0.83, 0.02), (0.31, 0.85, 0.02), (0.17, SEAT_Z, 0.03), (-0.26, SEAT_Z, 0.012),
           (-0.235, 0.37, 0.01)]
frames = []
for x in (-FX, 0.0, FX):
    f = n.extrude(profile, depth=0.04, plane="YZ", at=(x, 0, 0))
    for side in ("+X", "-X"):
        n.inset(f, side, amount=0.007, depth=-0.004)         # a recessed panel inside a raised cast rim
    n.hole(f, 0.03, at=(x, 0.29, 0.69), axis="X")          # then a round window through the back support
    n.bevel(f, width=0.003)
    frames.append(f)
frames = n.merge_parts(frames, name="Frames", weld=False)
n.paint(frames, iron)

# foot plates under the four outer legs, bolted down
feet, foot_bolts = [], []
for x in (-FX, FX):
    for y in (-0.23, 0.155):
        feet.append(n.box((0.07, 0.11, 0.012), at=(x, y, 0.006), bevel=0.003))
        foot_bolts.append(n.bolt(0.008, kind="hex", axis="Z", at=(x, y - 0.038, 0.012)))
feet = n.merge_parts(feet, name="FootPlates", weld=False)
n.paint(feet, iron)
foot_bolts = n.merge_parts(foot_bolts, name="FootBolts", weld=False)
n.paint(foot_bolts, steel)

# seat: four slats lying on the seat rails, each board a little different
seat = n.planks((1.5, 0.43), count=4, thickness=ST, gap=0.012, plane="XY", at=(0, -0.045, SEAT_Z + ST / 2 - 0.001),
                bevel=0.004, seed=5, name="SeatSlats")
n.paint(seat, oak)

# back: three slats on the leaning back support (sunk 1 mm into it so they really touch)
dy, dz = 0.37 - 0.17, 0.83 - SEAT_Z               # the support's front edge direction
length = math.hypot(dy, dz)
ang = math.degrees(math.atan2(dy, dz))
normal = (-dz / length, dy / length)               # toward the front
back = []
for t in (0.38, 0.6, 0.82):
    y = 0.17 + dy * t + normal[0] * (ST / 2 - 0.001)
    z = SEAT_Z + dz * t + normal[1] * (ST / 2 - 0.001)
    back.append(n.box((1.5, ST, 0.085), at=(0, y, z), rot=(-ang, 0, 0), bevel=0.004))
back = n.merge_parts(back, name="BackSlats", weld=False)
n.paint(back, oak)

# armrests: a flat cast bar from the back support curling down onto the front of the seat rail
arms = []
for x in (-FX, FX):
    arms.append(n.pipe([(x, 0.285, 0.64), (x, -0.16, 0.64), (x, -0.245, 0.58), (x, -0.25, SEAT_Z + 0.004)],
                       radius=0.018, bend=0.07))
arms = n.merge_parts(arms, name="Armrests", weld=False)
n.paint(arms, iron)

# carriage bolts: two per slat over every frame
pts = []
for x in (-FX, 0.0, FX):
    pts += [(x, y, SEAT_Z + ST - 0.001) for y in (-0.21, -0.1, 0.01, 0.12)]
bolts = n.rivets(pts, radius=0.0075, axis="Z", segments=8, name="SeatBolts")   # tiny heads: 8 sides is plenty
n.paint(bolts, steel)
back_pts = []
for t in (0.38, 0.6, 0.82):
    y = 0.17 + dy * t + normal[0] * (ST - 0.001)
    z = SEAT_Z + dz * t + normal[1] * (ST - 0.001)
    back_pts += [(x, y, z) for x in (-FX, 0.0, FX)]
back_bolts = n.rivets(back_pts, radius=0.0075, axis=(0, normal[0], normal[1]), segments=8, name="BackBolts")
n.paint(back_bolts, steel)

parts = [frames, feet, foot_bolts, seat, back, arms, bolts, back_bolts]
n.ground(parts)
n.center(parts, "XY")
