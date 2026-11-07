# SPDX-License-Identifier: GPL-3.0-or-later
"""Car wheel (18 inch) with a performance tire: three circumferential grooves and notched shoulders, a 5-spoke
alloy rim (one extruded face with five filleted windows), lug nuts, a center cap, a cast brake disc on its hat
and a red brake caliper behind the spokes.
tags: wheel, tire, tyre, rim, car, vehicle, alloy, rubber, spokes, automotive, brake, caliper, realistic
Lathe profiles for the tire (grooves in the profile) and the rim barrel; the spokes are one n.extrude with holes
(no booleans); shoulder notches are one merged cutter repeated with n.radial. Black rubber, silver alloy, red
caliper, dark cast iron.
budget: 9500 (a hero vehicle part; four per car)
"""
import math

import nighty as n

n.settings(detail="low", size=0.7, collection="Wheel")
rubber = n.surface("Wheel Rubber", "rubber", wear=0.15, dirt=0.5, size=0.5)
alloy = n.surface("Wheel Alloy", "aluminum", wear=0.15, dirt=0.4, size=0.4)
chrome = n.surface("Wheel Chrome", "chrome")
iron = n.surface("Wheel Disc", "iron", wear=0.3, dirt=0.5, size=0.4)
red = n.surface("Wheel Caliper", "painted_metal", color="#c0181c", wear=0.15, dirt=0.4, size=0.3)
cap_mat = n.surface("Wheel Cap", "polymer", color="#1d1e21")
parts = []
SEG = 40                                   # sides of the round parts (a smooth silhouette at hero size)

# ---- tire: bead, sidewall, shoulder, tread with three grooves, mirrored back, closed along the bead
side = n.spline([(0.214, -0.1), (0.262, -0.109), (0.302, -0.106), (0.322, -0.097)], samples=2)
tread = [(0.331, -0.088), (0.333, -0.075), (0.333, -0.052), (0.324, -0.05), (0.324, -0.04), (0.333, -0.038),
         (0.333, -0.006), (0.324, -0.005), (0.324, 0.005), (0.333, 0.006), (0.333, 0.038), (0.324, 0.04),
         (0.324, 0.05), (0.333, 0.052), (0.333, 0.075), (0.331, 0.088)]
back = [(r, -y) for r, y in reversed(side)]
tire = n.lathe(side + tread + back + [(0.209, 0.05), (0.209, -0.05), (0.214, -0.1)], axis="Y", caps="none",
               segments=SEG, name="Tire")
notch = [n.box((0.011, 0.03, 0.02), at=(0.0, y, 0.338)) for y in (-0.074, 0.074)]
cutter = n.merge_parts(notch, name="Notches", weld=False)
n.radial(cutter, 30, axis="Y")
n.boolean_cut(tire, cutter)
n.paint(tire, rubber)
parts.append(tire)

# ---- rim barrel: flanges, bead seats and the drop well, a solid ring
outer = [(0.214, -0.106), (0.222, -0.104), (0.225, -0.098), (0.216, -0.093), (0.211, -0.088), (0.211, -0.068),
         (0.197, -0.054), (0.197, 0.03), (0.211, 0.048), (0.211, 0.088), (0.216, 0.093), (0.225, 0.098),
         (0.222, 0.104), (0.214, 0.106)]
inner = [(0.203, 0.106), (0.203, 0.06), (0.188, 0.046), (0.188, -0.046), (0.203, -0.06), (0.203, -0.106)]
barrel = n.lathe(outer + inner + [outer[0]], axis="Y", caps="none", segments=SEG, name="RimBarrel")
n.paint(barrel, alloy)
parts.append(barrel)


def window(k):
    """The opening between spoke k and k+1: straight sides along the spokes, an arc along the rim."""
    c = math.radians(k * 72 + 36)
    ri, ro = 0.08, 0.185
    ai = math.radians(36) - math.asin(0.024 / ri)          # spokes 48 mm wide at the hub ...
    ao = math.radians(36) - math.asin(0.017 / ro)          # ... 34 mm at the rim
    pts = [(ri, c - ai, 0.01), (ro, c - ao, 0.014), (ro, c - ao * 0.33, 0.0), (ro, c + ao * 0.33, 0.0),
           (ro, c + ao, 0.014), (ri, c + ai, 0.01)]
    return [(r * math.sin(a), r * math.cos(a), rad) for r, a, rad in pts]


FACE_Y = -0.07                               # the spoke face sits toward the outside (-Y)
face = n.extrude(n.circle_points(0.2035, count=SEG), depth=0.03, plane="XZ", holes=[window(k) for k in range(5)],
                 at=(0, FACE_Y, 0), name="Spokes")
n.chamfer(face, 0.002)
n.paint(face, alloy)
parts.append(face)
hub = n.cylinder(0.072, 0.02, axis="Y", at=(0, FACE_Y - 0.022, 0), segments=32, name="HubFace")
n.chamfer(hub, 0.003)
n.paint(hub, alloy)
parts.append(hub)
HUB_FRONT = FACE_Y - 0.032
lug = n.cylinder(0.0105, 0.016, segments=6, axis="-Y", at=(0.0, HUB_FRONT - 0.0075, 0.052), name="LugNuts")
n.chamfer(lug, 0.0015)
n.radial(lug, 5, axis="Y")
n.paint(lug, chrome)
parts.append(lug)
parts.append(n.dome(0.032, height=0.012, axis="-Y", at=(0, HUB_FRONT + 0.001, 0), segments=24, name="CenterCap",
                    material=cap_mat))

# ---- brake: cast disc on a hat, caliper (an arc-shaped block) straddling the disc behind the spokes
disc = n.tube(0.165, 0.026, inner=0.09, axis="Y", segments=SEG, at=(0, -0.012, 0), name="BrakeDisc")
n.chamfer(disc, 0.0015)
n.paint(disc, iron)
parts.append(disc)
hat = n.cylinder(0.092, 0.044, axis="Y", at=(0, -0.034, 0), segments=32, name="DiscHat")   # bolted to the hub
n.chamfer(hat, 0.002)
n.paint(hat, iron)
parts.append(hat)
arc = [math.radians(a) for a in (28, 40, 52, 64, 76)]
cal = ([(0.183 * math.sin(a), 0.183 * math.cos(a), 0.0) for a in arc] +
       [(0.128 * math.sin(a), 0.128 * math.cos(a), 0.0) for a in reversed(arc)])
caliper = n.extrude(cal, depth=0.07, plane="XZ", at=(0, -0.012, 0), name="Caliper")
n.chamfer(caliper, 0.004)
n.paint(caliper, red)
parts.append(caliper)

n.ground(parts)
n.center(parts, "XY")
