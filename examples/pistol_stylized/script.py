# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized pistol: chunky white slide with serrations, an ejection port and a glowing side channel, a dark frame
with an integral trigger guard and rail slots, an angled grip with inset coral panels, sights, hammer, glowing bore.
tags: gun, pistol, handgun, sidearm, weapon, stylized, cartoon, fortnite, valorant, roblox, hard-surface, sci-fi
Clear color blocks (white slide, dark frame and grip, coral accents, cyan glow); layers step out of each other
(slide over frame, coral panels out of the grip) so the profile reads from any side; muzzle along +X.
budget: 6000 (a third-person or pickup pistol; one Roblox mesh)
"""
import nighty as n

n.settings(detail="low", size=0.26, collection="Pistol")
white = n.surface("Pistol White", "plastic", color="#eef1f5", style="stylized")
dark = n.surface("Pistol Dark", "plastic", color="#262b36", style="stylized")
coral = n.surface("Pistol Coral", "plastic", color="#ff5a3c", style="stylized")
steel = n.surface("Pistol Steel", "steel", color="#b4bcc6", style="stylized")
glow = n.surface("Pistol Glow", "glow", color="#35e8ff", glow=10)
parts = []


def keep(obj):
    parts.append(obj)
    return obj


# ---- slide: a side profile (x, z, corner radius), chunky outline, crisp serrations, port and glow channel
slide = n.extrude([(-0.112, 0.0, 0.003), (0.112, 0.0, 0.003), (0.118, 0.03, 0.008), (0.10, 0.046, 0.008),
                   (-0.104, 0.046, 0.006), (-0.116, 0.036, 0.004)], depth=0.032, name="Slide")
n.mark_bevel(slide)   # only the outline gets the chunky bevel; cuts made after stay crisp (and light)
for side in ("-Y", "+Y"):
    n.vents(slide, side, center=(-0.082, 0.025), count=5, slot=(0.0045, 0.03), gap=0.0042, direction="u",
            depth=0.0022)                                                                   # rear serrations
for s in (-1, 1):   # a recessed channel on each side with a light strip behind it
    n.boolean_cut(slide, n.rounded_box((0.07, 0.008, 0.0062), radius=0.0028, at=(0.055, s * 0.016, 0.016)))
n.boolean_cut(slide, n.rounded_box((0.036, 0.024, 0.016), radius=0.003, at=(-0.004, -0.017, 0.047)))  # port
n.bevel(slide, width=0.0028, segments=4, profile=0.55, limit="weight")
n.paint(slide, white)
keep(slide)
for s in (-1, 1):
    keep(n.box((0.068, 0.003, 0.0054), at=(0.055, s * 0.0135, 0.016), name="SlideGlow", material=glow))
keep(n.box((0.033, 0.008, 0.005), at=(-0.004, -0.0085, 0.0395), name="Chamber", bevel=0.0008, material=steel))
keep(n.box((0.15, 0.008, 0.003), at=(0.012, 0, 0.0458), name="TopStripe", bevel=0.0008, material=coral))

# ---- frame: one outline with the trigger guard hole, narrower than the slide (a shadow line under it)
guard_hole = [(0.012, -0.023, 0.004), (0.012, -0.042, 0.008), (-0.028, -0.045, 0.008), (-0.036, -0.032, 0.006),
              (-0.036, -0.023, 0.002)]
frame = n.extrude([(-0.108, 0.004, 0.002), (0.104, 0.004, 0.002), (0.104, -0.019, 0.005), (0.022, -0.019, 0.004),
                   (0.023, -0.05, 0.012), (-0.034, -0.054, 0.008), (-0.05, -0.03, 0.006), (-0.114, -0.022, 0.006)],
                  holes=[guard_hole], depth=0.028, name="Frame")
n.mark_bevel(frame)
n.vents(frame, "-Z", center=(0.07, 0.0), count=3, slot=(0.005, 0.02), gap=0.008, direction="u", depth=0.003)
n.bevel(frame, width=0.0022, segments=4, profile=0.55, limit="weight")
n.paint(frame, dark)
keep(frame)

# ---- grip: angled, with coral panels standing out of it (grooves crisp), a coral base plate
grip = n.extrude([(-0.042, -0.02, 0.0), (-0.06, -0.122, 0.006), (-0.124, -0.122, 0.01), (-0.113, -0.03, 0.012),
                  (-0.106, -0.02, 0.0)], depth=0.032, name="Grip")
n.bevel(grip, width=0.003, segments=4, profile=0.55)
n.paint(grip, dark)
keep(grip)
panels = n.extrude([(-0.052, -0.036, 0.005), (-0.066, -0.108, 0.005), (-0.114, -0.108, 0.006),
                    (-0.106, -0.036, 0.005)], depth=0.036, name="GripPanels")
n.mark_bevel(panels)
for side in ("-Y", "+Y"):
    n.vents(panels, side, center=(-0.086, -0.072), count=4, slot=(0.036, 0.0045), gap=0.006, depth=0.0018)
n.bevel(panels, width=0.0015, segments=2, limit="weight")
n.paint(panels, coral)
keep(panels)
keep(n.rounded_box((0.072, 0.036, 0.009), radius=0.003, at=(-0.092, 0, -0.124), name="MagPlate", material=coral))

# ---- trigger, barrel with a glowing bore, sights, hammer, slide stop, takedown pin
trigger = n.extrude(n.spline([(-0.006, -0.02), (-0.008, -0.032), (-0.015, -0.042), (-0.021, -0.041)]) +
                    [(-0.016, -0.03), (-0.014, -0.02)], depth=0.007, name="Trigger", material=coral)
n.chamfer(trigger, 0.001)
keep(trigger)
barrel = n.tube(0.0092, 0.016, inner=0.0058, axis="X", at=(0.12, 0, 0.022), name="Barrel", material=steel)
n.chamfer(barrel, 0.0008)
keep(barrel)
keep(n.cylinder(0.006, 0.002, axis="X", at=(0.122, 0, 0.022), name="BoreGlow", material=glow))
keep(n.rounded_box((0.012, 0.007, 0.009), radius=0.002, at=(0.094, 0, 0.0505), name="FrontSight", material=coral))
rear = n.box((0.012, 0.026, 0.01), at=(-0.094, 0, 0.0505), name="RearSight")
n.boolean_cut(rear, n.box((0.03, 0.006, 0.008), at=(-0.094, 0, 0.0565)))
n.chamfer(rear, 0.0012)
n.paint(rear, dark)
keep(rear)
hammer = n.extrude([(-0.112, 0.026, 0.002), (-0.126, 0.032, 0.004), (-0.13, 0.045, 0.003), (-0.121, 0.047, 0.002),
                    (-0.111, 0.038, 0.002)], depth=0.012, name="Hammer", material=steel)
n.chamfer(hammer, 0.001)
keep(hammer)
keep(n.rounded_box((0.032, 0.004, 0.006), radius=0.0015, at=(-0.012, -0.0155, 0.0015), name="SlideStop",
                   material=dark))
grey = n.surface("Pistol Grey", "plastic", color="#9aa6b5", style="stylized")
insert = n.extrude([(0.03, -0.003, 0.003), (0.1, -0.003, 0.003), (0.1, -0.016, 0.003), (0.03, -0.016, 0.003)],
                   depth=0.031, name="FrameInsert")       # a grey layer standing out of the frame's front
n.chamfer(insert, 0.0012)
n.paint(insert, grey)
keep(insert)
keep(n.cylinder(0.0032, 0.034, axis="Y", at=(0.07, 0, -0.0095), name="TakedownPin", material=steel))
keep(n.cylinder(0.0042, 0.034, axis="Y", at=(-0.04, 0, -0.03), name="MagRelease", material=coral))

n.ground(parts)
n.center(parts, "XY")
