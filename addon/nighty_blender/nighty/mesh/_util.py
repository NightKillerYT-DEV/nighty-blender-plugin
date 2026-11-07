# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared helpers for nighty.mesh: fast numpy reads of mesh data, small object utilities and the few
Blender 4.2 / 5.x differences this package meets (all in one place)."""

import math
import time

import bpy
import bmesh
import numpy as np

VERSION = bpy.app.version


# ---------------------------------------------------------------- numpy views of a mesh

def verts(me):
    """Vertex positions (n, 3) float64, in the mesh's own space."""
    co = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    return co.reshape(-1, 3).astype(np.float64)


def set_verts(me, co):
    me.vertices.foreach_set("co", np.ascontiguousarray(co, dtype=np.float32).ravel())
    me.update()


# foreach_get is a plain memory copy only when the buffer has Blender's own type (int32 / float32 / bool)

def edges(me):
    e = np.empty(len(me.edges) * 2, dtype=np.int32)
    me.edges.foreach_get("vertices", e)
    return e.reshape(-1, 2).astype(np.int64)


def polys(me):
    """(loop_start, loop_total, loop_vert, loop_edge) as int arrays."""
    n = len(me.polygons)
    start = np.empty(n, dtype=np.int32)
    total = np.empty(n, dtype=np.int32)
    me.polygons.foreach_get("loop_start", start)
    me.polygons.foreach_get("loop_total", total)
    nl = len(me.loops)
    lv = np.empty(nl, dtype=np.int32)
    le = np.empty(nl, dtype=np.int32)
    me.loops.foreach_get("vertex_index", lv)
    me.loops.foreach_get("edge_index", le)
    return start.astype(np.int64), total.astype(np.int64), lv.astype(np.int64), le.astype(np.int64)


def loop_face(start, total):
    """For every loop, the index of its face."""
    return np.repeat(np.arange(len(start)), total)


def tris(me):
    """Triangulation (t, 3) vertex indices and the face of each triangle."""
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    v = np.empty(n * 3, dtype=np.int32)
    p = np.empty(n, dtype=np.int32)
    me.loop_triangles.foreach_get("vertices", v)
    me.loop_triangles.foreach_get("polygon_index", p)
    return v.reshape(-1, 3).astype(np.int64), p.astype(np.int64)


def tri_loops(me):
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    lo = np.empty(n * 3, dtype=np.int32)
    me.loop_triangles.foreach_get("loops", lo)
    return lo.reshape(-1, 3).astype(np.int64)


def face_normals(me):
    n = np.empty(len(me.polygons) * 3, dtype=np.float32)
    me.polygons.foreach_get("normal", n)
    return n.reshape(-1, 3).astype(np.float64)


def face_centers(me):
    c = np.empty(len(me.polygons) * 3, dtype=np.float32)
    me.polygons.foreach_get("center", c)
    return c.reshape(-1, 3).astype(np.float64)


def face_areas(me):
    a = np.empty(len(me.polygons), dtype=np.float32)
    me.polygons.foreach_get("area", a)
    return a.astype(np.float64)


def edge_flags(me, name):
    """'use_seam' / 'use_edge_sharp' per edge as a bool array."""
    f = np.zeros(len(me.edges), dtype=bool)
    if len(me.edges):
        me.edges.foreach_get(name, f)
    return f


def face_materials(me):
    m = np.zeros(len(me.polygons), dtype=np.int32)
    if len(me.polygons):
        me.polygons.foreach_get("material_index", m)
    return m.astype(np.int64)


def edge_faces(me, start=None, total=None, le=None):
    """Edge -> faces table for edges used by exactly 2 faces: (edge_ids, face_a, face_b), plus the face count of
    every edge."""
    if le is None:
        start, total, _lv, le = polys(me)
    lf = loop_face(start, total)
    count = np.bincount(le, minlength=len(me.edges))
    order = np.argsort(le, kind="stable")
    le_s, lf_s = le[order], lf[order]
    two = np.nonzero(count == 2)[0]
    first = np.searchsorted(le_s, two)
    return two, lf_s[first], lf_s[first + 1], count


def dihedral(me, start=None, total=None, le=None):
    """For manifold edges: (edge_ids, angle in degrees between the face normals, concave flag)."""
    ids, fa, fb, _count = edge_faces(me, start, total, le)
    if len(ids) == 0:
        return ids, np.zeros(0), np.zeros(0, dtype=bool)
    n = face_normals(me)
    c = face_centers(me)
    dots = np.clip(np.einsum("ij,ij->i", n[fa], n[fb]), -1.0, 1.0)
    ang = np.degrees(np.arccos(dots))
    concave = np.einsum("ij,ij->i", n[fa], c[fb] - c[fa]) > 1e-9
    return ids, ang, concave


def components(n, pairs):
    """Connected component label (0..k-1) of n items joined by index pairs (m, 2). Pure numpy."""
    parent = np.arange(n, dtype=np.int64)
    if len(pairs) and n:
        a = pairs[:, 0].astype(np.int64)
        b = pairs[:, 1].astype(np.int64)
        for _ in range(200):
            pa, pb = parent[a], parent[b]
            diff = pa != pb
            if not diff.any():
                break
            pa, pb = pa[diff], pb[diff]
            lo = np.minimum(pa, pb)
            np.minimum.at(parent, pa, lo)
            np.minimum.at(parent, pb, lo)
            while True:  # pointer jumping until every item points at its root
                pp = parent[parent]
                if np.array_equal(pp, parent):
                    break
                parent = pp
    _, labels = np.unique(parent, return_inverse=True)
    return labels.reshape(-1)


def face_components(me):
    """Connected components of faces (faces sharing a vertex are connected)."""
    start, total, lv, _le = polys(me)
    if len(start) == 0:
        return np.zeros(0, dtype=np.int64)
    vlab = components(len(me.vertices), edges(me))
    return vlab[lv[start]]


def bbox(co):
    if len(co) == 0:
        z = np.zeros(3)
        return z, z
    return co.min(axis=0), co.max(axis=0)


def refresh(obj=None):
    """Updates matrix_world after changing location / rotation / scale (Blender only does it on a depsgraph
    update)."""
    bpy.context.view_layer.update()


def world_verts(obj):
    co = verts(obj.data)
    m = np.array(obj.matrix_world, dtype=np.float64)
    return co @ m[:3, :3].T + m[:3, 3]


def diag(co):
    lo, hi = bbox(co)
    return float(np.linalg.norm(hi - lo))


def tri_area_volume(co, t):
    """Total area and signed volume of a triangle list."""
    if len(t) == 0:
        return 0.0, 0.0
    a, b, c = co[t[:, 0]], co[t[:, 1]], co[t[:, 2]]
    cr = np.cross(b - a, c - a)
    area = 0.5 * float(np.linalg.norm(cr, axis=1).sum())
    vol = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0
    return area, vol


# ---------------------------------------------------------------- objects

def as_objects(objs):
    if objs is None:
        return []
    if isinstance(objs, bpy.types.Object):
        return [objs]
    return list(objs)


def require_mesh(obj):
    if obj is None or obj.type != 'MESH':
        raise ValueError(f"{getattr(obj, 'name', obj)!r} is not a mesh object")
    if obj.mode != 'OBJECT':
        object_mode(obj)
    if obj.data.shape_keys is not None:
        raise ValueError(f"{obj.name!r} has shape keys; remove them first (topology changes would break them)")
    if obj.data.users > 1:  # never change other objects that share this mesh
        obj.data = obj.data.copy()
    return obj


def object_mode(obj=None):
    ob = obj or bpy.context.view_layer.objects.active
    if ob is not None and ob.mode != 'OBJECT':
        with override(ob):
            bpy.ops.object.mode_set(mode='OBJECT')


def scene_collection_of(obj):
    return obj.users_collection[0] if obj.users_collection else bpy.context.scene.collection


def ensure_in_scene(obj):
    if obj.name not in bpy.context.scene.objects:
        bpy.context.scene.collection.objects.link(obj)


class override:
    """Context override for operators that need an active / selected object (works in background mode and from
    timers). Also really selects the objects in the view layer (multi-object edit mode reads that) and restores
    the person's selection and active object afterwards."""

    def __init__(self, obj, selected=None):
        self.obj = obj
        self.selected = selected if selected is not None else [obj]

    def __enter__(self):
        vl = bpy.context.view_layer
        for o in self.selected:
            ensure_in_scene(o)
        self.prev_active = vl.objects.active
        self.prev_sel = [o for o in vl.objects if o.select_get()]
        for o in self.prev_sel:
            o.select_set(False)
        for o in self.selected:
            o.hide_set(False)
            o.select_set(True)
        vl.objects.active = self.obj
        self.ctx = bpy.context.temp_override(active_object=self.obj, object=self.obj,
                                             selected_objects=self.selected,
                                             selected_editable_objects=self.selected)
        self.ctx.__enter__()
        return self

    def __exit__(self, *exc):
        self.ctx.__exit__(*exc)
        vl = bpy.context.view_layer
        try:
            for o in self.selected:
                o.select_set(False)
            for o in self.prev_sel:
                try:
                    o.select_set(True)
                except ReferenceError:
                    pass
            if self.prev_active is not None:
                try:
                    vl.objects.active = self.prev_active
                except ReferenceError:
                    pass
        except ReferenceError:
            pass
        return False


def apply_modifiers(obj, mods):
    """Applies only `mods` (other modifiers on the object are switched off while evaluating) and removes them."""
    others = [(m, m.show_viewport) for m in obj.modifiers if m not in mods]
    for m, _ in others:
        m.show_viewport = False
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        ev = obj.evaluated_get(dg)
        new = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    finally:
        for m, vis in others:
            m.show_viewport = vis
    for m in list(mods):
        obj.modifiers.remove(m)
    replace_mesh(obj, new)
    return obj


def replace_mesh(obj, new):
    """Gives the object a new mesh, keeping the old mesh's name and materials; frees the old mesh."""
    old = obj.data
    name = old.name
    restore_materials(new, old)
    obj.data = new
    if old.users == 0:
        bpy.data.meshes.remove(old)
    new.name = name
    return new


def restore_materials(new, old):
    """Gives `new` the materials of `old`: appended when it has none, filled in where its slots are empty (results
    from the background Blender come back with empty slots, so no duplicate materials appear)."""
    if len(new.materials) == 0:
        for mat in old.materials:
            new.materials.append(mat)
        return
    for i in range(min(len(new.materials), len(old.materials))):
        if new.materials[i] is None:
            new.materials[i] = old.materials[i]


def evaluated_face_count(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    return len(obj.evaluated_get(dg).data.polygons)


def bm_from(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    return bm


def bm_to(bm, obj):
    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()


def mark_sharp_by_angle(me, angle_deg, clear=False):
    """Marks edges sharper than angle_deg as sharp (and shades the mesh smooth so the edges show)."""
    start, total, _lv, le = polys(me)
    ids, ang, _concave = dihedral(me, start, total, le)
    sharp = edge_flags(me, "use_edge_sharp") if not clear else np.zeros(len(me.edges), dtype=bool)
    sharp[ids[ang > angle_deg]] = True
    count = np.bincount(le, minlength=len(me.edges)) if len(le) else np.zeros(len(me.edges), dtype=np.int64)
    sharp[count == 1] = True  # open borders shade as edges too
    me.edges.foreach_set("use_edge_sharp", sharp)
    me.polygons.foreach_set("use_smooth", np.ones(len(me.polygons), dtype=bool))
    me.update()
    return int(sharp.sum())


def shade_flat(me):
    me.polygons.foreach_set("use_smooth", np.zeros(len(me.polygons), dtype=bool))
    me.update()


def new_mesh_from_arrays(name, co, faces_flat, face_sizes):
    """Builds a mesh fast from numpy arrays (vertex positions, concatenated face vertex indices, face sizes)."""
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(co))
    me.vertices.foreach_set("co", np.ascontiguousarray(co, dtype=np.float32).ravel())
    nl = int(face_sizes.sum())
    me.loops.add(nl)
    me.loops.foreach_set("vertex_index", np.ascontiguousarray(faces_flat, dtype=np.int32))
    me.polygons.add(len(face_sizes))
    starts = np.zeros(len(face_sizes), dtype=np.int32)
    if len(face_sizes) > 1:
        starts[1:] = np.cumsum(face_sizes)[:-1]
    me.polygons.foreach_set("loop_start", starts)
    if VERSION < (4, 0, 0):  # loop_total is derived from loop_start since 4.0
        me.polygons.foreach_set("loop_total", np.ascontiguousarray(face_sizes, dtype=np.int32))
    me.update(calc_edges=True)
    me.validate(clean_customdata=False)
    return me


# attribute data names per type (foreach_get / foreach_set key, components)
_ATTR_KEYS = {
    'FLOAT': ("value", 1), 'INT': ("value", 1), 'BOOLEAN': ("value", 1), 'INT8': ("value", 1),
    'FLOAT_VECTOR': ("vector", 3), 'FLOAT2': ("vector", 2), 'INT32_2D': ("value", 2),
    'FLOAT_COLOR': ("color", 4), 'BYTE_COLOR': ("color", 4), 'QUATERNION': ("value", 4),
    'FLOAT4X4': ("value", 16),
}
_SKIP_ATTRS = {"position", ".edge_verts", ".corner_vert", ".corner_edge", ".select_vert", ".select_edge",
               ".select_poly", ".hide_vert", ".hide_edge", ".hide_poly"}


def submesh(me, face_mask, name):
    """A new mesh holding only the faces in face_mask, with every attribute (UVs, sharp edges, seams, materials,
    colors...) copied over. Much faster than copying the whole mesh per part."""
    start, total, lv, le = polys(me)
    fidx = np.nonzero(face_mask)[0]
    lf = loop_face(start, total)
    lmask = face_mask[lf]
    lidx = np.nonzero(lmask)[0]
    vused = np.unique(lv[lidx])
    vmap = np.full(len(me.vertices), -1, dtype=np.int64)
    vmap[vused] = np.arange(len(vused))
    eused = np.unique(le[lidx])
    co = verts(me)[vused]
    new = new_mesh_from_arrays(name, co, vmap[lv[lidx]], total[fidx])
    # new_mesh_from_arrays rebuilt edges; map old edges to new by their vertex pairs
    old_e = edges(me)[eused]
    old_key = np.sort(vmap[old_e], axis=1)
    new_e = np.sort(edges(new), axis=1)
    order_new = np.lexsort((new_e[:, 1], new_e[:, 0]))
    nk = new_e[order_new]
    ok_order = np.lexsort((old_key[:, 1], old_key[:, 0]))
    okk = old_key[ok_order]
    # both sorted: positions in the sorted lists match when the sets are equal
    emap_old = None
    if len(nk) == len(okk) and np.array_equal(nk, okk):
        emap_old = (eused[ok_order], order_new)  # old edge ids -> new edge ids
    # face / corner order is kept as is (faces kept in order, loops in order)
    for mat in me.materials:
        new.materials.append(mat)
    for attr in me.attributes:
        if attr.name in _SKIP_ATTRS or attr.name.startswith(".") and attr.name not in (".uv_seam",):
            continue
        key = _ATTR_KEYS.get(attr.data_type)
        if key is None:
            continue
        prop, ncomp = key
        dom = attr.domain
        if dom == 'POINT':
            sel, n_new = vused, len(vused)
        elif dom == 'FACE':
            sel, n_new = fidx, len(fidx)
        elif dom == 'CORNER':
            sel, n_new = lidx, len(lidx)
        elif dom == 'EDGE':
            if emap_old is None:
                continue
            sel, n_new = emap_old[0], len(emap_old[0])
        else:
            continue
        n_old = len(attr.data)
        dt = np.float32 if attr.data_type in ('FLOAT', 'FLOAT_VECTOR', 'FLOAT2', 'FLOAT_COLOR', 'BYTE_COLOR',
                                              'QUATERNION', 'FLOAT4X4') else (
            bool if attr.data_type == 'BOOLEAN' else np.int32)
        buf = np.empty(n_old * ncomp, dtype=dt)
        attr.data.foreach_get(prop, buf)
        buf = buf.reshape(n_old, ncomp)[sel]
        if dom == 'EDGE':
            out = np.empty_like(buf)
            out[emap_old[1]] = buf
            buf = out
        tgt = new.attributes.get(attr.name)
        if tgt is None:
            try:
                tgt = new.attributes.new(attr.name, attr.data_type, dom)
            except (RuntimeError, TypeError):
                continue
        if len(tgt.data) != n_new:
            continue
        tgt.data.foreach_set(prop, np.ascontiguousarray(buf).ravel())
    if emap_old is not None:  # seams / sharp flags (stored outside the generic attributes in some versions)
        for flag in ("use_seam", "use_edge_sharp"):
            src = edge_flags(me, flag)[emap_old[0]]
            out = np.zeros(len(new.edges), dtype=bool)
            out[emap_old[1]] = src
            new.edges.foreach_set(flag, out)
    # keep the active UV map / render UV
    if me.uv_layers.active is not None and me.uv_layers.active.name in new.uv_layers:
        new.uv_layers.active = new.uv_layers[me.uv_layers.active.name]
    new.update()
    return new


class Progress:
    """Calls fn(fraction, message) at most every ~0.2 s (from library code that may run anywhere)."""

    def __init__(self, fn=None, lo=0.0, hi=1.0):
        self.fn, self.lo, self.hi, self.last = fn, lo, hi, 0.0

    def __call__(self, frac, message=""):
        if self.fn is None:
            return
        now = time.monotonic()
        if frac < 1.0 and now - self.last < 0.2:
            return
        self.last = now
        self.fn(self.lo + (self.hi - self.lo) * max(0.0, min(1.0, frac)), message)

    def sub(self, a, b):
        return Progress(self.fn, self.lo + (self.hi - self.lo) * a, self.lo + (self.hi - self.lo) * b)


def fmt_len(m):
    m = abs(m)
    if m >= 1:
        return f"{m:.2f} m"
    if m >= 0.01:
        return f"{m * 100:.1f} cm"
    return f"{m * 1000:.1f} mm"


def radians(deg):
    return math.radians(float(deg))
