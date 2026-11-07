# SPDX-License-Identifier: GPL-3.0-or-later
"""Military ammo can (M2A1 style): a steel can with raised side panels and sunk end panels, a rolled bottom rim, a lid
with a raised top and an overlapping skirt, a hinged latch lever, a knuckle hinge, a wire handle and stencil text.
tags: ammo box, ammo can, ammunition, military, army, crate, container, pickup, prop, olive, stencil, realistic
Real size (0.31 x 0.16 x 0.23 m); olive drab paint chipped to bare steel on the edges, dark steel hardware.
Separate chamfered plates for the raised panels and shallow boolean cuts for the sunk ones: crisp and light.
budget: 5500 (a pickup prop with stencil text; one Roblox mesh)
"""
import nighty as n

n.settings(detail="low", size=0.31, collection="AmmoCan")
olive = n.surface("Ammo Olive", "painted_metal", color="#4a5228", wear=0.3, dirt=0.4, size=0.25)
steel = n.surface("Ammo Steel", "gunmetal", wear=0.2, dirt=0.3, size=0.25)
ink = n.surface("Ammo Stencil", "painted", color="#d6bf3a", wear=0.0, dirt=0.15, roughness=0.8)
parts = []

L, W, H = 0.30, 0.155, 0.19          # can body: length (X), width (Y), height (Z)
LID = 0.034                          # lid height; its skirt overlaps the can by 12 mm
TOP = H - 0.012 + LID                # top of the lid
PZ, PH = 0.095, 0.13                 # side panels: center height and height

# ---- can: rounded corners, sunk panels on the ends, a rolled rim at the bottom
can = n.extrude(n.rounded_rect(L, W, 0.012), depth=H, plane="XY", at=(0, 0, H / 2), name="Can")
for s in (-1, 1):
    n.boolean_cut(can, n.extrude(n.rounded_rect(W - 0.045, PH - 0.01, 0.01), depth=0.004, plane="YZ",
                                 at=(s * L / 2, 0, PZ)))                       # 2 mm deep
n.bevel(can, width=0.002)
n.paint(can, olive)
parts.append(can)
rim = n.extrude(n.rounded_rect(L + 0.005, W + 0.005, 0.014), depth=0.012, plane="XY", at=(0, 0, 0.006),
                name="BottomRim")
n.bevel(rim, width=0.002)
n.paint(rim, olive)
parts.append(rim)

# ---- raised side panels: plates 2.5 mm proud of the long sides, chamfered like stamped steel
panels = []
for s in (-1, 1):
    p = n.extrude(n.rounded_rect(L - 0.05, PH, 0.012), depth=0.004, plane="XZ", at=(0, s * (W / 2 + 0.0005), PZ))
    n.chamfer(p, 0.0015)
    panels.append(p)
parts.append(n.merge_parts(panels, name="SidePanels", weld=False))
n.paint("SidePanels", olive)

# ---- lid: a bit bigger than the can, raised top panel (inset less than the corner radius)
lid = n.extrude(n.rounded_rect(L + 0.008, W + 0.008, 0.016), depth=LID, plane="XY", at=(0, 0, TOP - LID / 2),
                name="Lid")
n.inset(lid, "+Z", amount=0.013, depth=0.004, min_dot=0.999)   # min_dot: the flat top only, not the corner arcs
n.bevel(lid, width=0.0022)
n.paint(lid, olive)
parts.append(lid)
RAISED = TOP + 0.004

# ---- wire handle on the raised top, held by two clips
parts.append(n.handle(0.11, 0.032, 0.0052, axis="Z", at=(0, 0, RAISED - 0.001), name="Handle", material=steel))
for x in (-0.055, 0.055):
    parts.append(n.rounded_box((0.02, 0.016, 0.008), radius=0.0025, at=(x, 0, RAISED + 0.003), name="HandleClip",
                               material=steel))

# ---- latch lever on the +X end: pivot bracket in the sunk panel, a stamped lever plate, a hook over the lid
X1 = L / 2
parts.append(n.box((0.010, 0.084, 0.012), at=(X1 + 0.002, 0, H - 0.07), bevel=0.0015, name="LatchBracket",
                   material=olive))
parts.append(n.cylinder(0.0038, 0.09, axis="Y", at=(X1 + 0.0062, 0, H - 0.07), name="LatchPin", material=steel))
lever = n.extrude([(-0.036, H - 0.075), (0.036, H - 0.075), (0.029, TOP - 0.004), (-0.029, TOP - 0.004)],
                  depth=0.004, plane="YZ", at=(X1 + 0.0068, 0, 0), name="Latch")   # sharp corners: the inset
n.inset(lever, "+X", amount=0.01, depth=0.0015)                                  # can't fold over an arc
n.bevel(lever, width=0.0012)
n.paint(lever, olive)
parts.append(lever)
parts.append(n.box((0.018, 0.05, 0.0045), at=(X1 + 0.0008, 0, TOP + 0.0019), bevel=0.0012, name="LatchHook",
                   material=olive))

# ---- knuckle hinge on the -X end: a leaf on the can, three knuckles on one pin
X0 = -L / 2
parts.append(n.box((0.004, 0.11, 0.03), at=(X0 - 0.0012, 0, H - 0.024), bevel=0.001, name="HingeLeaf",
                   material=steel))
knuckles = [n.cylinder(0.0062, 0.032, axis="Y", at=(X0 - 0.0055, y, H - 0.006)) for y in (-0.037, 0.0, 0.037)]
parts.append(n.merge_parts(knuckles, name="HingeKnuckles", weld=False))
n.paint("HingeKnuckles", steel)

# ---- stencil on the front panel (flat paint letters, a hair proud of the panel)
FACE = -W / 2 - 0.0025
for text, z, size in (("CARTRIDGES 7.62 MM", 0.128, 0.016), ("BALL M80", 0.096, 0.026), ("LOT 21-07", 0.062, 0.013)):
    parts.append(n.text3d(text, size=size, depth=0.0012, bevel=0, axis="-Y", at=(0, FACE - 0.0005, z),
                          name="Stencil", material=ink))

n.ground(parts)
n.center(parts, "XY")
