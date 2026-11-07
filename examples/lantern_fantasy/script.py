# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized fantasy lantern: a chunky six-sided iron frame with glowing amber panes, brass bands and cross bars, a
stepped base with rivets, an overhanging roof with a brass trim, a finial and a big ring handle.
tags: lantern, lamp, light, fantasy, medieval, rpg, glow, emissive, iron, brass, stylized, cartoon, fortnite, prop
Hexagonal on purpose (lathe and cylinder with segments=6, posts on the corners, bars on the faces). Dark iron and warm
brass frame the bright panes, so the shape reads as a light source from far away.
budget: 2700 (a hand-held or wall prop, often many in a scene)
"""
import math

import nighty as n

n.settings(detail="low", size=0.4, collection="Lantern")
iron = n.surface("Lantern Iron", "iron", color="#3c4049", style="stylized")
brass = n.surface("Lantern Brass", "brass", color="#e0a640", style="stylized")
glow = n.surface("Lantern Glow", "glow", color="#ff7c0a", glow=1.3)   # deep amber, soft: stays warm
parts = []


def keep(obj):
    parts.append(obj)
    return obj


R = 0.082                                             # pane corner radius
Z0, Z1 = 0.045, 0.235                                 # panes bottom and top
CORNERS = [math.radians(60 * k) for k in range(6)]    # hex corners (lathe / cylinder with 6 segments put them here)
FACES = [math.radians(30 + 60 * k) for k in range(6)]  # hex face middles

# ---- stepped base with a rivet on each face
base = n.lathe([(0.0, 0.0), (0.118, 0.0), (0.118, 0.028), (0.1, 0.028), (0.1, Z0), (0.0, Z0)], segments=6,
               name="Base")
n.bevel(base, width=0.004, segments=2, profile=0.6)
n.paint(base, iron)
keep(base)
apo = 0.118 * math.cos(math.radians(30))
keep(n.merge_parts([n.dome(0.0075, height=0.004, segments=8, axis=(math.cos(a), math.sin(a), 0),
                           at=(apo * math.cos(a), apo * math.sin(a), 0.013)) for a in FACES],
                   name="Rivets", weld=False))
n.paint("Rivets", brass)

# ---- glowing panes, iron corner posts, brass bands top and bottom, a brass bar across each pane
keep(n.cylinder(R, Z1 - Z0, segments=6, at=(0, 0, (Z0 + Z1) / 2), name="Panes", material=glow))
posts = []
for a in CORNERS:
    p = n.box((0.02, 0.02, Z1 - Z0 + 0.01), at=(R * math.cos(a), R * math.sin(a), (Z0 + Z1) / 2),
              rot=(0, 0, math.degrees(a)))
    n.chamfer(p, 0.0025)
    posts.append(p)
keep(n.merge_parts(posts, name="Posts", weld=False))
n.paint("Posts", iron)
for z, name in ((Z0 + 0.008, "BandBottom"), (Z1 - 0.008, "BandTop")):
    band = n.lathe([(0.076, z - 0.009), (0.094, z - 0.009), (0.094, z + 0.009), (0.076, z + 0.009),
                    (0.076, z - 0.009)], segments=6, caps="none", name=name)   # a closed profile: a hex ring
    n.chamfer(band, 0.002)
    n.paint(band, brass)
    keep(band)
side = R * 0.92                                        # a hex face is as long as the corner radius
apo_p = R * math.cos(math.radians(30))
bars = []
for a in FACES:
    b = n.box((0.008, side, 0.012), at=(apo_p * math.cos(a), apo_p * math.sin(a), (Z0 + Z1) / 2),
              rot=(0, 0, math.degrees(a)))
    n.chamfer(b, 0.002)
    bars.append(b)
keep(n.merge_parts(bars, name="CrossBars", weld=False))
n.paint("CrossBars", iron)

# ---- roof with an overhang and a brass trim, finial, ring handle
roof = n.lathe([(0.0, Z1 - 0.004), (0.112, Z1 - 0.004), (0.116, Z1 + 0.012), (0.04, Z1 + 0.075),
                (0.018, Z1 + 0.09), (0.0, Z1 + 0.092)], segments=6, name="Roof")
n.bevel(roof, width=0.004, segments=2, profile=0.6)
n.paint(roof, iron)
keep(roof)
trim = n.lathe([(0.1, Z1 + 0.008), (0.119, Z1 + 0.008), (0.119, Z1 + 0.02), (0.1, Z1 + 0.02),
                (0.1, Z1 + 0.008)], segments=6, caps="none", name="RoofTrim")
n.chamfer(trim, 0.002)
n.paint(trim, brass)
keep(trim)
top = Z1 + 0.09
keep(n.sphere(0.02, segments=12, at=(0, 0, top + 0.014), name="Finial", material=brass))
ring = n.torus(0.042, 0.008, segments=20, ring_segments=10, axis="Y", at=(0, 0, top + 0.03 + 0.042 - 0.004),
               name="Ring", material=iron)
n.smooth_by_angle(ring, 60)                            # few sides, still round
keep(ring)

n.ground(parts)
n.center(parts, "XY")
