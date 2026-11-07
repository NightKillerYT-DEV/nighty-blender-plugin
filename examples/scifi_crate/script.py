# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized sci-fi loot crate: a chunky white body in dark corner bumpers, grey side plates with glowing grilles,
a glowing seam under an overhanging lid with a sunk top, a raised plate and an emblem, amber latches, end handles.
tags: scifi, sci-fi, crate, box, container, cargo, loot, supply drop, chest, storage, prop, emissive, stylized
Layers step out of each other (body, bumpers, side plates, lid overhang, top plate, emblem), so every side reads;
clear color blocks (white, dark, grey, amber) with a purple glow behind the grilles and in the seam.
budget: 6000 (a hero loot prop; one Roblox mesh)
"""
import nighty as n

n.settings(detail="low", size=0.8, collection="SciFiCrate")
white = n.surface("Crate White", "plastic", color="#eef1f5", style="stylized")
dark = n.surface("Crate Dark", "plastic", color="#2b2f37", style="stylized")
grey = n.surface("Crate Grey", "plastic", color="#9aa6b5", style="stylized")
amber = n.surface("Crate Amber", "plastic", color="#ffb020", style="stylized")
glow = n.surface("Crate Glow", "glow", color="#8a3dff", glow=5)
parts = []


def keep(obj):
    parts.append(obj)
    return obj


SKID, W, D, H = 0.03, 0.76, 0.56, 0.36      # gap under the body, body width / depth / height
TOP = SKID + H                               # top of the body

# ---- body: a chunky white box, lifted off the ground by its corner bumpers
body = n.box((W, D, H), at=(0, 0, SKID + H / 2), name="Body")
n.bevel(body, width=0.012, segments=4, profile=0.55)
n.paint(body, white)
keep(body)

# ---- dark corner bumpers standing out of the body's corners; they are the feet too
guards = []
for sx in (-1, 1):
    for sy in (-1, 1):
        g = n.box((0.11, 0.11, TOP - 0.004), at=(sx * (W / 2 - 0.04), sy * (D / 2 - 0.04), (TOP - 0.004) / 2))
        n.bevel(g, width=0.012, segments=4, profile=0.55)
        guards.append(g)
keep(n.merge_parts(guards, name="CornerGuards", weld=False))
n.paint("CornerGuards", dark)

# ---- grey side plates on the long sides, each with a recessed grille and light behind the bars
for s in (-1, 1):
    side = "-Y" if s < 0 else "+Y"
    plate = n.box((0.46, 0.02, 0.22), at=(0, s * (D / 2 + 0.006), SKID + 0.17), name="SidePlate")
    n.mark_bevel(plate)
    bars = n.grille(plate, side, center=(0.0, SKID + 0.17), size=(0.36, 0.13), count=4, depth=0.012,
                    name="GrilleBars")
    n.bevel(plate, width=0.005, segments=2, limit="weight")
    n.paint(plate, grey)
    keep(plate)
    n.paint(bars, dark)
    keep(bars)
    keep(n.box((0.354, 0.003, 0.124), at=(0, s * (D / 2 + 0.0047), SKID + 0.17), name="GrilleLight",
               material=glow))

# ---- grey end plates with three vents, a handle on each
for s in (-1, 1):
    side = "+X" if s > 0 else "-X"
    end = n.box((0.02, 0.3, 0.24), at=(s * (W / 2 + 0.006), 0, SKID + 0.18), name="EndPlate")
    n.mark_bevel(end)
    n.vents(end, side, center=(0.0, SKID + 0.12), count=3, slot=(0.2, 0.016), gap=0.012, depth=0.008)
    n.bevel(end, width=0.005, segments=2, limit="weight")
    n.paint(end, grey)
    keep(end)
    keep(n.handle(0.2, 0.05, 0.011, axis=side, at=(s * (W / 2 + 0.016), 0, SKID + 0.25), name="Handle",
                  material=dark))

# ---- glowing seam, then an overhanging dark lid with a sunk top, a raised white plate and an emblem
keep(n.box((W - 0.02, D - 0.02, 0.016), at=(0, 0, TOP + 0.007), name="GlowSeam", material=glow))
LID = 0.095
lid = n.box((W + 0.04, D + 0.04, LID), at=(0, 0, TOP + 0.013 + LID / 2), name="Lid")
n.mark_bevel(lid)                                     # chunky outline; the sunk top's edges stay crisp
n.inset(lid, "+Z", amount=0.05, depth=-0.012)
n.bevel(lid, width=0.014, segments=4, profile=0.55, limit="weight")
n.paint(lid, dark)
keep(lid)
LID_TOP = TOP + 0.013 + LID - 0.012                   # floor of the sunk top
top_plate = n.box((0.5, 0.32, 0.024), at=(0, 0, LID_TOP + 0.01), name="TopPlate")
n.bevel(top_plate, width=0.008, segments=2, profile=0.55)
n.paint(top_plate, white)
keep(top_plate)
PT = LID_TOP + 0.022                                   # top of the white plate
keep(n.tube(0.085, 0.012, inner=0.066, at=(0, 0, PT + 0.004), name="EmblemRing", material=amber))
keep(n.cylinder(0.064, 0.008, at=(0, 0, PT + 0.002), name="EmblemGlow", material=glow))
CHEVRON = [(0.0, 0.05), (0.03, 0.05), (0.07, 0.0), (0.03, -0.05), (0.0, -0.05), (0.04, 0.0)]
for sx in (-1, 1):   # amber chevrons either side of the emblem, pointing out (mirrored outline for the left one)
    pts = [(sx * x, y) for x, y in CHEVRON]
    chev = n.extrude(pts if sx > 0 else pts[::-1], depth=0.01, plane="XY", at=(sx * 0.12, 0, PT + 0.003),
                     name="Chevron")
    n.chamfer(chev, 0.0015)
    n.paint(chev, amber)
    keep(chev)

# ---- amber latches bridging the seam on the long sides
lat = []
for sy in (-1, 1):
    for x in (-0.3, 0.3):
        l = n.box((0.07, 0.03, 0.1), at=(x, sy * (D / 2 + 0.016), TOP + 0.005))
        n.bevel(l, width=0.006, segments=2, profile=0.55)
        lat.append(l)
keep(n.merge_parts(lat, name="Latches", weld=False))
n.paint("Latches", amber)

n.ground(parts)
n.center(parts, "XY")
