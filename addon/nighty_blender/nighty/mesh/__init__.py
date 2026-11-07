# SPDX-License-Identifier: GPL-3.0-or-later
"""nighty.mesh: cleanup, retopology, low poly, parts, UVs and LODs for generated (or any) meshes.

Use it from run_python (blocking, in this Blender) or through the tools (cleanup_mesh, retopo, decimate,
split_parts, uv_unwrap, make_lods), which run the same functions in a background Blender so the UI never freezes.

    import nighty.mesh as nm
    nm.cleanup(obj, size=0.9)                       # weld, floaters, holes, manifold, 0.9 m long, on the ground
    nm.retopo(obj, mode="quads", detail="medium")   # quads keeping sharp edges; dense original kept as bake source
    nm.decimate(obj, faces=5000)                    # low poly to an exact triangle count
    parts = nm.split_parts(obj, method="concave")   # barrel, scope, grip... as separate objects
    nm.uv_unwrap(parts, texture_size=2048)          # one shared atlas, even texel density, no overlaps
    nm.make_lods(obj, ratios=[0.5, 0.25, 0.1])
"""

from .stats import analyze, surface_error, sharp_segments, sharp_kept, short
from .shape import classify, symmetry
from .fix import cleanup, weld, remove_floaters, fill_holes, recalc_normals, voxel_remesh, set_size, ground
from .topo import (retopo, decimate, quadriflow, reproject, bake_source, keep_bake_source, DETAIL_TRIANGLES,
                     detail_faces)
from .parts import split_parts, register_segmenter, segmenters
from .uv import uv_unwrap, uv_report, uv_overlap
from .lods import make_lods
from . import external

__all__ = [
    "analyze", "surface_error", "sharp_segments", "sharp_kept", "short", "classify", "symmetry",
    "cleanup", "weld", "remove_floaters", "fill_holes", "recalc_normals", "voxel_remesh", "set_size", "ground",
    "retopo", "decimate", "quadriflow", "reproject", "bake_source", "keep_bake_source", "DETAIL_TRIANGLES",
    "detail_faces", "split_parts", "register_segmenter", "segmenters", "uv_unwrap", "uv_report", "uv_overlap",
    "make_lods", "external",
]
