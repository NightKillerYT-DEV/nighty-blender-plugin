# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized sci-fi blaster (hero): chunky swept shell over a dark chassis, layered side plates with recessed vents,
orange armor, glowing energy canister in clamps, finned barrel shroud, glowing muzzle, side pistons, holo sight.
tags: gun, blaster, sci-fi, scifi, weapon, stylized, hero, fortnite, valorant, energy, laser, pistol, smg, toy
Clear color blocks (white shell, grey plates, dark chassis, orange armor, cyan glow), game look; muzzle +X.
Depth in profile: shell, plate and chassis layers step out from each other, so the side never reads flat.
budget: 18000 (a hero third-person weapon; one Roblox mesh is at most 20000)
"""
import nighty as n

n.settings(detail="low", size=0.5, collection="Blaster")
white = n.surface("Blaster White", "plastic", color="#eef1f5", style="stylized")
grey = n.surface("Blaster Grey", "plastic", color="#9aa6b5", style="stylized")
dark = n.surface("Blaster Dark", "plastic", color="#2b2f37", style="stylized")
orange = n.surface("Blaster Orange", "plastic", color="#ff7a1a", style="stylized")
metal = n.surface("Blaster Metal", "steel", color="#b4bcc6", style="stylized")
glow = n.surface("Blaster Glow", "glow", color="#2fe0ff", glow=12)
glass = n.surface("Blaster Glass", "glass", color="#bff3ff")
parts = []


def keep(obj):
    parts.append(obj)
    return obj


# ---- shell: a swept side profile with chunky outline edges and a recessed grille with light behind it
body = n.extrude([(-0.16, 0.0, 0.012), (0.10, 0.0, 0.01), (0.14, 0.032, 0.012), (0.14, 0.075, 0.012),
                  (0.02, 0.094, 0.02), (-0.12, 0.10, 0.02), (-0.168, 0.07, 0.016)], depth=0.06, name="Body")
n.mark_bevel(body)   # chunky edges on the outline only: the grille and the vents stay crisp (and light)
glow_bars = n.grille(body, "-Y", center=(-0.002, 0.05), size=(0.085, 0.034), count=4, depth=0.008,
                     name="GrilleBars")
n.paint(glow_bars, dark)
keep(glow_bars)
keep(n.box((0.083, 0.002, 0.032), at=(-0.002, -0.0213, 0.05), name="GrilleLight", material=glow))
n.vents(body, "+Z", center=(-0.07, 0.0), count=4, slot=(0.006, 0.034), gap=0.007, direction="u", depth=0.004)
n.bevel(body, width=0.0042, segments=4, profile=0.55, limit="weight")
n.paint(body, white)
keep(body)

# ---- chassis: a dark chamfered layer under the shell, wider than it, with recessed vents along both sides
chassis = n.box((0.27, 0.068, 0.02), at=(-0.017, 0, 0.007), name="Chassis")
n.mark_bevel(chassis)
for side in ("-Y", "+Y"):
    n.vents(chassis, side, center=(0.045, 0.007), count=4, slot=(0.016, 0.0075), gap=0.008, direction="u",
            depth=0.0034)                        # floors stay just outside the shell's side
n.chamfer(chassis, 0.003)
n.paint(chassis, dark)
keep(chassis)

# ---- layered side plates: grey plates standing out of the shell, chamfered, with vents and screws
for s in (-1, 1):
    side = "-Y" if s < 0 else "+Y"
    plate = n.extrude([(0.052, 0.022, 0.004), (0.112, 0.022, 0.004), (0.13, 0.04, 0.004), (0.13, 0.068, 0.004),
                       (0.052, 0.08, 0.004)], depth=0.006, at=(0, s * 0.032, 0), name="SidePlate")
    n.mark_bevel(plate)
    n.vents(plate, side, center=(0.095, 0.052), count=3, slot=(0.034, 0.0045), gap=0.0045, depth=0.003)
    n.chamfer(plate, 0.0018)
    n.paint(plate, grey)
    keep(plate)
    keep(n.bolts_along((0.06, s * 0.035, 0.03), (0.06, s * 0.035, 0.07), 2, radius=0.0032, kind="hex",
                       axis=(0, s, 0), name="PlateBolts", material=metal))
    # side piston under the grille: sleeve, rod, end blocks
    sleeve = n.cylinder(0.0058, 0.034, axis="X", at=(-0.024, s * 0.0345, 0.0235), name="PistonSleeve")
    n.chunky(sleeve, 0.6)
    n.paint(sleeve, dark)
    keep(sleeve)
    keep(n.cylinder(0.0028, 0.046, axis="X", at=(0.016, s * 0.0345, 0.0235), name="PistonRod", material=metal))
    for x in (-0.045, 0.041):
        keep(n.rounded_box((0.008, 0.011, 0.013), radius=0.002, at=(x, s * 0.0335, 0.0235), name="PistonBlock",
                           material=orange))

# ---- orange armor on the rear, layered over the shell, with a dark inset badge and big round bolts
armor = n.extrude([(-0.15, 0.012, 0.01), (-0.04, 0.012, 0.01), (-0.03, 0.086, 0.012), (-0.118, 0.09, 0.014),
                   (-0.152, 0.066, 0.012)], depth=0.072, name="Armor")
n.chunky(armor, 0.8)
n.paint(armor, orange)
keep(armor)
for s in (-1, 1):
    keep(n.bolts_along((-0.135, s * 0.036, 0.024), (-0.135, s * 0.036, 0.07), 2, radius=0.0055, kind="round",
                       axis=(0, s, 0), name="ArmorBolts", material=metal))
plate = n.plate((0.05, 0.02), thickness=0.0025, text="NB-7", axis=(0, -1, 0), at=(-0.088, -0.0355, 0.05),
                name="Badge", material=dark, text_material=orange)
keep(plate)
keep(n.get("BadgeText"))

# ---- energy canister on top, held by two clamps
can_z = 0.094 + 0.024
keep(n.cylinder(0.019, 0.13, axis="X", at=(-0.03, 0, can_z), name="CanGlass", material=glass))
keep(n.cylinder(0.009, 0.128, axis="X", at=(-0.03, 0, can_z), name="CanCore", material=glow))
for x in (-0.095, 0.035):
    cap = n.cylinder(0.022, 0.016, axis="X", at=(x, 0, can_z), name="CanCap")
    n.chunky(cap, 0.6)
    n.paint(cap, dark)
    keep(cap)
for x in (-0.06, 0.0):
    keep(n.torus(0.0215, 0.0045, axis="X", at=(x, 0, can_z), name="CanClamp", material=metal))
    keep(n.rounded_box((0.014, 0.02, 0.012), radius=0.003, at=(x, 0, can_z - 0.022), name="ClampFoot",
                       material=dark))

# ---- barrel shroud with fins, muzzle with a glowing ring
shroud = n.cylinder(0.026, 0.11, axis="X", at=(0.19, 0, 0.052), name="Shroud")
n.chunky(shroud, 0.6)
n.paint(shroud, dark)
keep(shroud)
for i in range(3):
    fin = n.cylinder(0.036, 0.008, axis="X", at=(0.168 + i * 0.024, 0, 0.052), name="Fin")
    n.chunky(fin, 0.5)
    n.paint(fin, orange)
    keep(fin)
muzzle = n.tube(0.024, 0.04, inner=0.014, axis="X", at=(0.262, 0, 0.052), name="Muzzle")
n.chunky(muzzle, 0.5)
n.paint(muzzle, white)
keep(muzzle)
keep(n.torus(0.0145, 0.0035, axis="X", at=(0.281, 0, 0.052), name="MuzzleGlow", material=glow))
keep(n.cylinder(0.0142, 0.004, axis="X", at=(0.262, 0, 0.052), name="MuzzleCore", material=glow))

# ---- holo sight: a frame with a glowing reticle
frame = n.extrude(n.rounded_rect(0.034, 0.03, 0.008), holes=[n.rounded_rect(0.024, 0.02, 0.004)], depth=0.008,
                  plane="YZ", at=(0.09, 0, 0.11), name="SightFrame")
n.chunky(frame, 0.5)
n.paint(frame, dark)
keep(frame)
keep(n.box((0.0015, 0.025, 0.021), at=(0.09, 0, 0.11), name="Reticle",
           material=n.surface("Blaster Reticle", "glow", color="#ff3b30", glow=4)))
keep(n.rounded_box((0.024, 0.02, 0.016), radius=0.003, at=(0.09, 0, 0.089), name="SightBase", material=dark))

# ---- grip, guard, trigger, hose
grip = n.extrude([(-0.07, 0.005, 0.0), (-0.09, -0.11, 0.012), (-0.135, -0.11, 0.014), (-0.13, -0.04, 0.02),
                  (-0.115, 0.005, 0.0)], depth=0.042, name="Grip")
n.mark_bevel(grip)
for side in ("-Y", "+Y"):
    n.vents(grip, side, center=(-0.105, -0.06), count=4, slot=(0.03, 0.006), gap=0.007, depth=0.0028)
n.bevel(grip, width=0.004, segments=4, profile=0.55, limit="weight")
n.paint(grip, dark)
keep(grip)
keep(n.rounded_box((0.052, 0.046, 0.012), radius=0.004, at=(-0.112, 0, -0.112), name="GripCap", material=orange))
keep(n.pipe([(-0.005, 0, 0.004), (0.0, 0, -0.045), (-0.06, 0, -0.045), (-0.075, 0, -0.03)], radius=0.006,
            bend=0.014, name="Guard", material=white))
trigger = n.extrude([(-0.025, 0.002), (-0.028, -0.02), (-0.04, -0.03), (-0.043, -0.024), (-0.036, -0.012),
                     (-0.036, 0.002)], depth=0.01, name="Trigger", material=orange)
n.chunky(trigger, 0.5)
keep(trigger)
keep(n.cable([(-0.098, 0.0, can_z), (-0.16, 0.01, 0.105), (-0.165, 0.02, 0.06)], radius=0.0065, sag=0.08, clips=1,
             name="Hose", material=dark, clip_material=orange))
keep(n.get("HoseClips"))

n.ground(parts)
n.center(parts, "XY")
