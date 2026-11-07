# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings (detail level, asset size), sides for round shapes, objects, collections and bounds."""

import math

import bpy
import bmesh
from mathutils import Euler, Matrix, Vector

from . import compat

__all__ = ["settings", "segments", "bevel_segments", "get", "objects", "collection", "bounds", "Bounds",
           "to_list", "update"]

# Detail levels: sides of round shapes grow with the square root of how big the circle shows on screen (its radius
# in pixels when the whole asset fills about 1000 px), between a minimum and a maximum, always a multiple of 4
# (clean quads; mirror and booleans line up). Never 8-sided by default.
DETAIL = {
    "low": {"min": 12, "max": 32, "k": 3.0, "bevel": 2},
    "medium": {"min": 16, "max": 64, "k": 5.0, "bevel": 4},
    "high": {"min": 24, "max": 128, "k": 8.0, "bevel": 6},
}
ALIASES = {"low_poly": "low", "lowpoly": "low", "mid": "medium", "med": "medium", "hi": "high", "ultra": "high"}

_S = {"detail": "medium", "size": 1.0, "collection": None}


def settings(detail=None, size=None, collection=None):
    """Global defaults for everything made after it. Returns the current settings.

    detail: "low" | "medium" | "high" (how many sides round shapes get, bevel segments).
    size: the asset's overall size in meters (a pistol 0.25, a rifle 0.9, a crate 0.6, a door 2.1).
    collection: name of the collection new objects go into (default: the active one).

        n.settings(detail="high", size=0.9, collection="Rifle")
    """
    if detail is not None:
        key = ALIASES.get(str(detail).lower(), str(detail).lower())
        if key not in DETAIL:
            raise ValueError(f"detail must be one of {sorted(DETAIL)}, not {detail!r}")
        _S["detail"] = key
    if size is not None:
        if not size > 0:
            raise ValueError("size must be > 0 (meters)")
        _S["size"] = float(size)
    if collection is not None:
        _S["collection"] = collection or None
    return dict(_S)


def _detail(detail=None):
    key = ALIASES.get(str(detail).lower(), str(detail).lower()) if detail else _S["detail"]
    if key not in DETAIL:
        raise ValueError(f"detail must be one of {sorted(DETAIL)}, not {detail!r}")
    return DETAIL[key]


def segments(radius, detail=None, size=None, arc=360.0):
    """Sides for a circle (or an arc, degrees) of this radius: enough for how big it shows, a multiple of 4.

        n.segments(0.0095)           # a rifle barrel (asset size 0.9 m) at medium detail -> 20
        n.segments(0.3, "low")       # a big barrel (size 1 m) at low detail -> 32
    """
    d = _detail(detail)
    size = float(size or _S["size"])
    r_px = abs(float(radius)) / size * 1000.0
    frac = arc / 360.0
    count = math.ceil(d["k"] * math.sqrt(max(r_px, 0.0)) * frac)
    low = max(2 if frac < 1 else 4, round(d["min"] * frac))
    high = max(low, round(d["max"] * frac))
    count = min(max(count, low), high)
    if arc >= 360.0:
        count = int(math.ceil(count / 4.0) * 4)
    return int(count)


def bevel_segments(detail=None):
    """Bevel segments of a detail level (even, so corners stay quads): low 2, medium 4, high 6."""
    return _detail(detail)["bevel"]


# ---------- objects ----------

def get(name):
    """An object by name (or the object itself). Raises a clear error when it doesn't exist."""
    if isinstance(name, bpy.types.Object):
        return name
    obj = bpy.data.objects.get(str(name))
    if obj is None:
        raise KeyError(f"no object named {name!r}")
    return obj


def to_list(objs):
    """One object, a name, or a list of them -> a list of objects."""
    if objs is None:
        return []
    if isinstance(objs, (str, bpy.types.Object)):
        return [get(objs)]
    return [get(o) for o in objs]


def objects(kind="MESH", collection=None, visible=True):
    """Objects in the scene (or a collection) of a type ("MESH", "ALL"), skipping Nighty's helpers."""
    scene = bpy.context.scene
    pool = collection_get(collection).all_objects if collection else scene.objects
    out = []
    for obj in pool:
        if kind != "ALL" and obj.type != kind:
            continue
        if obj.get("nighty_role") in ("cutter", "reference", "ghost", "helper", "outline"):
            continue
        if visible and not _visible(obj):
            continue
        out.append(obj)
    return out


def _visible(obj):
    try:
        return obj.visible_get()
    except RuntimeError:
        return not obj.hide_viewport


def collection_get(name):
    if isinstance(name, bpy.types.Collection):
        return name
    coll = bpy.data.collections.get(name)
    if coll is None:
        raise KeyError(f"no collection named {name!r}")
    return coll


def collection(name, parent=None):
    """A collection by name, made and linked under the scene (or parent) when missing.

        coll = n.collection("Rifle")
    """
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
    parent_coll = collection(parent) if isinstance(parent, str) else (parent or bpy.context.scene.collection)
    if coll.name not in parent_coll.children and coll != parent_coll:
        if not _linked_somewhere(coll):
            parent_coll.children.link(coll)
    return coll


def _linked_somewhere(coll):
    scene_coll = bpy.context.scene.collection
    return coll.name in scene_coll.children or any(coll.name in c.children for c in bpy.data.collections)


def _target_collection(name=None):
    name = name or _S["collection"]
    if name:
        return collection(name) if isinstance(name, str) else name
    try:
        return bpy.context.view_layer.active_layer_collection.collection
    except AttributeError:
        return bpy.context.scene.collection


def new_object(name, data, at=(0, 0, 0), rot=None, collection=None, parent=None, material=None):
    """Links a new object for mesh / curve data. rot: degrees (x, y, z)."""
    obj = bpy.data.objects.new(name, data)
    _target_collection(collection).objects.link(obj)
    obj.location = Vector(at)
    if rot is not None:
        obj.rotation_euler = Euler([math.radians(a) for a in rot], "XYZ")
    if parent is not None:
        p = get(parent)
        obj.parent = p
        obj.matrix_parent_inverse = p.matrix_world.inverted()
    if material is not None:
        from .paint import paint
        paint(obj, material)
    return obj


def mesh_object(bm, name, at=(0, 0, 0), rot=None, collection=None, parent=None, material=None, smooth=30.0):
    """bmesh -> a new mesh object (normals fixed, smooth by angle unless smooth is None / False)."""
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        compat.shade_smooth(me, angle=30.0 if smooth is True else float(smooth))
    else:
        compat.shade_flat(me)
    return new_object(name, me, at=at, rot=rot, collection=collection, parent=parent, material=material)


def update():
    """Updates matrices and modifiers (after moving things, before measuring)."""
    bpy.context.view_layer.update()


# ---------- bounds ----------

class Bounds:
    """A world-space box: .min .max .size .center (Vectors), .top .bottom (z), .corners()."""

    __slots__ = ("min", "max")

    def __init__(self, lo, hi):
        self.min, self.max = Vector(lo), Vector(hi)

    @property
    def size(self):
        return self.max - self.min

    @property
    def center(self):
        return (self.min + self.max) * 0.5

    @property
    def top(self):
        return self.max.z

    @property
    def bottom(self):
        return self.min.z

    def corners(self):
        lo, hi = self.min, self.max
        return [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]

    def __repr__(self):
        r = lambda v: tuple(round(c, 4) for c in v)
        return f"Bounds(min={r(self.min)}, max={r(self.max)}, size={r(self.size)})"


def world_points(obj, evaluated=True, depsgraph=None):
    """World coordinates of an object's (evaluated) vertices as an (n, 3) numpy array (bound box for non-meshes)."""
    import numpy as np
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    ob = obj.evaluated_get(dg) if evaluated else obj
    mw = np.array(obj.matrix_world, dtype=np.float64)
    if obj.type == "MESH":
        me = ob.data if evaluated else obj.data
        n = len(me.vertices)
        if n:
            co = np.empty(n * 3, dtype=np.float32)
            me.vertices.foreach_get("co", co)
            co = co.reshape(-1, 3).astype(np.float64)
            return co @ mw[:3, :3].T + mw[:3, 3]
    corners = np.array([tuple(c) for c in ob.bound_box], dtype=np.float64)
    if not len(corners):
        return np.zeros((0, 3))
    return corners @ mw[:3, :3].T + mw[:3, 3]


def bounds(objs, evaluated=True):
    """World bounds of objects (with modifiers by default), from their vertices.

        b = n.bounds(body); print(b.size, b.top)
    """
    import numpy as np
    objs = to_list(objs)
    if not objs:
        raise ValueError("bounds() needs at least one object")
    update()
    dg = bpy.context.evaluated_depsgraph_get()
    pts = [world_points(o, evaluated, dg) for o in objs]
    pts = [p for p in pts if len(p)]
    if not pts:
        loc = objs[0].matrix_world.translation
        return Bounds(loc, loc)
    allp = np.concatenate(pts)
    return Bounds(allp.min(axis=0), allp.max(axis=0))


def axis_vector(axis):
    """"X" / "-Y" / "+Z" (or any direction (x, y, z)) -> a unit Vector."""
    if not isinstance(axis, str):
        v = Vector(axis)
        if v.length < 1e-12:
            raise ValueError("a direction needs a length")
        return v.normalized()
    a = str(axis).upper().strip()
    sign = -1.0 if a.startswith("-") else 1.0
    a = a.lstrip("+-")
    idx = "XYZ".index(a)
    v = Vector((0.0, 0.0, 0.0))
    v[idx] = sign
    return v


def axis_matrix(axis):
    """Rotation that turns +Z into the given axis ("X", "-Y"... or a direction (x, y, z)), as a 4x4 Matrix."""
    target = axis_vector(axis)
    z = Vector((0, 0, 1))
    if (target - z).length < 1e-9:
        return Matrix.Identity(4)
    if (target + z).length < 1e-9:
        return Matrix.Rotation(math.pi, 4, "X")
    return z.rotation_difference(target).to_matrix().to_4x4()
