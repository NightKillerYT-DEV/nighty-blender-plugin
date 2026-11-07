# SPDX-License-Identifier: GPL-3.0-or-later
"""Realistic articulated desk lamp: a weighted base with a rubber foot and a rocker switch, twin chrome rods between
tension-knob joints, a coil spring, an enamelled shade with a rolled rim, white inside, a glowing bulb, and a cable.
tags: lamp, desk lamp, light, office, interior, articulated, spring, anglepoise, emissive, prop, realistic
About 0.45 m tall; the head is built upright around its joint, then tilted and moved onto the arm. The shade wall is
4 mm thick (realistic wear reads thinner walls as edges); its inside faces get the white enamel (n.paint faces=).
budget: 5500 (a small game prop)
"""
import math

import nighty as n

n.settings(detail="low", size=0.45, collection="DeskLamp")
enamel = n.surface("Lamp Enamel", "painted_metal", color="#8f231d", wear=0.08, dirt=0.15, size=0.25)
white = n.surface("Lamp Inside", "painted_metal", color="#efece4", wear=0.0, dirt=0.1, size=0.25)
chrome = n.surface("Lamp Chrome", "chrome", wear=0.05, dirt=0.1, size=0.25)
dark = n.surface("Lamp Dark", "polymer", color="#202124", wear=0.1, dirt=0.15, size=0.25)
rubber = n.surface("Lamp Rubber", "rubber", wear=0.0, dirt=0.2, size=0.25)
bulb_mat = n.surface("Lamp Bulb", "glow", color="#ffd9a0", glow=14)

# ---- base: a rubber foot, the round enamelled weight, a bracket for the arm, a rocker switch
foot = n.lathe([(0.0, 0.0), (0.08, 0.0), (0.081, 0.004), (0.0, 0.004)], name="Foot", material=rubber)
base = n.lathe(n.fillet([(0.0, 0.004, 0), (0.082, 0.004, 0.002), (0.082, 0.02, 0.008), (0.05, 0.034, 0.01),
                         (0.0, 0.036, 0)], closed=False, count=2), name="Base", material=enamel)
bracket = n.box((0.026, 0.05, 0.034), at=(0, 0, 0.05), name="Bracket")
n.bevel(bracket, width=0.004)
n.paint(bracket, enamel)
switch = n.box((0.016, 0.022, 0.009), at=(0.052, -0.025, 0.03), rot=(0, -25, 0), name="Switch")
n.bevel(switch, width=0.0025)
n.paint(switch, dark)

A = (0.0, 0.0, 0.058)      # base joint
B = (0.085, 0.0, 0.33)     # elbow
C = (0.3, 0.0, 0.36)       # head joint


def joint(p, name):
    """A hub between the twin rods, with a tension knob on the outside."""
    hub = n.cylinder(0.011, 0.034, axis="Y", at=p)
    n.chamfer(hub, 0.0015)
    knob = n.cylinder(0.009, 0.012, axis="Y", at=(p[0], p[1] - 0.023, p[2]))   # on a short axle out of the hub
    n.chamfer(knob, 0.0015)
    j = n.merge_parts([hub, knob], name=name, weld=False)
    n.paint(j, dark)
    return j


def rods(p, q, name):
    rs = [n.cylinder(0.004, 1.0, axis="X") for _ in (0, 1)]
    d = (q[0] - p[0], q[2] - p[2])
    length = math.hypot(*d)
    angle = math.degrees(math.atan2(d[1], d[0]))
    for r, y in zip(rs, (-0.013, 0.013)):
        r.scale = (length, 1.0, 1.0)
        r.rotation_euler = (0, math.radians(-angle), 0)
        r.location = ((p[0] + q[0]) / 2, y, (p[2] + q[2]) / 2)
    n.apply_transforms(rs)
    m = n.merge_parts(rs, name=name, weld=False)
    n.paint(m, chrome)
    return m


joints = [joint(A, "JointBase"), joint(B, "JointElbow"), joint(C, "JointHead")]
lower = rods(A, B, "LowerArm")
upper = rods(B, C, "UpperArm")

# ---- a coil spring alongside the lower arm, hooked onto the rods at both ends
coil, turns, steps = 0.0075, 8, 12
pts = []
for k in range(turns * steps + 1):
    t = k / float(turns * steps)
    a = 2 * math.pi * turns * t
    cx = A[0] + (B[0] - A[0]) * (0.22 + 0.56 * t)
    cz = A[2] + (B[2] - A[2]) * (0.22 + 0.56 * t)
    pts.append((cx + coil * math.cos(a), -0.028 + coil * math.sin(a), cz))
spring = n.pipe(pts, radius=0.0012, bend=0, segments=6, name="Spring")          # 1 mm wire: 6 sides read round
hooks = []
for t, end in ((0.22, pts[0]), (0.78, pts[-1])):    # from the coil's end to its axis, then across onto the rod
    ax, az = A[0] + (B[0] - A[0]) * t, A[2] + (B[2] - A[2]) * t
    hooks.append(n.pipe([end, (ax, -0.028, az), (ax, -0.013, az)], radius=0.0012, bend=0.003, segments=6))
spring = n.merge_parts([spring] + hooks, name="Spring", weld=False)
n.paint(spring, chrome)

# ---- head, built upright at the origin (the joint), then tilted down and forward
out = n.spline([(0.026, -0.005), (0.031, -0.03), (0.058, -0.085), (0.082, -0.133)], samples=2)
shade = n.lathe([(0.0, -0.005)] + out + [(0.085, -0.137), (0.081, -0.139)]          # rolled rim
                + [(r - 0.004, z - 0.002) for r, z in out[::-1]] + [(0.0, -0.009)], name="Shade")
inside = [f.index for f in shade.data.polygons if f.normal.z < -0.2 and f.center.z < -0.012]
n.paint(shade, enamel)
n.paint(shade, white, faces=inside)
cap = n.cylinder(0.014, 0.034, at=(0, 0, -0.024), name="Socket")   # its top hidden inside the shade's wall
n.chamfer(cap, 0.0015)
n.paint(cap, dark)
bulb = n.sphere(0.024, segments=16, at=(0, 0, -0.06), name="Bulb", material=bulb_mat)
knob = n.cylinder(0.011, 0.036, axis="Y", at=(0, 0, 0.0), name="HeadHub")
n.chamfer(knob, 0.0015)
n.paint(knob, dark)
head = n.merge_parts([shade, cap, bulb, knob], name="Head", weld=False)
head.rotation_euler = (math.radians(-12), math.radians(-38), 0)  # down, forward and a little toward the front
head.location = C

# ---- the cable from the back of the base
cable = n.pipe([(-0.06, 0.0, 0.012), (-0.11, 0.0, 0.006), (-0.17, 0.05, 0.004), (-0.22, 0.06, 0.004)],
               radius=0.003, bend=0.02, segments=12, name="Cable", material=dark)

parts = n.objects()
n.ground(parts)
n.center(parts, "XY")
