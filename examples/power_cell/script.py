# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized power cell (pickup): stepped dark end caps with amber bands, a glass tube with a glowing core and
coil rings, a white cage with a mid clamp ring, a charge meter with glowing pips, a carry handle and a status light.
tags: scifi, sci-fi, battery, power cell, energy, canister, pickup, item, prop, glass, emissive, glowing, stylized
Chunky lathed caps (one profile, mirrored for the top), glass around an emissive core: the glow reads through it;
clear color blocks (dark caps, white cage, amber bands, green glow).
budget: 5700 (a pickup prop; one Roblox mesh)
"""
import nighty as n

n.settings(detail="low", size=0.3, collection="PowerCell")
dark = n.surface("Cell Dark", "plastic", color="#2a2f3a", style="stylized")
white = n.surface("Cell White", "plastic", color="#eef1f5", style="stylized")
amber = n.surface("Cell Amber", "plastic", color="#ff9a00", style="stylized")
steel = n.surface("Cell Steel", "steel", color="#b4bcc6", style="stylized")
glass = n.surface("Cell Glass", "glass", color="#d8fff0")
glow = n.surface("Cell Glow", "glow", color="#3dff7a", glow=4)
parts = []


def keep(obj):
    parts.append(obj)
    return obj


H = 0.3                    # overall height (without the handle)
# ---- end caps: one stepped profile (radius, height), the top one is the same profile turned over
CAP = [(0.0, 0.0), (0.062, 0.0), (0.068, 0.006), (0.068, 0.03), (0.061, 0.034), (0.061, 0.042), (0.066, 0.046),
       (0.066, 0.058), (0.058, 0.064), (0.054, 0.064), (0.054, 0.07), (0.0, 0.07)]
bottom = n.lathe(CAP, segments=32, name="BottomCap")
top = n.lathe([(r, H - z) for r, z in CAP], segments=32, name="TopCap")
for cap in (bottom, top):   # the profile's own 45-degree steps are the bevels: no modifier needed
    n.paint(cap, dark)
    keep(cap)
for z in (0.038, H - 0.038):   # amber bands filling the caps' grooves
    keep(n.tube(0.0645, 0.0078, inner=0.058, segments=32, at=(0, 0, z), name="CapBand", material=amber))
screws = n.bolt(0.0045, kind="hex", axis="X", at=(0.068, 0, 0.018), name="CapScrews", material=steel)
n.radial(screws, 3, axis="Z", center=(0, 0, 0))
keep(screws)

# ---- glass tube with a glowing core and two coil rings inside (seen through the glass)
keep(n.cylinder(0.05, H - 0.14, segments=32, at=(0, 0, H / 2), name="GlassTube", material=glass))
keep(n.cylinder(0.022, H - 0.12, segments=24, at=(0, 0, H / 2), name="Core", material=glow))  # ends sit in the caps
for z in (0.12, 0.18):
    keep(n.torus(0.0245, 0.0045, segments=24, ring_segments=6, at=(0, 0, z), name="CoilRing", material=steel))

# ---- cage: three chunky bars, a clamp ring around their middle
bar = n.rounded_box((0.014, 0.012, H - 0.13), radius=0.004, at=(0.061, 0, H / 2), name="CageBars")
n.radial(bar, 3, axis="Z", center=(0, 0, 0))
n.paint(bar, white)
keep(bar)
keep(n.torus(0.064, 0.005, segments=32, ring_segments=6, at=(0, 0, H / 2), name="ClampRing", material=amber))

# ---- charge meter on the front: a dark strip from cap to cap with five glowing pips sunk into it
meter = n.box((0.024, 0.01, H - 0.132), at=(0, -0.0575, H / 2), name="Meter")
n.mark_bevel(meter)
n.vents(meter, "-Y", center=(0.0, H / 2), count=5, slot=(0.014, 0.02), gap=0.008, depth=0.004)
n.bevel(meter, width=0.0015, segments=2, limit="weight")
n.paint(meter, dark)
keep(meter)
pips = [n.box((0.012, 0.004, 0.018), at=(0, -0.06, H / 2 + (k - 2) * 0.028)) for k in range(5)]
keep(n.merge_parts(pips, name="MeterPips", weld=False))
n.paint("MeterPips", glow)

# ---- top: a carry handle and a glowing status light
keep(n.handle(0.1, 0.04, 0.0075, axis="Z", at=(0, 0, H - 0.002), name="Handle", material=white))
keep(n.dome(0.014, height=0.01, at=(0, 0, H - 0.001), name="StatusLight", material=glow))

n.ground(parts)
n.center(parts, "XY")
