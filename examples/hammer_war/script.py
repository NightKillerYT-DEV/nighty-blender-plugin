# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized war hammer: an oversized head (dark core block, two big steel striking drums with gold bands, a ruby in
a gold bezel on both sides, a steel top spike), steel langets down a wooden haft, leather grip bands, a gold pommel.
tags: hammer, war hammer, warhammer, mace, maul, weapon, melee, fantasy, medieval, dwarf, stylized, fortnite, roblox
Exaggerated proportions (a head as wide as a third of the haft) and clear color blocks: steel, navy, gold, ruby, wood.
budget: 8000 (a two-handed melee weapon; low detail, chunky bevels)
"""
import nighty as n

n.settings(detail="low", size=0.9, collection="WarHammer")
steel = n.surface("Hammer Steel", "steel", color="#aeb9c8", style="stylized")
navy = n.surface("Hammer Navy", "plastic", color="#27324a", style="stylized")
gold = n.surface("Hammer Gold", "gold", color="#f4b93a", style="stylized")
wood = n.surface("Hammer Wood", "wood", color="#9a5d30", grain="Z", style="stylized")
leather = n.surface("Hammer Leather", "leather", color="#7d2f1e", style="stylized")
ruby = n.surface("Hammer Ruby", "plastic", color="#e3263f", style="stylized", roughness=0.1)
Z = 0.8  # height of the head's center
parts = []


def keep(obj):
    parts.append(obj)
    return obj


def cut_gem(radius, axis, at, name):
    """A table-cut stone: a short faceted cone, flat shaded so each facet catches the light."""
    stone = n.lathe([(0.0, 0.0), (radius, 0.0), (radius, radius * 0.25), (radius * 0.6, radius * 0.6),
                     (0.0, radius * 0.6)], segments=8, axis=axis, at=at, name=name, material=ruby)
    n.shade_flat(stone)
    return keep(stone)


# ---- head: a dark core block between two big steel drums, gold bands, rubies, a top spike
core = n.rounded_box((0.15, 0.11, 0.17), radius=0.022, at=(0, 0, Z), name="HeadCore", material=navy)
keep(core)
for s in (-1, 1):
    drum = n.cylinder(0.078, 0.1, segments=32, axis="X", at=(s * 0.12, 0, Z), name="StrikeDrum")  # a round silhouette
    n.chunky(drum, 0.7)
    n.paint(drum, steel)
    keep(drum)
    face = n.cylinder(0.064, 0.016, segments=32, axis="X", at=(s * 0.174, 0, Z), name="StrikeFace")   # a raised striking face
    n.chunky(face, 0.8)
    n.paint(face, steel)
    keep(face)
    keep(n.torus(0.08, 0.011, segments=32, ring_segments=6, axis="X", at=(s * 0.088, 0, Z), name="DrumBand",
                 material=gold))
    keep(n.torus(0.08, 0.008, segments=32, ring_segments=6, axis="X", at=(s * 0.152, 0, Z), name="DrumRim",
                 material=gold))
    keep(n.torus(0.033, 0.007, segments=16, ring_segments=6, axis=(0, s, 0), at=(0, s * 0.055, Z),
                 name="GemBezel", material=gold))
    cut_gem(0.029, (0, s, 0), (0, s * 0.054, Z), "HeadRuby")
spike = n.lathe([(0.0, 0.0), (0.042, 0.0), (0.04, 0.02), (0.016, 0.085), (0.0, 0.1)], segments=12,
                at=(0, 0, Z + 0.08), name="TopSpike", material=steel)
keep(spike)
keep(n.cylinder(0.05, 0.018, at=(0, 0, Z + 0.086), name="SpikeCollar", material=gold))

# ---- haft: wood with steel langets under the head, a gold collar, leather bands, gold pommel
keep(n.cylinder(0.025, 0.74, at=(0, 0, 0.43), name="Haft", material=wood))
keep(n.cylinder(0.034, 0.03, at=(0, 0, Z - 0.1), name="HeadCollar", material=gold))
for s in (-1, 1):
    langet = n.extrude([(-0.013, 0.0), (0.013, 0.0), (0.013, 0.13), (0.0, 0.15), (-0.013, 0.13)], depth=0.008,
                       at=(0, s * 0.0265, Z - 0.26), name="Langet")
    n.chamfer(langet, 0.002)
    n.paint(langet, steel)
    keep(langet)
    keep(n.bolts_along((0.0, s * 0.031, Z - 0.235), (0.0, s * 0.031, Z - 0.165), 2, radius=0.0055, kind="round",
                       axis=(0, s, 0), name="LangetRivets", material=gold))
for k in range(4):
    band = n.cylinder(0.029, 0.026, at=(0, 0, 0.12 + k * 0.05), rot=(7 if k % 2 else -7, 0, 0), name="GripBand")
    n.chunky(band, 0.7)
    n.paint(band, leather)
    keep(band)
pommel = n.lathe(n.spline([(0.0, 0.0), (0.024, 0.006), (0.036, 0.03), (0.03, 0.05), (0.02, 0.064), (0.0, 0.068)],
                          samples=2), name="Pommel", material=gold)
keep(pommel)

n.rotate(parts, -20, "Z")  # the striking drum and the ruby both face the 3/4 view
n.ground(parts)
n.center(parts, "XY")
