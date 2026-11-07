# SPDX-License-Identifier: GPL-3.0-or-later
"""Realistic wooden shipping crate (hero): planked faces with gaps and butt joints, a beveled batten frame, diagonal
braces, iron corner brackets, nails in every board end, side handles on plates, a stenciled label.
tags: crate, box, wood, wooden, container, storage, shipping, prop, planks, nails, realistic, hero
Real board sizes (0.7 x 0.5 x 0.5 m); weathered pine with grain along each board, iron with worn edges.
Game-ready: low detail, light nail heads, one nail per bracket face, butt joints on the long sides only.
budget: 9500 (a hero prop; one Roblox mesh)
"""
import math

import nighty as n

L, W, H = 0.70, 0.50, 0.50        # outer size: x, y, z
F = 0.055                         # frame batten width
T = 0.018                         # plank thickness
B = 0.016                         # batten thickness (on top of the planks)
n.settings(detail="low", size=0.7, collection="Crate")
pine_x = n.surface("Crate Pine X", "wood", color="#a77d50", grain="X", wear=0.6, dirt=0.6)
pine_y = n.surface("Crate Pine Y", "wood", color="#a77d50", grain="Y", wear=0.6, dirt=0.6)
frame_x = n.surface("Crate Batten X", "wood", color="#7d5634", grain="X", wear=0.7, dirt=0.7)
frame_y = n.surface("Crate Batten Y", "wood", color="#7d5634", grain="Y", wear=0.7, dirt=0.7)
frame_z = n.surface("Crate Batten Z", "wood", color="#7d5634", grain="Z", wear=0.7, dirt=0.7)
inner = n.surface("Crate Inner", "wood", color="#3d2817", grain="X")
iron = n.surface("Crate Iron", "iron", wear=0.6)
ink = n.surface("Crate Stencil", "painted", color="#1d1d1b", wear=0.0, dirt=0.2, roughness=0.85)
parts = []

# core under the planks (keeps everything closed and connected)
core = n.box((L - 2 * B - 2 * T, W - 2 * B - 2 * T, H - 2 * B - 2 * T), at=(0, 0, H / 2), name="Core",
             material=inner)
parts.append(core)
cx, cy, cz = L / 2 - B - T / 2, W / 2 - B - T / 2, H / 2 - B - T / 2   # plank layer centers
pl = []
for s in (-1, 1):
    side_h = H - 2 * B - 2 * T                               # under the top boards, between the long faces
    pl.append(n.planks((L - 2 * B, side_h), count=4, thickness=T, plane="XZ", at=(0, s * cy, H / 2 - T / 2),
                       split=1, seed=3 + s, name="PlanksXZ", material=pine_x))        # butt joints
    pl.append(n.planks((W - 2 * B - 2 * T, side_h), count=4, thickness=T, plane="YZ", at=(s * cx, 0, H / 2 - T / 2),
                       seed=7 + s, name="PlanksYZ", material=pine_y))
pl.append(n.planks((L - 2 * B, W - 2 * B), count=3, thickness=T, plane="XY", at=(0, 0, H / 2 + cz),
                   seed=11, name="PlanksTop", material=pine_x))
planks = n.merge_parts(pl, name="Planks", weld=False)
parts.append(planks)

# battens around every face's edges (12 edge pieces), corners overlapping like nailed boards
bat = []
for a in (-1, 1):
    for b in (-1, 1):
        bat.append(n.box((L - 2 * F, F, F), at=(0, a * (W / 2 - F / 2), H / 2 + b * (H / 2 - F / 2)),
                         bevel=0.003, material=frame_x))
        bat.append(n.box((F, W - 2 * F + 0.0, F), at=(a * (L / 2 - F / 2), 0, H / 2 + b * (H / 2 - F / 2)),
                         bevel=0.003, material=frame_y))
        bat.append(n.box((F, F, H), at=(a * (L / 2 - F / 2), b * (W / 2 - F / 2), H / 2), bevel=0.003,
                         material=frame_z))
frame = n.merge_parts(bat, name="Frame", weld=False)
parts.append(frame)

# diagonal braces on the long faces, lying on the planks inside the frame
br = []
diag = math.hypot(L - 2 * F, H - 2 * F)
ang = math.degrees(math.atan2(H - 2 * F, L - 2 * F))
for s, a in ((-1, ang), (1, -ang)):
    br.append(n.box((diag + 0.02, B * 0.9, 0.075), at=(0, s * (W / 2 - B + 0.45 * B - 0.0003), H / 2), rot=(0, a, 0),
                    bevel=0.0025, material=frame_x))
braces = n.merge_parts(br, name="Braces", weld=False)
parts.append(braces)

# iron corner brackets, nailed
brk = []
for x in (-1, 1):
    for y in (-1, 1):
        for z in (-1, 1):
            brk.append(n.corner_bracket(frame, (x, y, z), size=0.075, thickness=0.0035, nails_per_face=1,
                                        name="Bracket", material=iron))
parts.append(n.merge_parts(brk, name="Brackets", weld=False))
parts.append(n.merge_parts([o for o in n.objects() if o.name.startswith("BracketNails")], name="BracketNails",
                           weld=False))

# nails: two at each plank end where the battens hold them
pts = []
for s in (-1, 1):
    for k in range(4):
        z = B + T + (k + 0.5) * (H - 2 * B - 2 * T) / 4
        for x in (-(L / 2 - F / 2), L / 2 - F / 2):
            pts.append(((x, s * (W / 2 + 0.0), z + 0.0), (0, s, 0)))
nail_parts = [n.nails([p], radius=0.0042, axis=d, name="Nail") for p, d in pts]
parts.append(n.merge_parts(nail_parts, name="Nails", weld=False))
n.paint("Nails", iron)

# handles on the short sides, on iron plates
for s in (-1, 1):
    face = L / 2 - B                                     # the recessed planks of the short side
    plate = n.rounded_box((0.004, 0.16, 0.05), radius=0.0015, at=(s * (face + 0.0018), 0, H * 0.62),
                          name="HandlePlate", material=iron)
    parts.append(plate)
    parts.append(n.handle(0.13, 0.035, 0.0065, axis=(s, 0, 0), at=(s * (face + 0.0035), 0, H * 0.62),
                          name="Handle", material=iron))
    parts.append(n.nails([(s * (face + 0.0038), y, H * 0.62) for y in (-0.07, 0.07)], radius=0.0035,
                         axis=(s, 0, 0), name="PlateNails", material=iron))

# stenciled label on the front planks (raised a hair, so it is paint, not a decal floating off)
for text, x, z, size in (("NIGHTY CO.", 0.13, 0.37, 0.04), ("FRAGILE", -0.15, 0.12, 0.034)):
    parts.append(n.text3d(text, size=size, depth=0.0012, axis="-Y", at=(x, -(W / 2 - B - 0.0003), z), bevel=0,
                          name="Stencil", material=ink))

n.ground(parts)
n.center(parts, "XY")
