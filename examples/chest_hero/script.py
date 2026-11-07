# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized treasure chest (hero): chunky planked body with posts and rails, arched lid with plank seams, gold bands
with rivets, corner guards, lock plate with keyhole and a ruby hasp, ring handles, feet, and coins spilled beside it.
tags: chest, treasure, loot, box, wood, gold, stylized, cartoon, fortnite, roblox, hero, prop, fantasy, coins
Exaggerated, chunky proportions with soft painted highlights: warm wood, dark frame, bright gold, red ruby.
Game-ready: low detail, light rivets and nails, coins with 2-segment edges.
budget: 15000 (a hero prop; one Roblox mesh)
"""
import math

import nighty as n

n.settings(detail="low", size=0.75, collection="Chest")
plank_x = n.surface("Chest Planks X", "wood", color="#b06a33", grain="X", style="stylized")
plank_y = n.surface("Chest Planks Y", "wood", color="#b06a33", grain="Y", style="stylized")
frame_x = n.surface("Chest Frame X", "wood", color="#6e3d1e", grain="X", style="stylized")
frame_y = n.surface("Chest Frame Y", "wood", color="#6e3d1e", grain="Y", style="stylized")
frame_z = n.surface("Chest Frame Z", "wood", color="#6e3d1e", grain="Z", style="stylized")
gold = n.surface("Chest Gold", "gold", color="#f4b93a", style="stylized")
ruby = n.surface("Chest Ruby", "painted", color="#e3263f", style="stylized", roughness=0.15)
inner = n.surface("Chest Inner", "wood", color="#4a2914", style="stylized")
X, Y = 0.35, 0.225          # half sizes of the body
Z0, Z1 = 0.035, 0.33        # body bottom (on the feet) and top
F, T, R = 0.06, 0.024, 0.012   # post size, plank thickness, how far planks sit inside the frame
parts = []


def keep(obj):
    parts.append(obj)
    return obj


# ---- body: core, planks, posts and rails
keep(n.box((2 * (X - R - T), 2 * (Y - R - T), Z1 - Z0 - 0.006), at=(0, 0, (Z0 + Z1) / 2), name="Core", material=inner))
mid, h = (Z0 + Z1) / 2, Z1 - Z0 - 0.07
pl = []
for s in (-1, 1):
    pl.append(n.planks((2 * X - 2 * F + 0.02, h), count=3, thickness=T, gap=0.008, plane="XZ",
                       at=(0, s * (Y - R - T / 2), mid), seed=2 + s, name="Planks", material=plank_x))
    pl.append(n.planks((2 * Y - 2 * F + 0.02, h), count=3, thickness=T, gap=0.008, plane="YZ",
                       at=(s * (X - R - T / 2), 0, mid), seed=5 + s, name="Planks", material=plank_y))
keep(n.merge_parts(pl, name="BodyPlanks", weld=False))
fr = []
for a in (-1, 1):
    for b in (-1, 1):
        fr.append(n.rounded_box((F, F, Z1 - Z0), radius=0.012, at=(a * (X - F / 2), b * (Y - F / 2), mid),
                                material=frame_z))
for z, hh in ((Z0 + 0.025, 0.05), (Z1 - 0.02, 0.04)):
    for s in (-1, 1):
        fr.append(n.rounded_box((2 * X - 2 * F + 0.01, F * 0.8, hh), radius=0.01, at=(0, s * (Y - F * 0.4), z),
                                material=frame_x))
        fr.append(n.rounded_box((F * 0.8, 2 * Y - 2 * F + 0.01, hh), radius=0.01, at=(s * (X - F * 0.4), 0, z),
                                material=frame_y))
keep(n.merge_parts(fr, name="BodyFrame", weld=False))

# ---- arched lid: a base frame, the arch with plank seams, gold bands and end trims
ZL = Z1 + 0.035
keep(n.rounded_box((2 * X + 0.012, 2 * Y + 0.012, 0.035), radius=0.01, at=(0, 0, Z1 + 0.0175), name="LidFrame",
                   material=frame_x))
A, Bh, steps = Y + 0.004, 0.16, 16
arch = [(A * math.cos(math.pi * k / steps), ZL + Bh * math.sin(math.pi * k / steps)) for k in range(steps + 1)]
lid = n.extrude(arch + [(-A, ZL - 0.004), (A, ZL - 0.004)], depth=2 * X, plane="YZ", name="Lid")
for k in range(4, steps, 4):
    t = math.pi * k / steps
    yz = (A * math.cos(t), ZL + Bh * math.sin(t))
    n.groove(lid, [(-X + 0.002, yz[0], yz[1]), (X - 0.002, yz[0], yz[1])], width=0.007)
n.chunky(lid, 0.5)
n.paint(lid, plank_x)
keep(lid)


def arch_ring(width, x, out=0.009, inn=0.003, name="Band"):
    outer = [((A + out) * math.cos(math.pi * k / steps), ZL + (Bh + out) * math.sin(math.pi * k / steps))
             for k in range(steps + 1)]
    inner_ = [((A - inn) * math.cos(math.pi * k / steps), ZL + (Bh - inn) * math.sin(math.pi * k / steps))
              for k in range(steps, -1, -1)]
    ring = n.extrude(outer + inner_, depth=width, plane="YZ", at=(x, 0, 0), name=name)
    n.chunky(ring, 0.6, segments=2)
    n.paint(ring, gold)
    return keep(ring)


for x in (-0.2, 0.2):
    arch_ring(0.05, x, name="LidBand")
for x in (-X + 0.004, X - 0.004):
    arch_ring(0.016, x, out=0.006, name="LidTrim")
rivets = []
for x in (-0.2, 0.2):
    for k in range(3, steps, 4):
        t = math.pi * k / steps
        p = (x, (A + 0.009) * math.cos(t), ZL + (Bh + 0.009) * math.sin(t))
        rivets.append(n.dome(0.009, height=0.006, segments=8, axis=(0, math.cos(t) * Bh, math.sin(t) * A), at=p))
    for s in (-1, 1):
        for z in (Z0 + 0.09, Z0 + 0.19):
            rivets.append(n.dome(0.009, height=0.006, segments=8, axis=(0, s, 0), at=(x, s * (Y + 0.005), z)))
keep(n.merge_parts(rivets, name="Rivets", weld=False))
n.paint("Rivets", gold)

# ---- gold bands down the body, corner guards, lock and hasp with a ruby
bands = [n.box((0.05, 0.016, Z1 - Z0 + 0.006), at=(x, s * (Y - 0.003), mid))
         for x in (-0.2, 0.2) for s in (-1, 1)]
keep(n.merge_parts(bands, name="BodyBands", weld=False))
n.chunky("BodyBands", 0.5)
n.paint("BodyBands", gold)
guards = []
body_box = n.box((2 * X, 2 * Y, Z1 - Z0), at=(0, 0, mid), name="GuardShape")
for a in (-1, 1):
    for b in (-1, 1):
        for c in (-1, 1):
            guards.append(n.corner_bracket(body_box, (a, b, c), size=0.07, thickness=0.007, nails_per_face=1,
                                           nail_radius=0.007, name="Guard", material=gold))
n.delete(body_box)
keep(n.merge_parts(guards, name="CornerGuards", weld=False))
keep(n.merge_parts([o for o in n.objects() if o.name.startswith("GuardNails")], name="GuardNails", weld=False))
lock = n.extrude(n.rounded_rect(0.09, 0.1, 0.02), depth=0.012, plane="XZ", at=(0, -(Y + 0.006), Z1 - 0.055),
                 name="LockPlate")
n.boolean_cut(lock, n.cylinder(0.0095, 0.05, axis="Y", at=(0, -(Y + 0.006), Z1 - 0.045)))
n.boolean_cut(lock, n.box((0.008, 0.05, 0.026), at=(0, -(Y + 0.006), Z1 - 0.062)))
n.chunky(lock, 0.5)
n.paint(lock, gold)
keep(lock)
hasp = n.rounded_box((0.05, 0.012, 0.075), radius=0.008, at=(0, -(Y + 0.012), Z1 + 0.012), name="Hasp", material=gold)
keep(hasp)
gem = n.sphere(0.017, segments=8, kind="uv", at=(0, -(Y + 0.02), Z1 + 0.02), name="Ruby", material=ruby)
n.shade_flat(gem)
keep(gem)

# ---- ring handles, feet
for s in (-1, 1):
    keep(n.rounded_box((0.012, 0.09, 0.06), radius=0.004, at=(s * (X - R + 0.004), 0, Z1 - 0.075), name="HandlePlate",
                       material=gold))
    keep(n.torus(0.045, 0.009, axis="X", at=(s * (X - R + 0.014), 0, Z1 - 0.115), name="HandleRing",
                 material=gold))
for a in (-1, 1):
    for b in (-1, 1):
        keep(n.rounded_box((0.075, 0.075, Z0 + 0.004), radius=0.012, at=(a * (X - 0.03), b * (Y - 0.03), Z0 / 2),
                           name="Foot", material=frame_z))

# ---- coins spilled beside it
coins = []
for i, (x, y, z, tilt) in enumerate(((0.33, -0.36, 0.0, 0), (0.25, -0.33, 0.0, 0), (0.25, -0.33, 0.012, 9),
                                     (0.41, -0.29, 0.0, 0), (0.30, -0.25, 0.0, 0))):
    coin = n.cylinder(0.03, 0.01, at=(x, y, z + 0.005), rot=(tilt, 0, 0), name="Coin")
    n.chunky(coin, 0.8, segments=2)
    coins.append(coin)
keep(n.merge_parts(coins, name="Coins", weld=False))
n.paint("Coins", gold)

n.ground(parts)
n.center(parts, "XY")
