# SPDX-License-Identifier: GPL-3.0-or-later
"""Realistic AR-15 carbine (hero): receivers with ejection port, dust cover, forward assist, brass deflector,
free-float M-LOK handguard, compensator with ports, red-dot sight, PMAG, knurled grip, castle nut, ribbed
adjustable stock. Black receivers against FDE (tan) furniture, so every detail reads.
tags: gun, rifle, assault rifle, carbine, ar15, m4, weapon, realistic, hero, hard-surface, firearm, military, fps
About 95 parts from a real parts list (0.88 m), cerakote / polymer / parkerized materials with worn edges; muzzle +X.
Game-ready: low detail (2-segment bevels, weighted normals), texture-sized details left to the materials.
budget: 20000 (one Roblox mesh; a third-person or mobile FPS weapon)
"""
import math

import nighty as n

n.settings(detail="low", size=0.9, collection="Rifle")
BORE = 0.0185                      # barrel axis height above the upper receiver's bottom
# size=0.35 + low wear: fine, patchy edge wear (a rifle wears in thin lines; thin walls and rail teeth stay dark)
anod = n.surface("AR Cerakote", "painted_metal", color="#33363b", wear=0.15, size=0.35)
poly = n.surface("AR Polymer", "polymer", color="#26272a", wear=0.35)
fde = n.surface("AR FDE", "polymer", color="#a08866", wear=0.4)
park = n.surface("AR Parkerized", "gunmetal", wear=0.25, size=0.35)
steel = n.surface("AR Steel", "steel", wear=0.2, size=0.35)
rubber = n.surface("AR Rubber", "rubber")
glass = n.surface("AR Lens", "glass", color="#9fd6c8")
dot = n.surface("AR Dot", "glow", color="#ff2a1a", glow=25)
parts = []


def keep(*objs):
    parts.extend(objs)
    return objs[0] if len(objs) == 1 else objs


# ---------------- upper receiver ----------------
upper = n.extrude([(-0.135, 0.0, 0.002), (0.095, 0.0, 0.002), (0.095, 0.040, 0.002), (-0.124, 0.040, 0.003),
                   (-0.135, 0.032, 0.003)], depth=0.026, name="UpperReceiver")
n.mark_bevel(upper)   # bevel the big outline edges only; ports, panels and slots cut after stay crisp (fewer triangles)
n.boolean_cut(upper, n.rounded_box((0.052, 0.006, 0.016), radius=0.002, at=(-0.03, -0.013, 0.022)))  # port
n.panel_cut(upper, "+Y", center=(-0.02, 0.022), size=(0.15, 0.026), groove=0.0012, radius=0.004)
n.panel_cut(upper, "-Y", center=(-0.095, 0.026), size=(0.03, 0.02), groove=0.0012, radius=0.003)
n.bevel(upper, width=0.0013, limit="weight")
n.paint(upper, anod)
keep(upper)
cover = keep(n.rounded_box((0.049, 0.0016, 0.0135), radius=0.0006, at=(-0.03, -0.01085, 0.022), name="DustCover",
                           material=anod))
keep(n.box((0.012, 0.002, 0.003), at=(-0.012, -0.0122, 0.026), bevel=0.0004, name="CoverLatch", material=steel))
keep(n.cylinder(0.0012, 0.052, axis="X", at=(-0.03, -0.0132, 0.0125), name="CoverHinge", material=steel))
deflector = n.rounded_box((0.016, 0.008, 0.02), radius=0.003, at=(-0.064, -0.0145, 0.025), name="BrassDeflector")
n.paint(deflector, anod)
keep(deflector)
fa_dir = (-0.55, -0.83, 0.0)
keep(n.cylinder(0.0085, 0.022, axis=fa_dir, at=(-0.108, -0.017, 0.023), name="AssistHousing", material=anod))
plunger = n.cylinder(0.0058, 0.016, axis=fa_dir, at=(-0.1135, -0.0262, 0.023), name="AssistPlunger",
                     material=steel)
n.bevel(plunger, width=0.0006)
keep(plunger)
keep(n.rail(0.23, at=(-0.02, 0, 0.0398), name="TopRail", material=anod))
handle = n.rounded_box((0.011, 0.054, 0.0075), radius=0.0025, at=(-0.1415, 0, 0.034), name="ChargingHandle",
                       material=anod)
keep(handle)
keep(n.rounded_box((0.008, 0.006, 0.006), radius=0.0015, at=(-0.141, 0.029, 0.0345), name="ChargingLatch",
                   material=anod))

# ---------------- lower receiver ----------------
lower = n.extrude([(-0.150, 0.036, 0.004), (-0.150, -0.012, 0.004), (-0.128, -0.030, 0.006), (-0.004, -0.030, 0.0),
                   (-0.004, -0.074, 0.003), (0.072, -0.074, 0.003), (0.080, -0.012, 0.008), (0.080, 0.0, 0.0),
                   (-0.135, 0.0, 0.0), (-0.135, 0.036, 0.002)], depth=0.028, name="LowerReceiver")
n.mark_bevel(lower)
n.panel_cut(lower, "-Y", center=(0.034, -0.05), size=(0.054, 0.03), groove=0.0014, radius=0.004)
n.panel_cut(lower, "+Y", center=(0.034, -0.05), size=(0.054, 0.03), groove=0.0014, radius=0.004)
n.bevel(lower, width=0.0013, limit="weight")
n.paint(lower, anod)
keep(lower)
flare = n.extrude(n.rounded_rect(0.086, 0.034, 0.006), holes=[n.rounded_rect(0.07, 0.022, 0.003)], depth=0.008,
                  plane="XY", at=(0.034, 0, -0.0705), name="MagwellFlare")
n.bevel(flare, width=0.0012)
n.paint(flare, anod)
keep(flare)
guard = keep(n.pipe([(-0.006, 0, -0.066), (-0.05, 0, -0.066), (-0.063, 0, -0.04)], radius=0.0036, bend=0.009,
                    name="TriggerGuard", material=anod))
trigger = n.extrude(n.spline([(-0.021, -0.028), (-0.023, -0.042), (-0.029, -0.052), (-0.036, -0.053)]) +
                    [(-0.031, -0.042), (-0.029, -0.028)], depth=0.0055, name="Trigger", material=steel)
n.bevel(trigger, width=0.0005)
keep(trigger)
pins = [n.cylinder(0.0026, 0.0305, axis="Y", at=p) for p in ((-0.141, 0, -0.004), (0.072, 0, -0.006),
                                                               (-0.08, 0, -0.019), (-0.047, 0, -0.019))]
for p in pins:
    n.bevel(p, width=0.0005)
keep(n.merge_parts(pins, name="Pins", weld=False))
n.paint("Pins", steel)
keep(n.cylinder(0.0042, 0.0045, axis="-Y", at=(0.03, -0.0158, -0.045), name="MagRelease", material=steel))
keep(n.torus(0.0068, 0.0013, axis="Y", at=(0.03, -0.0142, -0.045), name="ReleaseFence", material=anod))
catch = n.extrude([(-0.008, -0.012), (0.012, -0.016), (0.012, -0.026), (-0.006, -0.024)], depth=0.003,
                  plane="XZ", at=(0.0, 0.0154, 0.0), name="BoltCatch", material=anod)
n.bevel(catch, width=0.0005)
keep(catch)
selector = n.rounded_box((0.024, 0.0032, 0.0075), radius=0.0012, at=(-0.1, 0.0155, -0.012), rot=(0, 12, 0),
                         name="Selector", material=steel)
keep(selector)
keep(n.cylinder(0.0045, 0.002, axis="Y", at=(-0.09, 0.0145, -0.011), name="SelectorHub", material=steel))

# ---------------- pistol grip ----------------
grip = n.extrude([(-0.052, -0.024, 0.0), (-0.061, -0.058, 0.01), (-0.066, -0.07, 0.008), (-0.071, -0.083, 0.01),
                  (-0.088, -0.122, 0.008), (-0.137, -0.118, 0.012), (-0.121, -0.06, 0.02), (-0.106, -0.030, 0.006),
                  (-0.112, -0.021, 0.004), (-0.098, -0.024, 0.0)], depth=0.031, name="PistolGrip")
n.mark_bevel(grip)
for side in ("-Y", "+Y"):   # grip panels: the stipple texture comes from the polymer material
    n.panel_cut(grip, side, center=(-0.103, -0.078), size=(0.03, 0.058), groove=0.0012, radius=0.006)
n.bevel(grip, width=0.0018, limit="weight")
n.paint(grip, fde)
keep(grip)
keep(n.rounded_box((0.052, 0.034, 0.006), radius=0.002, at=(-0.108, 0, -0.1185), rot=(0, 2, 0), name="GripCap",
                   material=fde))

# ---------------- buffer tube, castle nut, stock ----------------
keep(n.cylinder(0.0145, 0.195, axis="X", at=(-0.2375, 0, BORE), name="BufferTube", material=anod))
nut = n.cylinder(0.0178, 0.009, axis="X", at=(-0.1565, 0, BORE), name="CastleNut")
notch = n.box((0.005, 0.006, 0.006), at=(-0.1595, 0, BORE + 0.0172))
n.radial(notch, 6, axis="X", center=(0, 0, BORE))
n.boolean_cut(nut, notch)
n.bevel(nut, width=0.0005)
n.paint(nut, park)
keep(nut)
plate = n.extrude(n.rounded_rect(0.034, 0.034, 0.006), depth=0.003, plane="YZ", at=(-0.1515, 0, BORE - 0.004),
                  name="EndPlate", material=anod)
n.bevel(plate, width=0.0006)
keep(plate)
keep(n.torus(0.006, 0.0015, axis="X", arc=200, at=(-0.1515, 0.012, BORE - 0.024), name="SlingLoop",
             material=steel))
# adjustable stock: a round housing over the buffer tube, a tall butt, ribbed pockets in the web, sling slot
housing = n.cylinder(0.0215, 0.132, axis="X", at=(-0.338, 0, BORE), name="StockHousing")
n.bevel(housing, width=0.003)
n.paint(housing, fde)
keep(housing)
stock = n.extrude([(-0.276, BORE, 0.0), (-0.396, BORE, 0.0), (-0.404, 0.047, 0.004), (-0.431, 0.047, 0.005),
                   (-0.431, -0.070, 0.006), (-0.405, -0.075, 0.004), (-0.300, -0.007, 0.012), (-0.276, -0.004, 0.004)],
                  depth=0.040, name="Stock")
n.mark_bevel(stock)
TOP = 0.007                                                    # top of the ribbed pocket, just under the housing


def web_bottom(x):                                             # the pocket's lower edge, parallel to the stock's
    return -0.075 + 0.648 * (x + 0.405) + 0.011


pocket = [(-0.398, TOP, 0.003), (-0.398, web_bottom(-0.398), 0.003), (-0.314, web_bottom(-0.314), 0.003),
          (-0.314, TOP, 0.003)]
for y in (0.02, -0.02):
    n.boolean_cut(stock, n.extrude(pocket, depth=0.012, at=(0, y, 0)))
n.boolean_cut(stock, n.rounded_box((0.0065, 0.06, 0.026), radius=0.003, at=(-0.419, 0, -0.044)))   # sling slot
n.bevel(stock, width=0.0018, limit="weight")
n.paint(stock, fde)
keep(stock)
ribs = []
for x in (-0.386, -0.373, -0.360, -0.347, -0.334, -0.322):
    lo = web_bottom(x) + 0.0005
    for y in (0.0172, -0.0172):
        r = n.box((0.0028, 0.0056, TOP - lo), at=(x, y, (TOP + lo) / 2))
        n.chamfer(r, 0.0007)
        ribs.append(r)
keep(n.merge_parts(ribs, name="StockRibs", weld=False))
n.paint("StockRibs", fde)
lever = n.rounded_box((0.034, 0.012, 0.007), radius=0.002, at=(-0.296, 0, -0.0085), rot=(0, 3, 0),
                      name="StockLever", material=poly)
keep(lever)
keep(n.cylinder(0.0035, 0.0422, axis="Y", at=(-0.281, 0, -0.0035), name="LeverPin", material=steel))
pad = n.box((0.016, 0.046, 0.124), at=(-0.4385, 0, -0.012), name="ButtPad")
n.mark_bevel(pad)
n.vents(pad, "-X", count=6, slot=(0.034, 0.005), gap=0.012, depth=0.002)
n.bevel(pad, width=0.003, limit="weight")
n.paint(pad, rubber)
keep(pad)

# ---------------- handguard, barrel, compensator ----------------
hg = n.tube(0.0225, 0.37, inner=0.017, axis="X", at=(0.28, 0, BORE), name="Handguard")
n.mark_bevel(hg)
for side in ("-Y", "+Y"):
    n.vents(hg, side, center=(0.29, BORE), count=7, slot=(0.032, 0.0072), gap=0.0135,
            direction="u", depth=0.009)                     # M-LOK slots (through the wall)
n.bevel(hg, width=0.0009, limit="weight")
n.paint(hg, anod)
keep(hg)
keep(n.rail(0.36, at=(0.28, 0, 0.0398), name="HandguardRail", material=anod))
keep(n.bolts_along((0.108, -0.0207, BORE - 0.007), (0.124, -0.0207, BORE - 0.007), 2, radius=0.0026,
                   kind="socket", axis="-Y", name="HandguardScrews", material=steel))
keep(n.cylinder(0.0095, 0.425, axis="X", at=(0.3075, 0, BORE), name="Barrel", material=park))
keep(n.tube(0.0122, 0.002, inner=0.0074, axis="X", at=(0.521, 0, BORE), name="CrushWasher", material=steel))
comp = n.cylinder(0.0115, 0.058, axis="X", at=(0.551, 0, BORE), name="Compensator")
n.mark_bevel(comp)
for side, count in (("+Z", 3), ("-Y", 2), ("+Y", 2)):
    center = (0.556, 0.0) if side == "+Z" else (0.556, BORE)
    n.vents(comp, side, center=center, count=count, slot=(0.007, 0.011), gap=0.0055, direction="u", depth=0.006)
n.hole(comp, 0.0052, at=(0.58, 0, BORE), axis="X", depth=0.012)
n.bevel(comp, width=0.0008, limit="weight")
n.paint(comp, park)
keep(comp)

# ---------------- optic and backup sights ----------------
RAIL_TOP = 0.0398 + 0.0094
mount = n.rounded_box((0.036, 0.03, 0.012), radius=0.002, at=(-0.03, 0, RAIL_TOP + 0.006), name="OpticMount",
                      material=anod)
keep(mount)
keep(n.bolts_along((-0.042, -0.0152, RAIL_TOP + 0.005), (-0.018, -0.0152, RAIL_TOP + 0.005), 2, radius=0.0022,
                   kind="socket", axis="-Y", name="MountScrews", material=steel))
body = n.tube(0.0165, 0.064, inner=0.011, axis="X", at=(-0.03, 0, RAIL_TOP + 0.012 + 0.0165), name="OpticBody")
n.bevel(body, width=0.0008)
n.paint(body, anod)
keep(body)
OPT = RAIL_TOP + 0.012 + 0.0165
lenses = n.merge_parts([n.cylinder(0.0111, 0.0016, axis="X", at=(x, 0, OPT)) for x in (0.0, -0.058)],
                       name="OpticLenses", weld=False)
n.paint(lenses, glass)
keep(lenses)
keep(n.sphere(0.0009, at=(-0.0575, 0, OPT), name="RedDot", material=dot))
top_turret = n.cylinder(0.0062, 0.0075, at=(-0.03, 0, OPT + 0.0165 + 0.0025), name="TopTurret")
n.vents(top_turret, "+Y", count=5, slot=(0.0012, 0.006), direction="u", gap=0.0011, depth=0.0006)
n.bevel(top_turret, width=0.0005)
n.paint(top_turret, anod)
keep(top_turret)
side_turret = n.cylinder(0.0062, 0.0075, axis="-Y", at=(-0.03, -0.0165 - 0.0025, OPT), name="SideTurret")
n.bevel(side_turret, width=0.0005)
n.paint(side_turret, anod)
keep(side_turret)
for x, name in ((-0.112, "RearSight"), (0.44, "FrontSight")):
    s = n.rounded_box((0.022, 0.024, 0.009), radius=0.002, at=(x, 0, RAIL_TOP + 0.0045), name=name, material=anod)
    keep(s)

# ---------------- angled foregrip and weapon light ----------------
afg = n.extrude([(0.25, 0.0, 0.004), (0.33, 0.0, 0.004), (0.315, -0.024, 0.008), (0.268, -0.036, 0.01),
                 (0.252, -0.03, 0.006)], depth=0.026, at=(0, 0, BORE - 0.0228), name="Foregrip")
n.vents(afg, "-Z", count=3, slot=(0.004, 0.018), gap=0.008, direction="u", depth=0.0012)
n.bevel(afg, width=0.002)
n.paint(afg, fde)
keep(afg)
light_mount = n.rounded_box((0.03, 0.009, 0.014), radius=0.002, at=(0.39, -0.0255, BORE), name="LightMount",
                            material=anod)
keep(light_mount)
torch = n.lathe([(0.0, 0.0), (0.0108, 0.0), (0.0108, 0.004), (0.0098, 0.006), (0.0098, 0.05), (0.0118, 0.056),
                 (0.0128, 0.072), (0.0105, 0.075), (0.0, 0.075)], axis="X", at=(0.36, -0.0402, BORE),
                name="WeaponLight")
n.bevel(torch, width=0.0006)
n.paint(torch, anod)
keep(torch)
keep(n.cylinder(0.0098, 0.0016, axis="X", at=(0.4345, -0.0402, BORE), name="LightLens",
                material=n.surface("AR Light Lens", "glow", color="#fff4d8", glow=4)))
keep(n.torus(0.0099, 0.0009, axis="X", at=(0.384, -0.0402, BORE), name="LightGrip", material=anod))

# ---------------- magazine (PMAG) ----------------
back = n.spline([(0.0, -0.06), (0.004, -0.12), (0.016, -0.18), (0.034, -0.236)], samples=4)
front = n.spline([(0.094, -0.216), (0.078, -0.16), (0.068, -0.11), (0.066, -0.06)], samples=4)
mag = n.extrude(back + front, depth=0.0235, name="Magazine")
n.mark_bevel(mag)
for side in ("-Y", "+Y"):
    n.vents(mag, side, center=(0.05, -0.2), count=3, slot=(0.05, 0.0032), gap=0.0055, depth=0.0012)
    n.panel_cut(mag, side, center=(0.037, -0.115), size=(0.026, 0.06), groove=0.0016, radius=0.006)
n.bevel(mag, width=0.0011, limit="weight")
n.paint(mag, fde)
keep(mag)
base = n.rounded_box((0.074, 0.029, 0.011), radius=0.003, at=(0.0632, 0, -0.2295), rot=(0, -18.4, 0),
                     name="MagBase", material=fde)
keep(base)

n.ground(parts)
n.center(parts, "XY")
