# SPDX-License-Identifier: GPL-3.0-or-later
"""Industrial pipe run (DN100 gas line): a pipe with a long-radius elbow, gasketed flange joints with hex nuts on
both sides, blind flanges on the ends, an OS&Y gate valve (bolted bonnet, yoke, red hand wheel, rising stem),
a pressure gauge on a nipple and a pipe support with a U-bolt.
tags: pipe, pipes, valve, gate valve, industrial, factory, plumbing, flange, elbow, wheel, gauge, environment, prop, realistic
Real sizes (1.2 m run); one n.pipe for the run, a joint() helper for every flange pair, game-light hex nuts
(6-sided, one chamfer) copied with n.radial; yellow line paint, dark cast valve, red wheel, steel hardware.
budget: 12000 (an environment set piece)
"""
import math

import nighty as n

n.settings(detail="low", size=1.2, collection="PipeValve")
line = n.surface("Pipe Yellow", "painted_metal", color="#b8952e", wear=0.35, dirt=0.6, size=0.8)
cast = n.surface("Valve Iron", "painted_metal", color="#2e3338", wear=0.35, dirt=0.5, size=0.6)
red = n.surface("Valve Wheel", "painted_metal", color="#a8261d", wear=0.4, dirt=0.4, size=0.5)
grey = n.surface("Support Grey", "painted_metal", color="#4b5055", wear=0.3, dirt=0.6, size=0.8)
steel = n.surface("Pipe Steel", "steel", wear=0.2, dirt=0.5, size=0.4)
rubber = n.surface("Pipe Gasket", "rubber")
dial = n.surface("Gauge Dial", "painted", color="#ece8dc", wear=0.0, dirt=0.1, roughness=0.5)
glass = n.surface("Gauge Glass", "glass")
parts = []

R, Z = 0.057, 0.32                     # pipe radius (DN100) and height of the run
X_END, X_ELBOW, Z_TOP = -0.84, 0.25, 1.05
parts.append(n.pipe([(X_END, 0, Z), (X_ELBOW, 0, Z), (X_ELBOW, 0, Z_TOP)], radius=R, bend=0.16, name="Pipe",
                    material=line))


def nuts(center, axis, ring, count=6, radius=0.0105, name="Nuts", material=steel):
    """Hex nuts standing on a face (center), facing axis, around the pipe axis."""
    d = n.core.axis_vector(axis)
    u = d.orthogonal().normalized()
    c = [center[i] + d[i] * 0.0042 for i in range(3)]
    nut = n.cylinder(radius, 0.009, segments=6, axis=axis, at=tuple(c[i] + u[i] * ring for i in range(3)), name=name)
    n.chamfer(nut, 0.0015)
    n.radial(nut, count, axis=axis, center=center)
    n.paint(nut, material)
    return nut


def joint(c, axis, name, mat_a=line, mat_b=line):
    """A flange pair with a rubber gasket between, centered at c along axis; nuts on both outer faces."""
    d = n.core.axis_vector(axis)
    at = lambda t: tuple(c[i] + d[i] * t for i in range(3))   # noqa: E731
    out = []
    for t, mat, nm in ((-0.0105, mat_a, "A"), (0.0105, mat_b, "B")):
        f = n.cylinder(0.11, 0.02, axis=axis, at=at(t), name=name + nm)
        n.chamfer(f, 0.002)
        n.paint(f, mat)
        out.append(f)
    out.append(n.cylinder(0.095, 0.003, axis=axis, at=at(0), name=name + "Gasket", material=rubber))
    out.append(nuts(at(0.0205), axis, 0.085, name=name + "NutsB"))
    out.append(nuts(at(-0.0205), "-" + axis.lstrip("+-") if not axis.startswith("-") else axis[1:], 0.085,
                    name=name + "NutsA"))
    return out


XA, XB, XV = -0.61, -0.29, -0.45       # valve joints and valve center
parts += joint((X_END, 0, Z), "X", "EndFlange")                 # blind flange closing the run
parts += joint((XA, 0, Z), "X", "JointA", line, cast)
parts += joint((XB, 0, Z), "X", "JointB", cast, line)
parts += joint((X_ELBOW, 0, Z_TOP), "Z", "TopFlange")           # blind flange on the riser

# ---- OS&Y gate valve: bulbous body, neck, bolted bonnet, bonnet, yoke, hand wheel, rising stem
body = n.lathe(n.spline([(0.07, -0.14), (0.088, -0.09), (0.104, 0.0), (0.088, 0.09), (0.07, 0.14)], samples=3),
               axis="X", at=(XV, 0, Z), name="ValveBody")
n.paint(body, cast)
parts.append(body)
neck = n.cylinder(0.072, 0.13, at=(XV, 0, Z + 0.065), name="ValveNeck")
n.bevel(neck, width=0.003)
n.paint(neck, cast)
parts.append(neck)
bflange = n.cylinder(0.096, 0.022, at=(XV, 0, Z + 0.141), name="BonnetFlange")
n.chamfer(bflange, 0.002)
n.paint(bflange, cast)
parts.append(bflange)
parts.append(nuts((XV, 0, Z + 0.152), "Z", 0.08, name="BonnetNuts"))
bonnet = n.lathe([(0.0, 0.0), (0.07, 0.0), (0.066, 0.03), (0.05, 0.09), (0.044, 0.12), (0.0, 0.12)],
                 at=(XV, 0, Z + 0.151), name="Bonnet")
n.paint(bonnet, cast)
parts.append(bonnet)
YT = Z + 0.27                           # top of the bonnet: the yoke starts here
yoke = [n.box((0.024, 0.026, 0.23), at=(XV, s * 0.05, YT + 0.105), bevel=0.003) for s in (-1, 1)]
yoke.append(n.box((0.034, 0.13, 0.03), at=(XV, 0, YT + 0.225), bevel=0.004))
yoke.append(n.cylinder(0.032, 0.05, at=(XV, 0, YT + 0.245)))
parts.append(n.merge_parts(yoke, name="Yoke", weld=False))
n.paint("Yoke", cast)
WZ = YT + 0.292                         # hand wheel height
rim = n.torus(0.14, 0.012, at=(XV, 0, WZ), name="WheelRim")
spokes = [n.cylinder(0.009, 0.12, axis="X", at=(XV + 0.075 * math.cos(a), 0.075 * math.sin(a), WZ),
                     rot=(0, 0, math.degrees(a))) for a in [k * 2 * math.pi / 5 for k in range(5)]]
hub = n.cylinder(0.03, 0.04, at=(XV, 0, WZ))
n.bevel(hub, width=0.003)
wheel = n.merge_parts([rim, hub] + spokes, name="HandWheel", weld=False)
n.paint(wheel, red)
parts.append(wheel)
parts.append(n.cylinder(0.011, 0.44, at=(XV, 0, YT + 0.2), name="Stem", material=steel))   # rises above the wheel

# ---- pressure gauge on a nipple on top of the pipe
GX, GZ = -0.06, Z + R + 0.1
parts.append(n.cylinder(0.011, 0.06, at=(GX, 0, Z + R + 0.027), name="GaugeNipple", material=steel))
parts.append(n.cylinder(0.016, 0.014, segments=6, at=(GX, 0, Z + R + 0.04), name="GaugeNut", material=steel))
housing = n.cylinder(0.046, 0.026, axis="-Y", at=(GX, 0, GZ), name="GaugeHousing")
n.bevel(housing, width=0.003)
n.paint(housing, steel)
parts.append(housing)
parts.append(n.cylinder(0.04, 0.002, axis="-Y", at=(GX, -0.0128, GZ), name="GaugeDial", material=dial))
parts.append(n.box((0.003, 0.0012, 0.032), at=(GX + 0.008, -0.0144, GZ + 0.006), rot=(0, 30, 0), name="GaugeNeedle",
                   material=red))
parts.append(n.cylinder(0.041, 0.0016, axis="-Y", at=(GX, -0.0158, GZ), name="GaugeGlass", material=glass))

# ---- pipe support: base plate with anchor nuts, post, cradle saddle, U-bolt with nuts
SX = -0.74
base = n.box((0.22, 0.22, 0.02), at=(SX, 0, 0.01), name="SupportBase")
n.chamfer(base, 0.003)
n.paint(base, grey)
parts.append(base)
anchors = n.cylinder(0.0105, 0.009, segments=6, at=(SX + 0.08, 0.08, 0.0242), name="AnchorNuts")
n.chamfer(anchors, 0.0015)
n.radial(anchors, 4, axis="Z", center=(SX, 0, 0))
n.paint(anchors, steel)
parts.append(anchors)
SADDLE_TOP = Z - R + 0.012
post = n.box((0.08, 0.08, SADDLE_TOP - 0.03 - 0.02), at=(SX, 0, 0.02 + (SADDLE_TOP - 0.05) / 2), name="SupportPost")
n.chamfer(post, 0.003)
n.paint(post, grey)
parts.append(post)
saddle = n.box((0.11, 0.17, 0.03), at=(SX, 0, SADDLE_TOP - 0.015), name="Saddle")
n.boolean_cut(saddle, n.cylinder(R + 0.0005, 0.2, axis="X", at=(SX, 0, Z)))      # a cradle that hugs the pipe
n.chamfer(saddle, 0.002)
n.paint(saddle, grey)
parts.append(saddle)
A = R + 0.007
parts.append(n.handle(2 * A, A + 0.045, 0.006, axis="Z", along="Y", at=(SX, 0, Z - 0.045), name="UBolt",
                      material=steel))
for s in (-1, 1):
    nut = n.cylinder(0.0095, 0.008, segments=6, at=(SX, s * A, SADDLE_TOP + 0.0038), name="UBoltNut")
    n.chamfer(nut, 0.0012)
    n.paint(nut, steel)
    parts.append(nut)

n.ground(parts)
n.center(parts, "XY")
