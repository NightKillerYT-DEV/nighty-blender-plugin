# SPDX-License-Identifier: GPL-3.0-or-later
"""LODs: copies of a finished mesh decimated by several ratios (UVs, seams and sharp edges are kept as well as a
collapse can). Named <name>_LOD1, _LOD2... (Unity / Unreal read the _LODn suffix); the original is LOD0."""

import time

import bpy

from . import _util as U
from .topo import decimate

DEFAULT_RATIOS = (0.5, 0.25, 0.1)


def make_lods(obj, ratios=None, faces=None, hide=True, progress=None):
    """Makes LOD copies of obj. ratios: fractions of obj's triangles (default 0.5, 0.25, 0.1) or faces: exact
    triangle counts. Existing <name>_LODn copies are replaced. Returns (lod objects, report)."""
    p = U.Progress(progress)
    t0 = time.monotonic()
    U.require_mesh(obj)
    from .stats import analyze
    base_tris = analyze(obj)["triangles"]
    targets = [int(f) for f in faces] if faces else [max(4, int(round(base_tris * float(r))))
                                                     for r in (ratios or DEFAULT_RATIOS)]
    for i in range(1, 12):  # replace old LODs
        old = bpy.data.objects.get(f"{obj.name}_LOD{i}")
        if old is not None and old.get("nighty_lod_of") == obj.name:
            me = old.data
            bpy.data.objects.remove(old)
            if me.users == 0:
                bpy.data.meshes.remove(me)
    lods, rows = [], [{"name": obj.name, "lod": 0, "triangles": base_tris}]
    obj["nighty_lod"] = 0
    for i, tgt in enumerate(targets, start=1):
        p((i - 1) / len(targets), f"LOD{i}")
        ob = obj.copy()
        ob.data = obj.data.copy()
        ob.name = f"{obj.name}_LOD{i}"
        ob.data.name = f"{obj.data.name}_LOD{i}"
        for k in ("nighty_bake_source", "nighty_high"):
            if k in ob:
                del ob[k]
        for m in list(ob.modifiers):  # LODs are plain meshes (a Triangulate-on-export modifier is kept)
            if m.type != 'TRIANGULATE':
                ob.modifiers.remove(m)
        for col in obj.users_collection or [bpy.context.scene.collection]:
            col.objects.link(ob)
        ob["nighty_lod"] = i
        ob["nighty_lod_of"] = obj.name
        if tgt < base_tris:
            decimate(ob, faces=tgt, symmetry="auto", planar=None, keep_sharp=35.0, keep_seams=True, protect=0.5)
        if hide:
            ob.hide_set(True)
        lods.append(ob)
        rows.append({"name": ob.name, "lod": i, "triangles": analyze(ob)["triangles"]})
    p(1.0, "done")
    return lods, {"lods": rows, "seconds": round(time.monotonic() - t0, 2),
                  "note": "LOD1+ are hidden in the viewport; exports pick them up by the _LODn names"}
