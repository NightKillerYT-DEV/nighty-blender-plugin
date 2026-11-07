# SPDX-License-Identifier: GPL-3.0-or-later
"""Fire hydrant (dry barrel, US street style) on a concrete pad: a lathed cast body with a ground flange, a bolted
breakaway flange, a nozzle section, a bolted bonnet with a pentagon operating nut, two hose nozzles and a pumper
nozzle with threaded collars, caps and pentagon nuts.
tags: fire hydrant, hydrant, street, city, urban, prop, environment, lathe, cast iron, red, realistic
Real size (0.75 m tall); one lathe profile for the whole casting, bolt rings with n.bolts_around; red paint
chipped on the flanges and nozzles, street grime low down, cream caps, dark iron bolts, a weathered concrete pad.
budget: 7500 (a street prop placed many times)
"""
import nighty as n

n.settings(detail="low", size=0.75, collection="Hydrant")
red = n.surface("Hydrant Red", "painted_metal", color="#a8251c", wear=0.5, dirt=0.6, size=0.4)
cream = n.surface("Hydrant Caps", "painted_metal", color="#d9d1bd", wear=0.5, dirt=0.5, size=0.4)
iron = n.surface("Hydrant Bolts", "iron", wear=0.2, dirt=0.4, size=0.3)
concrete = n.surface("Hydrant Pad", "concrete", color="#6a665f", wear=0.3, dirt=0.7)
parts = []

PAD = 0.05
pad = n.box((0.42, 0.42, PAD), at=(0, 0, PAD / 2), name="Pad")
n.chamfer(pad, 0.008)
n.paint(pad, concrete)
parts.append(pad)

# the casting: ground flange, lower barrel, breakaway flange, upper barrel, nozzle section, neck, bonnet flange, dome
Z0 = PAD - 0.001
profile = [(0.0, 0.0), (0.135, 0.0), (0.135, 0.02), (0.112, 0.026), (0.098, 0.032), (0.098, 0.1),
           (0.122, 0.104), (0.122, 0.128), (0.1, 0.134), (0.096, 0.14), (0.092, 0.33),
           (0.1, 0.342), (0.104, 0.36), (0.104, 0.44), (0.097, 0.456), (0.092, 0.47), (0.092, 0.515),
           (0.112, 0.52), (0.112, 0.544), (0.097, 0.55)] + \
          n.spline([(0.094, 0.556), (0.088, 0.6), (0.066, 0.638), (0.034, 0.656)], samples=3) + [(0.0, 0.658)]
body = n.lathe([(r, z + Z0) for r, z in profile], segments=32, name="Body")   # crisp cast edges, no bevel
n.paint(body, red)
parts.append(body)

# bolt rings on the ground, breakaway and bonnet flanges
# (game-light hex nuts: a 6-sided cylinder with a one-segment chamfer, copied around with n.radial)
for z, ring, count, name in ((0.02, 0.123, 4, "GroundBolts"), (0.128, 0.111, 6, "FlangeBolts"),
                             (0.544, 0.103, 6, "BonnetBolts")):
    nut = n.cylinder(0.0105, 0.009, segments=6, at=(ring, 0, Z0 + z + 0.0037), name=name)
    n.chamfer(nut, 0.0015)
    n.radial(nut, count, axis="Z")
    n.paint(nut, iron)
    parts.append(nut)

# operating nut on a weather shield
parts.append(n.cylinder(0.04, 0.008, at=(0, 0, Z0 + 0.66), name="WeatherShield", material=red))
nut = n.cylinder(0.023, 0.038, segments=5, at=(0, 0, Z0 + 0.682), name="OperatingNut")
n.bevel(nut, width=0.002)
n.paint(nut, iron)
parts.append(nut)


def nozzle(radius, length, axis, z, name):
    """A nozzle from the barrel's axis outward, a threaded collar, a cap with two lugs and a pentagon nut."""
    d = n.core.axis_vector(axis)

    def at(t):
        return (d.x * t, d.y * t, Z0 + z)
    pipe = n.cylinder(radius, length, axis=axis, at=at(length / 2), name=name)
    n.bevel(pipe, width=0.002)
    n.paint(pipe, red)
    collar = n.cylinder(radius * 1.13, 0.016, axis=axis, at=at(length - 0.012), name=name + "Collar")
    n.bevel(collar, width=0.0015)
    n.paint(collar, red)
    cap = n.cylinder(radius * 1.2, 0.03, axis=axis, at=at(length + 0.011), name=name + "Cap")
    n.chamfer(cap, 0.003)
    n.paint(cap, cream)
    side = n.core.axis_vector("Z")
    lugs = [n.box((0.024 if abs(d.x) > 0.5 else 0.012, 0.012 if abs(d.x) > 0.5 else 0.024, 0.012),
                  at=(d.x * (length + 0.011) + 0, d.y * (length + 0.011), Z0 + z + s * radius * 1.2), bevel=0.002)
            for s in (-1, 1)]
    lug = n.merge_parts(lugs, name=name + "Lugs", weld=False)
    n.paint(lug, cream)
    pent = n.cylinder(radius * 0.5, 0.026, segments=5, axis=axis, at=at(length + 0.037), name=name + "Nut")
    n.bevel(pent, width=0.0015)
    n.paint(pent, cream)
    return [pipe, collar, cap, lug, pent]


parts += nozzle(0.036, 0.13, "X", 0.40, "HoseRight")
parts += nozzle(0.036, 0.13, "-X", 0.40, "HoseLeft")
parts += nozzle(0.054, 0.14, "-Y", 0.39, "Pumper")

n.ground(parts)
n.center(parts, "XY")
