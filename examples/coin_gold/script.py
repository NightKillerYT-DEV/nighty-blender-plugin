# SPDX-License-Identifier: GPL-3.0-or-later
"""Stylized gold coins (pickup size, 12 cm): thick chunky coins with a bright raised rim, a deeper gold field and a
star in relief; one stands up facing you, one lies flat, and a short stack sits behind them.
tags: coin, gold, money, currency, treasure, loot, pickup, item, reward, fantasy, game, stylized, cartoon, roblox
Two golds (bright rim and star, deeper field) give the relief value contrast; hidden stack coins are plain discs.
Game pickups are big on purpose: the painted edge highlights stay a thin line instead of covering a tiny coin.
budget: 2500 (six pickup coins; low detail, one-segment chamfers)
"""
import math

import nighty as n

n.settings(detail="low", size=0.3, collection="Coins")
bright = n.surface("Coin Gold", "gold", color="#ffc843", style="stylized", roughness=0.4)
deep = n.surface("Coin Gold Deep", "gold", color="#d48f22", style="stylized", roughness=0.6)
R, T, SEG = 0.06, 0.02, 24   # coin radius, thickness, sides
parts = []


def star(points=5, outer=0.035, inner=0.015):
    out = []
    for k in range(points * 2):
        a = math.pi / 2 + math.pi * k / points
        r = outer if k % 2 == 0 else inner
        out.append((r * math.cos(a), r * math.sin(a)))
    return out


def coin(at, name, emblem=True):
    """One coin lying flat at at (its center). emblem: rim, field and star (else a plain chamfered disc)."""
    if not emblem:
        disc = n.cylinder(R, T, segments=SEG, at=at, name=name)
        n.chamfer(disc, 0.0045)
        n.paint(disc, bright)
        return disc
    rim = n.tube(R, T, inner=R - 0.011, segments=SEG, at=at, name=name)
    n.chamfer(rim, 0.004)
    n.paint(rim, bright)
    field = n.cylinder(R - 0.0108, T - 0.0055, segments=SEG, at=at, material=deep)       # 2.7 mm below the rim
    relief = n.extrude(star(), depth=T - 0.0022, plane="XY", at=at, material=bright)  # 1.6 mm proud of the field
    n.chamfer(relief, 0.0016)
    return n.merge_parts([rim, field, relief], name=name, weld=False)


# a stack of four (only the top one shows a face), one lying flat, one standing up against the stack
for k in range(4):
    c = coin((0.048 + 0.0025 * (k % 2), 0.056, T / 2 + k * T), f"StackCoin{k + 1}", emblem=(k == 3))
    n.rotate(c, 17 * k, "Z")
    parts.append(c)
flat = coin((0.12, -0.048, T / 2), "FlatCoin")
n.rotate(flat, 40, "Z")
parts.append(flat)
TILT = 12                          # leaning back a little; the center height keeps its edge 0.5 mm in the ground
lean = math.radians(TILT)
hero = coin((-0.048, -0.016, R * math.cos(lean) + T / 2 * math.sin(lean) - 0.0005), "Coin")
n.rotate(hero, 90, "X")            # on its edge, the face toward -Y (the camera side)
n.rotate(hero, -TILT, "X")
n.rotate(hero, 20, "Z")
parts.append(hero)

n.ground(parts)
n.center(parts, "XY")
