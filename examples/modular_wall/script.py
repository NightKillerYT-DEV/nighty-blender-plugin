# SPDX-License-Identifier: GPL-3.0-or-later
"""Realistic modular precast concrete wall, 2 m wide x 3 m tall x 0.25 m deep, snapping on a 0.25 m grid (origin
corner at 0, 0, 0): chamfered panel ends (copies show V-joints), a reveal groove, formwork tie holes on both faces, a
darker plinth, a metal coping with drip edges, and an electrical conduit with clamps and a junction box.
tags: realistic, modular, wall, kit, building, architecture, environment, concrete, precast, industrial, level design, trim
Not centered on purpose: the wall fills x 0..2, y 0..0.25, z 0..3 so copies placed every 2 m in X line up exactly;
only the plinth and the coping stand proud in Y. Every detail stays inside x 0..2, so neighbours never overlap.
budget: 3500 (a modular environment piece)
"""
import nighty as n

W, D, H = 2.0, 0.25, 3.0           # the grid cell this piece fills
n.settings(detail="low", size=H, collection="ModularWall")
concrete = n.surface("Wall Concrete", "concrete", color="#8e8b84", wear=0.2, dirt=0.55)
plinth_mat = n.surface("Wall Plinth", "concrete", color="#64625d", wear=0.25, dirt=0.7)
coping_mat = n.surface("Wall Coping", "painted_metal", color="#5c6168", wear=0.15, dirt=0.4, size=1.0)
conduit_mat = n.surface("Wall Conduit", "painted_metal", color="#5f666e", wear=0.12, dirt=0.35, size=0.6)
stencil = n.surface("Wall Stencil", "painted_metal", color="#2b2b2a", wear=0.0, dirt=0.3, roughness=0.8)
PL, CP = 0.3, 0.012                # plinth height, coping plate thickness
REVEAL = 1.62                      # the horizontal reveal between two pour lifts

# ---- the panel: chamfered ends and edges, a reveal groove and tie holes on both faces
core = n.box((W, D, H - PL - CP), at=(W / 2, D / 2, PL + (H - PL - CP) / 2), name="Panel")
n.chamfer(core, 0.012)             # chamfered panel edges (copies side by side show V-joints) ...
n.apply_modifiers(core)            # ... made real first, so the reveal cuts cleanly through the chamfered ends
for y in (0.0, D):
    n.boolean_cut(core, n.box((W + 0.1, 0.024, 0.02), at=(W / 2, y, REVEAL)))      # 12 mm deep reveal
    for x in (0.25, 0.75, 1.25, 1.75):
        for z in (0.78, 1.25, 2.05, 2.6):
            n.boolean_cut(core, n.cone(0.022, 0.034, top=0.009, axis="Y" if y == 0.0 else "-Y", segments=12,
                                       at=(x, y, z)))                              # formwork tie cones
n.weighted_normals(core)           # big flat faces shade flat again after the cuts
n.paint(core, concrete)
# a painted panel ID: low flat letters, 0.5 mm proud of the face (the rest sunk into the panel)
label = n.text3d("P-07", size=0.11, depth=0.002, bevel=0, resolution=2, axis="-Y", at=(0.36, 0.0005, 0.52),
                 name="PanelID", material=stencil)

# ---- plinth: proud of both faces, chamfered top edge
plinth = n.box((W, D + 0.04, PL), at=(W / 2, D / 2, PL / 2), name="Plinth")
n.chamfer(plinth, 0.015)
n.paint(plinth, plinth_mat)

# ---- metal coping: overhangs both faces with a turned-down drip edge
O, T, DR = 0.0265, 0.004, 0.049   # overhang, sheet thickness, drip depth: one bent sheet, extruded along the wall
coping = n.extrude([(-O, H), (D + O, H), (D + O, H - DR), (D + O - T, H - DR), (D + O - T, H - CP),
                    (-O + T, H - CP), (-O + T, H - DR), (-O, H - DR)], depth=W, plane="YZ", at=(W / 2, 0, 0),
                   name="Coping")
n.paint(coping, coping_mat)

# ---- conduit up the front face: a pipe on stand-off clamps, a junction box
CX, CY = 1.62, -0.032              # conduit center line (in front of the face at y = 0)
conduit = n.cylinder(0.018, H - PL - CP - 0.12, at=(CX, CY, PL + (H - PL - CP) / 2), name="Conduit")
box_z = 1.15
jbox = n.box((0.12, 0.05, 0.14), at=(CX, -0.025, box_z), name="JunctionBox")
n.bevel(jbox, width=0.006)
clamps = []
for z in (0.55, 2.2, 2.75):
    strap = n.tube(0.021, 0.022, inner=0.018, axis="Z", at=(CX, CY, z))
    foot = n.box((0.07, 0.018, 0.026), at=(CX, -0.009, z))
    n.chamfer(foot, 0.002)
    clamps += [strap, foot]
    clamps += [n.bolt(0.0038, kind="hex", axis="-Y", at=(CX + sx * 0.026, -0.018, z)) for sx in (-1, 1)]
clamps = n.merge_parts(clamps, name="Clamps", weld=False)
n.paint([conduit, jbox, clamps], conduit_mat)
