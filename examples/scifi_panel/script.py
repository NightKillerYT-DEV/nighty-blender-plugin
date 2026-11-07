# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized sci-fi wall panel (modular, 1 x 1 m): a dark backing plate, a white hatch plate with vents, bolts and a
status light, a glowing strip in a recessed channel, a grey lower plate with a grille and light behind it, a conduit.
tags: scifi, sci-fi, panel, wall, modular, kit, tile, spaceship, level design, environment, greeble, emissive, stylized
Tiles on a 1 m grid: the back face is the wall plane (y = 0), the pivot is its bottom center, nothing sticks out past
the 1 x 1 m edges (the conduit runs edge to edge, so stacked panels continue it). Front faces -Y.
budget: 3500 (a modular wall piece used many times in a level)
"""
import nighty as n

n.settings(detail="low", size=1.0, collection="SciFiPanel")
dark = n.surface("Panel Dark", "plastic", color="#2b2f37", style="stylized")
white = n.surface("Panel White", "plastic", color="#eef1f5", style="stylized")
grey = n.surface("Panel Grey", "plastic", color="#9aa6b5", style="stylized")
amber = n.surface("Panel Amber", "plastic", color="#ffb020", style="stylized")
steel = n.surface("Panel Steel", "steel", color="#b4bcc6", style="stylized")
glow = n.surface("Panel Glow", "glow", color="#2fe0ff", glow=6)
warn = n.surface("Panel Warning", "glow", color="#ff7a1a", glow=5)

T = 0.06                    # backing plate thickness; its front is at y = -T
X0 = 0.04                   # the plates sit right of the conduit

# ---- backing plate: the 1 x 1 m tile itself (chunky edges make a panel line where two tiles meet)
base = n.box((1.0, T, 1.0), at=(0, -T / 2, 0.5), name="Backing")
n.mark_bevel(base)
n.boolean_cut(base, n.box((0.8, 0.02, 0.03), at=(X0, -T, 0.33)))        # channel for the light strip
n.bevel(base, width=0.008, segments=2, limit="weight")
n.paint(base, dark)
keep = [base]               # the parts (no n.ground / n.center: the tile keeps its exact grid placement)
keep.append(n.box((0.79, 0.005, 0.022), at=(X0, -T + 0.0078, 0.33), name="LightStrip", material=glow))

# ---- white hatch plate stepping out of the backing: hatch seam, vents, bolts, status light
hatch = n.box((0.8, 0.03, 0.56), at=(X0, -T - 0.011, 0.66), name="HatchPlate")
n.mark_bevel(hatch)
n.panel_cut(hatch, "-Y", center=(-0.06, 0.66), size=(0.42, 0.34), groove=0.01, radius=0.04)
n.vents(hatch, "-Y", center=(0.33, 0.62), count=4, slot=(0.12, 0.022), gap=0.02, depth=0.012)
n.bevel(hatch, width=0.012, segments=4, profile=0.55, limit="weight")
n.paint(hatch, white)
keep.append(hatch)
HF = -T - 0.026             # the hatch plate's front
keep.append(n.box((0.2, 0.012, 0.04), at=(-0.06, HF - 0.004, 0.53), bevel=0.004, name="HatchGrip", material=amber))
hinges = [n.box((0.032, 0.014, 0.07), at=(-0.27, HF - 0.005, z), bevel=0.004) for z in (0.58, 0.74)]
keep.append(n.merge_parts(hinges, name="HatchHinges", weld=False))
n.paint("HatchHinges", dark)
bolts = [n.bolt(0.014, kind="hex", axis="-Y", at=(x, HF, z)) for x in (-0.32, 0.4) for z in (0.42, 0.9)]
keep.append(n.merge_parts(bolts, name="Bolts", weld=False))
n.paint("Bolts", steel)
keep.append(n.tube(0.034, 0.014, inner=0.022, axis="Y", at=(0.33, HF - 0.005, 0.85), name="LightBezel",
                   material=amber))
keep.append(n.dome(0.023, height=0.014, axis="-Y", at=(0.33, HF + 0.001, 0.85), name="StatusLight",
                   material=warn))

# ---- grey lower plate with a recessed grille and light behind the bars
low = n.box((0.8, 0.025, 0.24), at=(X0, -T - 0.0085, 0.16), name="GrillePlate")
n.mark_bevel(low)
bars = n.grille(low, "-Y", center=(X0, 0.16), size=(0.6, 0.14), count=5, depth=0.015, name="GrilleBars")
n.bevel(low, width=0.008, segments=2, limit="weight")
n.paint(low, grey)
keep.append(low)
n.paint(bars, dark)
keep.append(bars)
keep.append(n.box((0.594, 0.003, 0.134), at=(X0, -T - 0.021 + 0.015 - 0.0012, 0.16), name="GrilleLight",
                  material=glow))

# ---- a conduit on the left running edge to edge (stacked panels continue it), held by two clamps
keep.append(n.cylinder(0.022, 1.0, at=(-0.44, -T - 0.018, 0.5), name="Conduit", material=steel))
clamps = [n.box((0.07, 0.05, 0.045), at=(-0.44, -T - 0.021, z)) for z in (0.2, 0.8)]
for c in clamps:
    n.bevel(c, width=0.006, segments=2, profile=0.55)
keep.append(n.merge_parts(clamps, name="Clamps", weld=False))
n.paint("Clamps", dark)
