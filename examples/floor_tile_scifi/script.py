# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized sci-fi floor tile (modular, 2 x 2 m): a dark slab, white border plates, a grey frame around a slotted
grate over a glowing underlay, glowing strips in the gaps around the frame, amber corner plates with bolts.
tags: scifi, sci-fi, floor, tile, grate, modular, kit, environment, level design, spaceship, emissive, stylized
Tiles on a 2 m grid: pivot at the slab's bottom center, nothing sticks out past the 2 x 2 m edges, the slab's chunky
edges make the seam between tiles. Layers step up (slab, frame, plates, corner plates) so it reads from above.
budget: 5200 (a floor piece repeated across a level)
"""
import nighty as n

S = 2.0                     # tile size
n.settings(detail="low", size=S, collection="FloorTile")
dark = n.surface("Tile Dark", "plastic", color="#2b2f37", style="stylized")
white = n.surface("Tile White", "plastic", color="#e6eaef", style="stylized")
grey = n.surface("Tile Grey", "plastic", color="#9aa6b5", style="stylized")
amber = n.surface("Tile Amber", "plastic", color="#ffb020", style="stylized")
steel = n.surface("Tile Steel", "steel", color="#b4bcc6", style="stylized")
glow = n.surface("Tile Glow", "glow", color="#2fe0ff", glow=5)
parts = []


def keep(obj):
    parts.append(obj)
    return obj


SLAB, G, F = 0.08, 0.96, 0.55          # slab height, grate size, frame half size

# ---- slab: the tile itself
slab = n.box((S, S, SLAB), at=(0, 0, SLAB / 2), name="Slab")
n.bevel(slab, width=0.012, segments=2)
n.paint(slab, dark)
keep(slab)

# ---- center: glowing underlay, a slotted grate over it (slots go through), a grey frame around it
keep(n.box((G, G, 0.004), at=(0, 0, SLAB + 0.0015), name="Underglow", material=glow))
grate = n.box((G, G, 0.022), at=(0, 0, SLAB + 0.0035 + 0.011), name="Grate")
n.mark_bevel(grate)
n.vents(grate, "+Z", center=(0, 0), count=9, slot=(0.8, 0.045), gap=0.03, depth=0.03)
n.bevel(grate, width=0.004, segments=2, limit="weight")
n.paint(grate, dark)
keep(grate)
frame = n.extrude(n.rounded_rect(2 * F, 2 * F, 0.03), holes=[n.rounded_rect(G + 0.002, G + 0.002, 0.004)],
                  depth=0.034, plane="XY", at=(0, 0, SLAB + 0.017 - 0.003), name="GrateFrame")
n.bevel(frame, width=0.006, segments=2, profile=0.55)
n.paint(frame, grey)
keep(frame)

# ---- white border plates around the frame, glowing strips in the gaps between them and the frame
P, GAP, E = 0.025, 0.012, S / 2 - 0.02      # plate height, gap, plate outer edge
plates = []
w = E - F - GAP
for s in (-1, 1):   # tread grooves across each plate (crisp: cut after marking the outline)
    ns = n.box((2 * E, w, P), at=(0, s * (F + GAP + w / 2), SLAB + P / 2 - 0.003))              # north / south
    n.mark_bevel(ns)
    n.vents(ns, "+Z", center=(0, s * (F + GAP + w / 2)), count=5, slot=(0.03, 0.26), gap=0.07, direction="u",
            depth=0.008)
    ew = n.box((w, 2 * F, P), at=(s * (F + GAP + w / 2), 0, SLAB + P / 2 - 0.003))              # east / west
    n.mark_bevel(ew)
    n.vents(ew, "+Z", center=(s * (F + GAP + w / 2), 0), count=5, slot=(0.26, 0.03), gap=0.07, direction="v",
            depth=0.008)
    plates += [ns, ew]
for p in plates:
    n.bevel(p, width=0.008, segments=2, profile=0.55, limit="weight")
keep(n.merge_parts(plates, name="BorderPlates", weld=False))
n.paint("BorderPlates", white)
strips = []
for s in (-1, 1):
    strips.append(n.box((2 * F, 0.006, 0.006), at=(0, s * (F + GAP / 2), SLAB + 0.002)))
    strips.append(n.box((0.006, 2 * F, 0.006), at=(s * (F + GAP / 2), 0, SLAB + 0.002)))
keep(n.merge_parts(strips, name="GlowStrips", weld=False))
n.paint("GlowStrips", glow)

# ---- amber corner plates with dark hazard stripes, one bolt each
C, TOPP = 0.3, SLAB + P - 0.003                  # corner plate size, top of the border plates
corners, stripes, bolts = [], [], []
for sx in (-1, 1):
    for sy in (-1, 1):
        cx, cy = sx * (E - C / 2 - 0.03), sy * (E - C / 2 - 0.03)
        c = n.box((C, C, 0.014), at=(cx, cy, TOPP + 0.005))
        n.bevel(c, width=0.005, segments=2, profile=0.55)
        corners.append(c)
        for d in (-0.075, 0.0, 0.075):           # raised stripes pointing at the tile corner (chunky: stay dark)
            length = 0.25 - 2 * abs(d)
            stripe = n.box((length, 0.04, 0.012), rot=(0, 0, 45 * sx * sy),
                           at=(cx + sx * d * 0.7071, cy - sy * d * 0.7071, TOPP + 0.015))
            n.chamfer(stripe, 0.002)
            stripes.append(stripe)
        bolts.append(n.bolt(0.02, kind="hex", axis="Z", at=(cx + sx * 0.105, cy - sy * 0.105, TOPP + 0.012)))
keep(n.merge_parts(stripes, name="HazardStripes", weld=False))
n.paint("HazardStripes", dark)
keep(n.merge_parts(corners, name="CornerPlates", weld=False))
n.paint("CornerPlates", amber)
keep(n.merge_parts(bolts, name="Bolts", weld=False))
n.paint("Bolts", steel)
# no n.ground / n.center: the tile keeps its exact grid placement (bottom center at the origin)
