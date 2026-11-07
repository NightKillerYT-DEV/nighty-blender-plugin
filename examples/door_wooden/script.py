# SPDX-License-Identifier: GPL-3.0-or-later
"""Realistic four-panel oak door in a painted frame: real stile-and-rail construction with fielded (chamfered) panels,
jambs with door stops, molded casing with a backband on both faces, an oak threshold, brass levers with rosettes,
key escutcheons, a kick plate and three hinges.
tags: realistic, door, wooden door, panel door, entrance, frame, casing, interior, architecture, house, hinges, handle, oak
Opening 0.9 x 2.05 m, door 45 mm thick. Every board is its own piece with its grain along its length (stiles and the
mullion up, rails across), so it reads like joinery; the panels sit 10 mm back in the frame on both faces.
budget: 5000 (a medium game prop / modular door)
"""
import nighty as n

n.settings(detail="low", size=2.2, collection="Door")
oak_up = n.surface("Door Oak Up", "wood", color="#6e4426", grain="Z", wear=0.0, dirt=0.25)   # varnished: no worn edges
oak_across = n.surface("Door Oak Across", "wood", color="#6e4426", grain="X", wear=0.0, dirt=0.25)
paint = n.surface("Door Frame Paint", "painted_wood", color="#ebe6dc", wear=0.12, dirt=0.2)
sill = n.surface("Door Threshold", "wood", color="#8a6a48", grain="X", wear=0.3, dirt=0.4)
brass = n.surface("Door Brass", "brass", wear=0.15, dirt=0.45, roughness=0.38, size=0.5)

OW, OH = 0.9, 2.05          # the opening
JW, JD = 0.03, 0.14         # jamb thickness and depth (the wall's thickness)
DT = 0.045                  # door thickness
GAP = 0.003                 # gap around the door
SILL = 0.02                 # threshold height
W, H = OW - 2 * GAP, OH - SILL - GAP     # the door slab
X0, Z0 = -W / 2, SILL + GAP / 2           # its lower left corner
ST, RT, RM, RB = 0.12, 0.12, 0.17, 0.22   # stile width, top / middle / bottom rail heights
MID = 0.95                                # middle rail center height above the door's bottom

# ---- the door: stiles, rails, mullion, fielded panels
door = []
for sx in (-1, 1):
    door.append(n.box((ST, DT, H), at=(sx * (W / 2 - ST / 2), 0, Z0 + H / 2), bevel=0.003, material=oak_up))
rails = [(Z0 + RB / 2, RB), (Z0 + MID, RM), (Z0 + H - RT / 2, RT)]
for zc, rh in rails:        # rails fit between the stiles (end grain against the stiles' sides)
    door.append(n.box((W - 2 * ST, DT, rh), at=(0, 0, zc), bevel=0.003, material=oak_across))
MW = 0.1                    # mullion between the panel pairs
openings = [(Z0 + RB, Z0 + MID - RM / 2), (Z0 + MID + RM / 2, Z0 + H - RT)]
PW = (W - 2 * ST - MW) / 2  # panel opening width
for z0, z1 in openings:
    door.append(n.box((MW, DT, z1 - z0), at=(0, 0, (z0 + z1) / 2), bevel=0.003, material=oak_up))
    for sx in (-1, 1):      # a 16 mm panel let 6 mm into the frame, with a raised field 10 mm back from each face
        px, pz, ph = sx * (MW / 2 + PW / 2), (z0 + z1) / 2, z1 - z0
        panel = n.box((PW + 0.012, 0.016, ph + 0.012), at=(px, 0, pz))
        field = n.box((PW - 0.07, 0.025, ph - 0.07), at=(px, 0, pz))
        n.chamfer(field, 0.016)                  # the field's wide bevel catches the light
        n.paint([panel, field], oak_up)
        door += [panel, field]
door = n.merge_parts(door, name="Door", weld=False)

# ---- frame: jambs and head, door stops, threshold
frame = [n.box((JW, JD, OH), at=(sx * (OW / 2 + JW / 2), 0, OH / 2), bevel=0.002) for sx in (-1, 1)]
frame.append(n.box((OW + 2 * JW, JD, JW), at=(0, 0, OH + JW / 2), bevel=0.002))
STOP_Y = DT / 2 + 0.006     # stops behind the closed door (+Y side)
for sx in (-1, 1):
    frame.append(n.box((0.012, 0.035, OH - SILL - 0.012), at=(sx * (OW / 2 - 0.006), STOP_Y + 0.0175,
                                                             SILL + (OH - SILL - 0.012) / 2), bevel=0.002))
frame.append(n.box((OW, 0.035, 0.012), at=(0, STOP_Y + 0.0175, OH - 0.006), bevel=0.002))
# ---- casing on both wall faces: a flat board plus a thicker backband on its outer edge (a molded profile)
CW, CT, BB = 0.075, 0.014, 0.02
for sy in (-1, 1):
    y = sy * (JD / 2 + CT / 2)
    top = OH + 0.006 + CW                        # the head casing sits on the legs
    for sx in (-1, 1):
        x = sx * (OW / 2 + 0.006 + CW / 2 - 0.006)
        frame.append(n.box((CW, CT, top - CW), at=(x, y, (top - CW) / 2), bevel=0.003))
        frame.append(n.box((BB, CT + 0.01, top), at=(x + sx * (CW / 2 + BB / 2), sy * (JD / 2 + (CT + 0.01) / 2),
                                                    top / 2), bevel=0.003))
    span = OW + 2 * CW + 2 * BB
    frame.append(n.box((span - 2 * BB, CT, CW), at=(0, y, top - CW / 2), bevel=0.003))
    frame.append(n.box((span, CT + 0.01, BB), at=(0, sy * (JD / 2 + (CT + 0.01) / 2), top + BB / 2), bevel=0.003))
frame = n.merge_parts(frame, name="Frame", weld=False)
n.paint(frame, paint)
threshold = n.box((OW + 2 * JW + 0.04, JD + 0.03, SILL), at=(0, 0, SILL / 2), name="Threshold", material=sill)
n.chamfer(threshold, 0.006)

# ---- hardware: levers with rosettes and key escutcheons on both faces, a kick plate, hinges
HX, HZ = W / 2 - ST / 2, Z0 + 1.0 - Z0   # lever on the lock stile, 1 m up


def lever(sy):
    y0 = sy * DT / 2
    rose = n.cylinder(0.026, 0.008, axis="Y", at=(HX, y0 + sy * 0.004, HZ))
    n.bevel(rose, width=0.002)
    neck = n.cylinder(0.009, 0.045, axis="Y", at=(HX, y0 + sy * 0.03, HZ))
    bar = n.cylinder(0.0095, 0.13, axis="X", at=(HX - 0.055, y0 + sy * 0.052, HZ))  # a capsule would be 1000 tris
    n.bevel(bar, width=0.005)                                                    # rounded ends
    plate = n.box((0.036, 0.006, 0.072), at=(HX, y0 + sy * 0.003, HZ - 0.115))
    n.bevel(plate, width=0.0025)
    n.boolean_cut(plate, n.cylinder(0.0045, 0.02, axis="Y", at=(HX, y0, HZ - 0.105)))      # keyhole: round top
    n.boolean_cut(plate, n.box((0.004, 0.02, 0.016), at=(HX, y0, HZ - 0.115)))             # and the slot
    return [rose, neck, bar, plate]


hardware = lever(-1) + lever(1)
kick = n.box((W - 0.06, 0.004, 0.16), at=(0, -DT / 2 - 0.0015, Z0 + 0.11))             # 0.5 mm into the door
n.bevel(kick, width=0.0015)
hardware.append(kick)
for z in (Z0 + 0.25, Z0 + 1.0, Z0 + H - 0.25):
    knuckle = n.cylinder(0.009, 0.1, at=(-OW / 2, -DT / 2 + 0.004, z))
    hardware.append(knuckle)
    for dz in (-0.055, 0.055):               # finials on both ends of the knuckle
        hardware.append(n.cone(0.009, 0.01, top=0.004, axis="Z" if dz > 0 else "-Z",
                               at=(-OW / 2, -DT / 2 + 0.004, z + dz)))
hardware = n.merge_parts(hardware, name="Hardware", weld=False)
n.paint(hardware, brass)

parts = [door, frame, threshold, hardware]
n.ground(parts)
n.center(parts, "XY")
