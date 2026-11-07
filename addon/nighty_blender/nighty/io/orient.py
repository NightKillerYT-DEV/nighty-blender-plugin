# SPDX-License-Identifier: GPL-3.0-or-later
"""Which way an imported model faces (numpy; used by import_file.py after the model is stood upright, only when asked).

One rule for every model, the one nighty's examples and guides use (Z up, front -Y, right +X; a gun lies along X
with its muzzle at +X, so the front view shows its side; a chest or a bench is wide along X and faces -Y):

- not clearly long (its longer side under 1.6x the shorter): it stays as it is; its front faces -Y.
- clearly long: its long side runs along X and its front end (a gun's muzzle, a blade's tip, a car's nose) points
  to +X.

Where the front end is: most model files use a canonical frame whose front faces -Y, so a long model along Y turns
+90 degrees (front -Y -> +X). A model in a camera's frame (pixel_aligned) has its front end found from the shape:
the thinner end (the muzzle end, not the stock; the tip, not the hilt); when the two ends are too alike it is left
as it is.
"""

import math

import numpy as np

LONG = 1.6        # long side / short side above this: a long model
END = 0.15        # the share of the length looked at on each end
ALIKE = 0.85      # end sizes closer than this ratio: no thinner end


def _end_sizes(co, axis):
    """Cross-section size (the other horizontal extent x height) of the last END of the length at each end."""
    u = co[:, axis]
    lo, hi = u.min(), u.max()
    span = hi - lo or 1.0
    other = 1 - axis
    out = []
    for m in (u <= lo + span * END, u >= hi - span * END):
        p = co[m]
        if len(p) < 3:
            out.append(0.0)
            continue
        out.append(float((p[:, other].max() - p[:, other].min()) * (p[:, 2].max() - p[:, 2].min())))
    return out          # [at the - end, at the + end]


def facing(co, pixel_aligned=False):
    """(turn about Z in degrees, info) for vertices co (n, 3) of an upright model."""
    co = np.asarray(co, dtype=np.float64).reshape(-1, 3)
    if len(co) < 4:
        return 0, {"facing": "too few vertices", "turned_deg": 0}
    ext = co.max(axis=0) - co.min(axis=0)
    ex, ey = float(ext[0]), float(ext[1])
    if max(ex, ey) < LONG * max(min(ex, ey), 1e-9):
        return 0, {"facing": "front -Y (not a long model)", "turned_deg": 0}
    axis = 0 if ex >= ey else 1
    if not pixel_aligned:
        # canonical frame: the front faces -Y; a long model along Y turns its front end to +X
        turn = 90 if axis == 1 else 0
        return turn, {"facing": "long along X, front end at +X" if turn else "long along X (front -Y kept)",
                      "turned_deg": turn}
    neg, pos = _end_sizes(co, axis)
    small, big = min(neg, pos), max(neg, pos)
    if big <= 0 or small / big > ALIKE:
        turn = 90 if axis == 1 else 0       # long along X; the ends look alike: which end is the front is unknown
        return turn, {"facing": "long along X (its ends look alike: front end not known)", "turned_deg": turn,
                      "ends": [round(neg, 6), round(pos, 6)]}
    front_neg = neg < pos                   # the thinner end is the front end
    if axis == 0:
        turn = 180 if front_neg else 0
    else:
        turn = 90 if front_neg else -90     # -Y -> +X is +90; +Y -> +X is -90
    return turn, {"facing": "long along X, front end (the thinner one) at +X", "turned_deg": turn,
                  "ends": [round(neg, 6), round(pos, 6)]}


def turn_matrix(deg):
    """3x3 rotation about Z."""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]
