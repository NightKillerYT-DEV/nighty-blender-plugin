# SPDX-License-Identifier: GPL-3.0-or-later
"""Realistic oak barrel: a bulging body of 16 staves, a recessed planked head inside the chime, four iron hoops with
rivets, a wooden bung and a brass tap.
tags: barrel, cask, keg, wood, wooden, oak, container, prop, tavern, staves, hoops, tap, realistic
A lathe profile gives the bulge; thin fins that follow it cut the stave seams; the hoops are cones that hug the curve.
budget: 8000 (a medium game prop)
"""
import nighty as n

H = 0.9
n.settings(detail="low", size=H, collection="Barrel")
oak = n.surface("Barrel Oak", "wood", color="#7b4e2a", grain="Z", wear=0.2, dirt=0.5)
head = n.surface("Barrel Head", "wood", color="#7a4f2b", grain="X", wear=0.15, dirt=0.4)
iron = n.surface("Barrel Iron", "painted_metal", color="#232325", wear=0.2, dirt=0.35, size=0.5)  # blackened iron
brass = n.surface("Barrel Brass", "brass", wear=0.25, dirt=0.4)
outer = n.spline([(0.25, 0.0), (0.285, 0.2), (0.3, 0.45), (0.285, 0.7), (0.25, H)], samples=4)


def radius_at(z):
    """The body's outer radius at height z (from the profile points)."""
    for (r0, z0), (r1, z1) in zip(outer, outer[1:]):
        if z0 <= z <= z1:
            return r0 + (r1 - r0) * (z - z0) / (z1 - z0)
    return outer[-1][0]


# body: the bulge, the chime (stave ends standing above the heads) and recessed heads top and bottom
profile = [(0.0, 0.03), (0.226, 0.03), (0.226, 0.0)] + outer + [(0.226, H), (0.226, H - 0.03), (0.0, H - 0.03)]
body = n.lathe(profile, name="Body", material=oak)
n.mark_bevel(body)          # round the chime and the head edges; the stave seams cut next stay crisp

# stave seams: a thin fin that follows the bulge, copied around and cut in
seam = [(outer[0][0], -0.02)] + outer + [(outer[-1][0], H + 0.02)]  # past both ends: no faces left flat on flat
fin = n.extrude([(r - 0.004, z) for r, z in seam] + [(r + 0.02, z) for r, z in seam[::-1]], depth=0.004,
                plane="XZ", name="SeamCutter")
n.radial(fin, 16, axis="Z")
n.boolean_cut(body, fin)
for x in (-0.075, 0.075):   # the head is three boards
    chord = 2 * (0.226 ** 2 - x ** 2) ** 0.5 - 0.004
    n.boolean_cut(body, n.box((0.005, chord, 0.008), at=(x, 0, H - 0.03)))
n.bevel(body, width=0.006, limit="weight")

# iron hoops (truncated cones hugging the bulge), riveted
hoops, rivets = [], []
for zc in (0.075, 0.25, 0.65, 0.825):
    zb, zt = zc - 0.024, zc + 0.024
    hoop = n.cone(radius_at(zb) + 0.005, 0.048, top=radius_at(zt) + 0.005, at=(0, 0, zc))
    n.bevel(hoop, width=0.0025)
    hoops.append(hoop)
    rivet = n.dome(0.007, height=0.004, segments=8, axis="X", at=(radius_at(zc) + 0.005, 0, zc))  # tiny: 8 sides
    n.radial(rivet, 5, axis="Z")
    rivets.append(rivet)
hoops = n.merge_parts(hoops, name="Hoops", weld=False)
n.paint(hoops, iron)
rivets = n.merge_parts(rivets, name="Rivets", weld=False)
n.paint(rivets, iron)

# a wooden bung on the belly, a brass tap low on the front
bung = n.cylinder(0.026, 0.024, axis="-Y", at=(0, -radius_at(0.45) + 0.004, 0.45), name="Bung", material=head)
n.bevel(bung, width=0.003)
TZ = 0.16
ty = -radius_at(TZ)
tap_parts = [n.cylinder(0.022, 0.012, axis="-Y", at=(0, ty - 0.002, TZ)),             # flange on the stave
             n.cylinder(0.011, 0.07, axis="-Y", at=(0, ty - 0.04, TZ)),               # spout body
             n.cylinder(0.008, 0.035, at=(0, ty - 0.066, TZ - 0.022)),                # nozzle pointing down
             n.cylinder(0.006, 0.026, at=(0, ty - 0.05, TZ + 0.022)),                 # stem
             n.rounded_box((0.05, 0.012, 0.01), radius=0.004, at=(0, ty - 0.05, TZ + 0.037))]  # T handle
for p in tap_parts:
    n.bevel(p, width=0.0015)
tap = n.merge_parts(tap_parts, name="Tap", weld=False)
n.paint(tap, brass)

parts = [body, hoops, rivets, bung, tap]
n.ground(parts)
n.center(parts, "XY")
