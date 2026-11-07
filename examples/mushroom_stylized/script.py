# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized toadstools on a mossy mound: one big and two small mushrooms with curled caps, raised white spots, warm
gills underneath, a frilled ring on the stem and a bulb at its foot, plus a few pebbles.
tags: mushroom, toadstool, amanita, stylized, cartoon, fantasy, nature, plant, forest, environment, fortnite, prop
Caps are lathe profiles (dome, rim, curl, underside in one), spots are domes set on the cap with n.place_on, each
mushroom leans a little for charm. Bright red caps against cream stems and green moss; hand-painted look.
budget: 5500 (a nature prop cluster)
"""
import math
import random

import nighty as n

n.settings(detail="low", size=0.5, collection="Mushrooms")
red = n.surface("Mushroom Cap", "plastic", color="#e5352b", style="stylized", roughness=0.45)
spot = n.surface("Mushroom Spots", "plastic", color="#fff4e0", style="stylized", roughness=0.6)
stem = n.surface("Mushroom Stem", "plastic", color="#f1e2c2", style="stylized", roughness=0.7)
gill = n.surface("Mushroom Gills", "plastic", color="#e6ae7c", style="stylized", roughness=0.8)
moss = n.surface("Mushroom Moss", "plastic", color="#5c9c32", wear=0.0, dirt=0.15, roughness=0.9)   # soft, no edge lines
grass = n.surface("Mushroom Grass", "plastic", color="#6fb83a", wear=0.0, dirt=0.0, roughness=0.7)  # thin: no edge paint
pebble = n.surface("Mushroom Pebbles", "stone", color="#a29d92", style="stylized")
parts = []


def keep(obj):
    parts.append(obj)
    return obj


def mushroom(s, at, lean, spots, seed, name):
    """A toadstool of scale s standing at (x, y, z), leaning lean degrees; returns its parts."""
    x0, y0, z0 = at
    rs, L = 0.032 * s, 0.24 * s                       # stem radius and length
    R, H = 0.15 * s, 0.11 * s                         # cap radius and height above its rim
    seg = 32 if s > 0.7 else 20                       # sides: fewer on the small ones
    body = n.lathe(n.spline([(1.4 * rs, 0.0), (1.45 * rs, 0.07 * L), (1.05 * rs, 0.3 * L), (0.92 * rs, 0.72 * L),
                             (0.95 * rs, L)], samples=2) + [(0.0, L)], segments=16, at=(x0, y0, z0),
                  name=name + "Stem")
    n.paint(body, stem)
    ring = n.lathe([(0.97 * rs, 0.8 * L), (1.75 * rs, 0.69 * L), (1.7 * rs, 0.65 * L), (0.97 * rs, 0.74 * L),
                    (0.97 * rs, 0.8 * L)], segments=16, caps="none", at=(x0, y0, z0),
                  name=name + "Ring")                 # a profile ending where it starts: a closed frill
    n.paint(ring, spot)
    Z = z0 + L - 0.02 * s                             # the rim's height
    top = n.spline([(0.0, H), (0.5 * R, 0.9 * H), (0.85 * R, 0.55 * H), (1.0 * R, 0.12 * H)], samples=3)
    cap = n.lathe(top + [(1.03 * R, 0.0), (0.97 * R, -0.07 * H), (0.82 * R, -0.05 * H), (1.2 * rs, 0.16 * H),
                         (0.0, 0.18 * H)], segments=seg, at=(x0, y0, Z), name=name + "Cap")
    n.paint(cap, red)
    under = [p.index for p in cap.data.polygons if p.normal.z < -0.2]
    n.paint(cap, gill, faces=under)
    rnd = random.Random(seed)
    dots = []
    for k in range(spots):                            # spots spread over the top, bigger near the middle
        th = math.radians(10 + 62 * (k + rnd.random() * 0.6) / spots)
        ph = k * 2.4 + rnd.uniform(-0.3, 0.3)
        p = (x0 + 1.6 * R * math.sin(th) * math.cos(ph), y0 + 1.6 * R * math.sin(th) * math.sin(ph),
             Z + 1.6 * H * math.cos(th))
        r = (0.026 - 0.01 * th) * s
        d = n.lathe([(r, 0.0), (0.78 * r, 0.28 * r), (0.0, 0.38 * r)], segments=12, at=p)   # a light round spot
        n.place_on(d, cap, direction=(x0 - p[0], y0 - p[1], Z + 0.3 * H - p[2]), offset=-0.0015 * s)
        dots.append(d)
    dots = n.merge_parts(dots, name=name + "Spots", weld=False)
    n.paint(dots, spot)
    group = [body, ring, cap, dots]
    a = math.radians(rnd.uniform(0, 360))
    n.rotate(group, lean, axis=(math.cos(a), math.sin(a), 0), pivot=(x0, y0, z0))
    return group


# ---- a mossy mound with three mushrooms and pebbles
MH = 0.085                                            # mound height


def mound_z(x, y):                                    # the mound's height at (x, y), before the noise
    return MH * math.sqrt(max(0.0, 1.0 - (x / 0.375) ** 2 - (y / 0.3) ** 2))


mound = n.dome(0.3, height=MH, segments=32, caps="fan", name="Mound")   # fan: the bottom stays flat-safe
mound.scale = (1.25, 1.0, 1.0)
n.apply_transforms(mound)
n.displace(mound, strength=0.01, scale=0.09, octaves=2, seed=2)
n.paint(mound, moss)
keep(mound)
for s, x, y, lean, k in ((1.0, -0.04, 0.02, 4, 9), (0.62, 0.19, -0.08, 12, 6), (0.4, 0.04, -0.16, -14, 4)):
    at = (x, y, mound_z(x, y) - 0.025)                # stems start inside the mound
    for obj in mushroom(s, at, lean, k, seed=k, name="Toadstool" if s == 1.0 else "Toadstool%d" % k):
        keep(obj)
stones = []
for k, (x, y, r) in enumerate(((-0.25, -0.08, 0.035), (-0.21, -0.15, 0.022), (0.28, 0.08, 0.028))):
    st = n.sphere(r, segments=8, at=(x, y, mound_z(x, y) - 0.004))
    st.scale = (1.3, 1.0, 0.65)
    n.apply_transforms(st)
    n.displace(st, strength=r * 0.25, scale=r, octaves=1, seed=k)
    n.shade_flat(st)
    stones.append(st)
keep(n.merge_parts(stones, name="Pebbles", weld=False))
n.paint("Pebbles", pebble)


# ---- grass tufts: flat pointed blades fanned around a point, leaning out
blades = []
rnd = random.Random(5)
for cx, cy, count in ((-0.14, -0.07, 8), (0.1, 0.11, 7), (0.27, -0.12, 6), (-0.21, 0.11, 7), (0.0, -0.22, 5)):
    for k in range(count):
        h = rnd.uniform(0.06, 0.1)
        w = h * 0.2
        blades.append(n.extrude([(-w, 0.0), (w, 0.0), (w * 0.45, h * 0.6), (0.0, h)], depth=0.006,
                                at=(cx, cy, mound_z(cx, cy) - 0.015),
                                rot=(rnd.uniform(14, 30), 0, k * 360 / count + rnd.uniform(-15, 15))))
keep(n.merge_parts(blades, name="Grass", weld=False))
n.paint("Grass", grass)

n.ground(parts)
n.center(parts, "XY")
