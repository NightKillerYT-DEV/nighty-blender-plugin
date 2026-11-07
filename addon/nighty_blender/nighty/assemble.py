# SPDX-License-Identifier: GPL-3.0-or-later
"""Parts: names, collections, parents, copies, and merging parts into one mesh."""

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

from . import core
from .core import get, to_list

__all__ = ["part", "parent", "duplicate", "delete", "merge_parts", "group"]


def part(obj, name=None, collection=None, role=None):
    """Names a part and moves it into a collection (made when missing). role: a tag kept on the object.

        n.part(barrel, "Barrel", collection="Rifle")
    """
    obj = get(obj)
    if name:
        obj.name = name
        if obj.data is not None and obj.data.users == 1:
            obj.data.name = name
    if collection:
        coll = core.collection(collection) if isinstance(collection, str) else collection
        for c in list(obj.users_collection):
            if c != coll:
                c.objects.unlink(obj)
        if obj.name not in coll.objects:
            coll.objects.link(obj)
    if role:
        obj["nighty_part"] = str(role)
    return obj


def group(objs, collection):
    """Puts objects into one collection (made when missing). Returns the collection."""
    coll = core.collection(collection)
    for o in to_list(objs):
        part(o, collection=coll)
    return coll


def parent(child, parent_obj, keep_transform=True):
    """Parents child (or a list) to parent_obj, keeping where they are."""
    p = get(parent_obj)
    core.update()
    for c in to_list(child):
        mw = c.matrix_world.copy()
        c.parent = p
        if keep_transform:
            c.matrix_parent_inverse = p.matrix_world.inverted()
            c.matrix_world = mw
    core.update()
    return child


def duplicate(obj, at=None, rot=None, linked=False, name=None, mirror_x=False):
    """A copy of an object (its own mesh unless linked), optionally moved / turned (degrees) / mirrored across X=0.

        right_leg = n.duplicate(left_leg, at=(0.25, 0.2, 0.2))
    """
    import math
    src = get(obj)
    new = src.copy()
    if src.data is not None and not linked:
        new.data = src.data.copy()
    new.name = name or src.name
    for c in src.users_collection:
        c.objects.link(new)
    if at is not None:
        new.location = Vector(at)
    if rot is not None:
        new.rotation_euler = Euler([math.radians(a) for a in rot], "XYZ")
    if mirror_x and new.type == "MESH":
        new.data.transform(Matrix.Scale(-1, 4, (1, 0, 0)))
        new.data.flip_normals()
        new.location.x = -new.location.x
        new.data.update()
    core.update()
    return new


def delete(objs):
    """Deletes objects and their meshes when nothing else uses them."""
    for o in to_list(objs):
        data = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)


def merge_parts(objs, name=None, weld=True, distance=1e-5, keep=False):
    """Joins parts into one mesh object (modifiers applied, materials kept), optionally welding touching vertices.

    The first object becomes the merged one (its origin stays). keep=True leaves the originals.
    Parts that only overlap stay separate shells; use n.boolean_union for one watertight piece.

        gun = n.merge_parts([receiver, barrel, grip, stock], name="Rifle")
    """
    from .modify import apply_modifiers
    objs = [o for o in to_list(objs) if o.type == "MESH"]
    if not objs:
        raise ValueError("merge_parts needs mesh objects")
    core.update()
    if keep:
        objs = [duplicate(o, name=o.name + "_merge") for o in objs]
    for o in objs:
        if o.modifiers:
            apply_modifiers(o)
        if o.data.users > 1:
            o.data = o.data.copy()
    first = objs[0]
    if len(objs) > 1:
        for o in objs[1:]:
            for c in o.children:
                if c not in objs:
                    mw = c.matrix_world.copy()
                    c.parent = first
                    c.matrix_parent_inverse = first.matrix_world.inverted()
                    c.matrix_world = mw
        with bpy.context.temp_override(active_object=first, object=first, selected_objects=objs,
                                       selected_editable_objects=objs):
            bpy.ops.object.join()
    if weld:
        bm = bmesh.new()
        bm.from_mesh(first.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=float(distance))
        bm.to_mesh(first.data)
        bm.free()
        first.data.update()
    if name:
        first.name = name
        first.data.name = name
    if not first.data.has_custom_normals:
        from .modify import _reshade
        _reshade(first)
    core.update()
    return first
