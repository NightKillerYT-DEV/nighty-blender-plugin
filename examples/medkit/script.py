# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized medkit (health pickup): a chunky white case in dark corner bumpers, a red seam band, an overhanging lid
with a raised red cross, a framed front panel with a second cross, grey latches over the band, a carry handle.
tags: medkit, first aid, health, health pack, heal, medical, case, pickup, item, prop, game, stylized, fortnite
Clear color blocks (white, red, dark bumpers, grey latches); layers step out of each other (case, bumpers, band,
lid overhang, crosses), so it reads as a medkit from any side and any distance.
budget: 4200 (a pickup prop; one Roblox mesh)
"""
import nighty as n

n.settings(detail="low", size=0.4, collection="Medkit")
white = n.surface("Medkit White", "plastic", color="#f2f4f6", style="stylized")
red = n.surface("Medkit Red", "plastic", color="#e5323b", style="stylized")
dark = n.surface("Medkit Dark", "plastic", color="#2b2f37", style="stylized")
grey = n.surface("Medkit Grey", "plastic", color="#9aa6b5", style="stylized")
parts = []


def keep(obj):
    parts.append(obj)
    return obj


def cross(size, arm, plane, at, name, depth=0.012):
    """A plus sign with softly rounded outer corners, raised depth meters, chunky edges."""
    a, s = arm / 2, size / 2
    r = arm * 0.2
    outline = [(-a, -s, r), (a, -s, r), (a, -a, 0), (s, -a, r), (s, a, r), (a, a, 0), (a, s, r), (-a, s, r),
               (-a, a, 0), (-s, a, r), (-s, -a, r), (-a, -a, 0)]
    c = n.extrude(outline, depth=depth, plane=plane, at=at, name=name)
    n.bevel(c, width=0.003, segments=2, profile=0.55)
    n.paint(c, red)
    return keep(c)


W, D, H, LID, FOOT = 0.4, 0.24, 0.13, 0.05, 0.012   # case size, lid height, gap under the case
TOP = FOOT + H                                       # the seam

# ---- case: chunky white box with a framed front panel (groove crisp: cut after marking the outline)
case = n.box((W, D, H), at=(0, 0, FOOT + H / 2), name="Case")
n.mark_bevel(case)
n.panel_cut(case, "-Y", center=(0, FOOT + H / 2), size=(0.2, 0.094), groove=0.006, radius=0.014)
for side in ("-X", "+X"):   # small vents on the ends
    n.vents(case, side, center=(0.0, FOOT + H / 2), count=3, slot=(0.1, 0.012), gap=0.012, depth=0.006)
n.bevel(case, width=0.01, segments=4, profile=0.55, limit="weight")
n.paint(case, white)
keep(case)
cross(0.07, 0.024, "XZ", (0, -D / 2 - 0.003, FOOT + H / 2), "CrossFront")

# ---- dark corner bumpers (also the feet)
bumpers = []
for sx in (-1, 1):
    for sy in (-1, 1):
        b = n.box((0.05, 0.05, TOP - 0.006), at=(sx * (W / 2 - 0.016), sy * (D / 2 - 0.016), (TOP - 0.006) / 2))
        n.bevel(b, width=0.008, segments=2, profile=0.55)
        bumpers.append(b)
keep(n.merge_parts(bumpers, name="Bumpers", weld=False))
n.paint("Bumpers", dark)

# ---- red band over the seam, then the overhanging lid with a big raised cross and a handle
band = n.box((W + 0.014, D + 0.014, 0.018), at=(0, 0, TOP), name="SeamBand")
n.bevel(band, width=0.004, segments=2, profile=0.55)
n.paint(band, red)
keep(band)
lid = n.box((W + 0.008, D + 0.008, LID), at=(0, 0, TOP + 0.007 + LID / 2), name="Lid")
n.bevel(lid, width=0.012, segments=4, profile=0.55)
n.paint(lid, white)
keep(lid)
LT = TOP + 0.007 + LID                               # top of the lid
cross(0.13, 0.042, "XY", (0.0, 0.035, LT + 0.003), "CrossTop")
mounts = [n.box((0.028, 0.03, 0.016), at=(x, -0.06, LT + 0.006)) for x in (-0.07, 0.07)]
for m in mounts:
    n.bevel(m, width=0.004, segments=2, profile=0.55)
keep(n.merge_parts(mounts, name="HandleMounts", weld=False))
n.paint("HandleMounts", dark)
keep(n.handle(0.14, 0.04, 0.0085, axis="Z", at=(0, -0.06, LT + 0.012), name="Handle", material=dark))

# ---- grey latches over the band on the front
latches = []
for x in (-0.13, 0.13):
    l = n.box((0.04, 0.018, 0.056), at=(x, -D / 2 - 0.009, TOP + 0.004))
    n.mark_bevel(l)
    n.boolean_cut(l, n.box((0.024, 0.01, 0.008), at=(x, -D / 2 - 0.018, TOP - 0.01)))   # finger slot
    n.bevel(l, width=0.004, segments=2, profile=0.55, limit="weight")
    latches.append(l)
keep(n.merge_parts(latches, name="Latches", weld=False))
n.paint("Latches", grey)

n.ground(parts)
n.center(parts, "XY")
