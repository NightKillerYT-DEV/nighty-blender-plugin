# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized fantasy sword: a broad leaf blade with wide chamfered edges and a glowing rune channel, a gold blade
collar, a winged gold crossguard with cut sapphires in bezels, a leather grip with chunky wraps and a gem pommel.
tags: sword, blade, longsword, weapon, melee, fantasy, medieval, knight, magic, stylized, fortnite, roblox, cartoon
Exaggerated, chunky proportions and clear color blocks: cool steel, warm gold, a dark navy guard, blue wraps,
glow and gems.
The blade's outline edges get one wide flat chamfer (n.mark_bevel first), so the rune channel cut after stays crisp.
budget: 5000 (a hand-held melee weapon; low detail, chunky bevels)
"""
import nighty as n

n.settings(detail="low", size=1.0, collection="Sword")
steel = n.surface("Sword Steel", "steel", color="#b4c2d2", style="stylized")
gold = n.surface("Sword Gold", "gold", color="#f4b93a", style="stylized")
navy = n.surface("Sword Navy", "plastic", color="#26324a", style="stylized")   # a dark painted guard: value contrast
leather = n.surface("Sword Leather", "leather", color="#4a2716", style="stylized")
wrap = n.surface("Sword Wrap", "plastic", color="#2350c8", style="stylized")
gem = n.surface("Sword Sapphire", "plastic", color="#2f6bff", style="stylized", roughness=0.1)
rune = n.surface("Sword Rune", "glow", color="#3fd8ff", glow=10)
parts = []


def keep(obj):
    parts.append(obj)
    return obj


def cut_gem(radius, axis, at, name):
    """A table-cut stone: a short faceted cone, flat shaded so each facet catches the light."""
    stone = n.lathe([(0.0, 0.0), (radius, 0.0), (radius, radius * 0.25), (radius * 0.6, radius * 0.6),
                     (0.0, radius * 0.6)], segments=8, axis=axis, at=at, name=name, material=gem)
    n.shade_flat(stone)
    return keep(stone)


# ---- blade: a leaf outline, thick enough to read from the side, one wide chamfer on the outline
blade = n.extrude([(-0.04, 0.0), (0.04, 0.0), (0.05, 0.36), (0.044, 0.56), (0.0, 0.74), (-0.044, 0.56),
                   (-0.05, 0.36)], depth=0.018, name="Blade")
n.mark_bevel(blade)
for side in ("-Y", "+Y"):  # the rune channel down both faces
    n.vents(blade, side, center=(0.0, 0.33), count=1, slot=(0.016, 0.4), depth=0.004)
n.bevel(blade, width=0.0075, segments=1, limit="weight")
n.paint(blade, steel)
keep(blade)
keep(n.box((0.009, 0.0102, 0.39), at=(0.0, 0.0, 0.33), name="RuneGlow", material=rune))  # inside the channel

# blade collar: a pointed gold plate over the blade's root, thicker than the blade (a layer that reads)
collar = n.extrude([(-0.058, 0.0, 0.006), (0.058, 0.0, 0.006), (0.05, 0.06, 0.008), (0.0, 0.11),
                    (-0.05, 0.06, 0.008)], depth=0.028, name="BladeCollar")
n.mark_bevel(collar)
for side in ("-Y", "+Y"):
    n.panel_cut(collar, side, center=(0.0, 0.05), size=(0.06, 0.05), groove=0.004, radius=0.012)
n.bevel(collar, width=0.004, segments=2, limit="weight")
n.paint(collar, gold)
keep(collar)

# ---- crossguard: big swept-up wings in dark navy with gold tips, a center block holding a cut sapphire
guard = n.extrude([(-0.17, 0.05, 0.016), (-0.14, 0.0, 0.012), (-0.05, -0.03, 0.014), (0.05, -0.03, 0.014),
                   (0.14, 0.0, 0.012), (0.17, 0.05, 0.016), (0.135, 0.035, 0.01), (0.05, 0.008, 0.012),
                   (-0.05, 0.008, 0.012), (-0.135, 0.035, 0.01)], depth=0.04, at=(0, 0, -0.012), name="Crossguard")
n.chunky(guard, 0.8)
n.paint(guard, navy)
keep(guard)
for s in (-1, 1):
    tip = n.sphere(0.024, segments=12, at=(s * 0.165, 0, 0.032), name="GuardTip", material=gold)
    keep(tip)
block = n.rounded_box((0.085, 0.05, 0.075), radius=0.016, at=(0, 0, -0.012), name="GuardBlock", material=gold)
keep(block)
for s in (-1, 1):
    keep(n.torus(0.024, 0.0055, segments=16, ring_segments=6, axis=(0, s, 0), at=(0, s * 0.025, -0.012),
                 name="GemBezel", material=gold))
    cut_gem(0.021, (0, s, 0), (0, s * 0.0235, -0.012), "GuardGem")

# ---- grip: leather core, four chunky wrap bands (big enough to read), gold rings at both ends
keep(n.cylinder(0.02, 0.17, at=(0, 0, -0.13), name="Grip", material=leather))
for k in range(4):
    band = n.cylinder(0.0235, 0.018, at=(0, 0, -0.178 + k * 0.034), rot=(8 if k % 2 else -8, 0, 0),
                      name="GripWrap")
    n.chunky(band, 0.7)
    n.paint(band, wrap)
    keep(band)
for z in (-0.05, -0.212):
    ring = n.cylinder(0.027, 0.018, at=(0, 0, z), name="GripRing")
    n.chunky(ring, 0.6)
    n.paint(ring, gold)
    keep(ring)

# ---- pommel: a gold bulb with a cut gem on the front
pommel = n.lathe(n.spline([(0.0, -0.3), (0.026, -0.294), (0.042, -0.272), (0.042, -0.246), (0.028, -0.226),
                           (0.0, -0.22)], samples=2), name="Pommel", material=gold)
keep(pommel)
cut_gem(0.017, (0, -1, 0), (0, -0.038, -0.259), "PommelGem")

n.rotate(parts, 25, "Z")  # turn the flat of the blade to the 3/4 view
n.ground(parts)
n.center(parts, "XY")
