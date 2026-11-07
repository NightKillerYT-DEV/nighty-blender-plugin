# SPDX-License-Identifier: GPL-3.0-or-later
"""nighty: building blocks for clean, good-looking models in Blender 4.2 to 5.x (import nighty as n).

    import nighty as n
    n.settings(detail="medium", size=0.9)              # how fine, and how big the asset is (meters)
    body = n.rounded_box((0.32, 0.05, 0.09), radius=0.006, name="Receiver")
    barrel = n.cylinder(0.011, 0.42, axis="X", name="Barrel")
    n.align(barrel, body, "right")                     # touching the receiver's right side, centered
    n.bevel(body)                                      # bevel + weighted normals + smooth shading
    print(n.verify([body, barrel])["errors"])          # the verify_mesh report

Round shapes get enough sides for their size (never 8), quads where it matters, transforms applied.
Front = -Y, right = +X, up = +Z. n.help() lists everything; n.help("cylinder") shows one.
"""

from . import compat
from .core import *          # settings, segments, bevel_segments, get, objects, collection, bounds, Bounds
from .shapes import *        # box, rounded_box, cylinder, tube, cone, sphere, dome, capsule, torus, plane, lathe...
from .modify import *        # bevel, weighted_normals, smooth_by_angle, mirror, array, boolean_cut, panel_cut...
from .place import *         # align, snap, stack, distribute, ground, center, apply_transforms, scale_to
from .assemble import *      # part, group, parent, duplicate, delete, merge_parts
from .details import *       # bolt, rivets, rail, handle, text3d
from .kit import *           # bolts_along / around, nails, groove, grille, knurl, cable, planks, corner_bracket...
from .surface import *       # surface: procedural metals, polymer, wood... realistic or stylized
from .paint import *         # material, paint, hex_color
from .check import *         # verify, measure, distance, compare
from . import check, core, kit, view  # (n.surface is the function; the module is nighty.surface)

VERSION = (1, 0, 0)

# ---- other areas add their import here, one line each (nighty.mesh, nighty.materials, nighty.bake, ...) ----
from . import mesh   # b-topo (not in SAFE_NIGHTY: it starts a background Blender)
from . import materials, bake, export, presets   # b-texture (not in SAFE_NIGHTY: they write files / start a process)
from . import colors   # b-color (clean colors for AI models; the clean_colors tool is the way in)


def help(name=None):
    """Lists nighty's functions with their first doc line, or the full doc of one: n.help("cylinder")."""
    import inspect
    import sys
    mod = sys.modules[__name__]
    if name is not None:
        fn = getattr(mod, name) if isinstance(name, str) else name
        sig = ""
        try:
            sig = str(inspect.signature(fn))
        except (TypeError, ValueError):
            pass
        return f"{getattr(fn, '__name__', name)}{sig}\n{inspect.getdoc(fn) or ''}"
    lines = []
    for key in sorted(dir(mod)):
        if key.startswith("_"):
            continue
        fn = getattr(mod, key)
        if callable(fn) and getattr(fn, "__module__", "").startswith(__name__) and not isinstance(fn, type):
            doc = (inspect.getdoc(fn) or "").split("\n")[0]
            lines.append(f"{key}: {doc}")
    return "\n".join(lines)
