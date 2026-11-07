# SPDX-License-Identifier: GPL-3.0-or-later
"""Cleanup for generated meshes (dense triangle soup from image -> 3D models): weld, drop floaters, fill holes,
make it manifold, fix normals, apply transforms, real-world size, put it on the ground with the origin at the
bottom center."""

import math
import time

import bmesh
import bpy
import numpy as np

from . import _util as U
from . import stats as S


def auto_weld_distance(co):
    return max(U.diag(co) * 1e-5, 1e-7)


def weld(obj, dist=None):
    """Merges vertices closer than dist (auto: a tiny fraction of the size). Returns how many were merged."""
    me = obj.data
    co = U.verts(me)
    d = auto_weld_distance(co) if dist in (None, "auto") else float(dist)
    before = len(me.vertices)
    bm = U.bm_from(obj)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=d)
    bmesh.ops.dissolve_degenerate(bm, dist=d * 0.5, edges=bm.edges)
    U.bm_to(bm, obj)
    _remove_loose(obj)
    _remove_duplicate_faces(obj)
    return before - len(obj.data.vertices), d


def _remove_loose(obj):
    """Deletes edges and vertices that belong to no face (found with numpy, deleted only if there are any)."""
    me = obj.data
    _s, _t, lv, le = U.polys(me)
    loose_e = np.nonzero(np.bincount(le, minlength=len(me.edges)) == 0)[0] if len(me.edges) else []
    used_v = np.zeros(len(me.vertices), dtype=bool)
    used_v[lv] = True
    loose_v = np.nonzero(~used_v)[0]
    if len(loose_e) == 0 and len(loose_v) == 0:
        return 0
    bm = U.bm_from(obj)
    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    vrefs = [bm.verts[i] for i in loose_v]
    if len(loose_e):
        bmesh.ops.delete(bm, geom=[bm.edges[i] for i in loose_e], context='EDGES')
    left = [v for v in vrefs if v.is_valid and not v.link_faces]
    if left:
        bmesh.ops.delete(bm, geom=left, context='VERTS')
    U.bm_to(bm, obj)
    return len(loose_e) + len(loose_v)


def _remove_duplicate_faces(obj):
    me = obj.data
    start, total, lv, _le = U.polys(me)
    if len(start) == 0:
        return 0
    k = int(min(total.max(), 8))
    keys = np.full((len(start), k + 1), -1, dtype=np.int64)
    keys[:, 0] = total
    for j in range(k):
        has = total > j
        keys[has, j + 1] = lv[start[has] + j]
    keys[:, 1:] = np.sort(np.where(keys[:, 1:] < 0, np.iinfo(np.int64).max, keys[:, 1:]), axis=1)
    _u, first = np.unique(keys, axis=0, return_index=True)
    dup = np.setdiff1d(np.arange(len(start)), first)
    if len(dup) == 0:
        return 0
    bm = U.bm_from(obj)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in dup], context='FACES_ONLY')
    U.bm_to(bm, obj)
    return len(dup)


def remove_floaters(obj, min_size=0.03, keep_largest=False, min_faces=0):
    """Deletes loose pieces smaller than min_size (a fraction of the whole size; 0.03 = 3%). keep_largest: keep only
    the biggest piece. Returns (pieces removed, pieces kept)."""
    me = obj.data
    if len(me.polygons) == 0:
        return 0, 0
    flab = U.face_components(me)
    k = int(flab.max() + 1)
    if k <= 1:
        return 0, 1
    co = U.verts(me)
    start, total, lv, _le = U.polys(me)
    vlab_face = np.repeat(flab, total)
    lvco = co[lv]
    lo = np.full((k, 3), np.inf)
    hi = np.full((k, 3), -np.inf)
    for i in range(3):
        np.minimum.at(lo[:, i], vlab_face, lvco[:, i])
        np.maximum.at(hi[:, i], vlab_face, lvco[:, i])
    size = np.linalg.norm(hi - lo, axis=1)
    whole = U.diag(co) or 1.0
    t, tp = U.tris(me)
    a, b, c = co[t[:, 0]], co[t[:, 1]], co[t[:, 2]]
    vol = np.bincount(flab[tp], weights=np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0, minlength=k)
    faces = np.bincount(flab, minlength=k)
    biggest = int(np.argmax(np.abs(vol) + size * 1e-9))
    if keep_largest:
        keep = np.zeros(k, dtype=bool)
        keep[biggest] = True
    else:
        keep = (size >= min_size * whole) & (faces >= min_faces)
        keep[biggest] = True
    drop_faces = ~keep[flab]
    if not drop_faces.any():
        return 0, k
    bm = U.bm_from(obj)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in np.nonzero(drop_faces)[0]], context='FACES')
    U.bm_to(bm, obj)
    return int((~keep).sum()), int(keep.sum())


def fill_holes(obj, max_sides=0):
    """Closes open borders with new faces (triangulated). max_sides 0 = any size. Returns holes filled."""
    bm = U.bm_from(obj)
    # where two holes touch in one vertex the border is a figure 8, which holes_fill cannot close: open those
    # spots a little so every hole is one simple loop
    for _ in range(4):
        bad = [v for v in bm.verts if sum(1 for e in v.link_edges if e.is_boundary) > 2]
        if not bad:
            break
        faces = list({f for v in bad for f in v.link_faces})
        bmesh.ops.delete(bm, geom=faces, context='FACES')
        loose = [v for v in bm.verts if not v.link_edges]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context='VERTS')
    border = [e for e in bm.edges if e.is_boundary]
    if not border:
        bm.free()
        return 0
    res = bmesh.ops.holes_fill(bm, edges=border, sides=int(max_sides))
    new = list(res.get("faces", []))
    filled = len(new)
    if new:
        bmesh.ops.triangulate(bm, faces=new, quad_method='BEAUTY', ngon_method='BEAUTY')
    left = [e for e in bm.edges if e.is_boundary]
    if left and not max_sides:  # loops holes_fill skipped: close them with triangles
        res2 = bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False, edges=left)
        if any(isinstance(g, bmesh.types.BMFace) for g in res2.get("geom", [])):
            filled += 1
    U.bm_to(bm, obj)
    return filled


def recalc_normals(obj):
    """Makes face normals point outward (per loose piece). Returns True when it flipped something inside out."""
    bm = U.bm_from(obj)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    U.bm_to(bm, obj)
    # closed pieces with negative volume are inside out (recalc can fail on odd shapes): flip them
    me = obj.data
    if len(me.polygons) == 0:
        return False
    flab = U.face_components(me)
    co = U.verts(me)
    t, tp = U.tris(me)
    a, b, c = co[t[:, 0]], co[t[:, 1]], co[t[:, 2]]
    vol = np.bincount(flab[tp], weights=np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0, minlength=flab.max() + 1)
    bad = np.nonzero(vol < 0)[0]
    if len(bad) == 0:
        return False
    bm = U.bm_from(obj)
    bm.faces.ensure_lookup_table()
    flip = np.isin(flab, bad)
    bmesh.ops.reverse_faces(bm, faces=[bm.faces[i] for i in np.nonzero(flip)[0]])
    U.bm_to(bm, obj)
    return True


def non_manifold_counts(obj):
    me = obj.data
    _s, _t, _lv, le = U.polys(me)
    count = np.bincount(le, minlength=len(me.edges)) if len(le) else np.zeros(0, dtype=np.int64)
    bm = U.bm_from(obj)
    bad_v = sum(1 for v in bm.verts if not v.is_manifold)
    bm.free()
    return {"open_edges": int((count == 1).sum()), "bad_edges": int((count > 2).sum()), "bad_verts": int(bad_v)}


def repair_spots(obj, max_spots=400):
    """A few broken spots on an otherwise clean mesh (an AI model with 2-10 bad edges / vertices) are cut out with
    the faces around them and closed again, so every UV and texture elsewhere stays (a voxel rebuild would lose the
    AI texture). Returns the faces removed, or None when there are too many spots for this (then rebuild)."""
    bm = U.bm_from(obj)
    try:
        spots = {v for e in bm.edges if len(e.link_faces) != 2 for v in e.verts}
        spots |= {v for v in bm.verts if not v.is_manifold}
        if not spots:
            return 0
        if len(spots) > max_spots:
            return None
        cut = {f for v in spots for f in v.link_faces}
        cut |= {f for g in list(cut) for v in g.verts for f in v.link_faces}       # one ring more: simple holes
        removed = 0
        for _ in range(4):
            bmesh.ops.delete(bm, geom=list(cut), context='FACES_ONLY')
            removed += len(cut)
            wire = [e for e in bm.edges if not e.link_faces]
            if wire:
                bmesh.ops.delete(bm, geom=wire, context='EDGES')
            loose = [v for v in bm.verts if not v.link_faces]
            if loose:
                bmesh.ops.delete(bm, geom=loose, context='VERTS')
            border = [e for e in bm.edges if e.is_boundary]
            made = bmesh.ops.holes_fill(bm, edges=border, sides=0).get("faces", []) if border else []
            big = [f for f in made if len(f.verts) > 3]
            if big:
                bmesh.ops.triangulate(bm, faces=big, quad_method='BEAUTY', ngon_method='BEAUTY')
            left = {v for e in bm.edges if len(e.link_faces) != 2 for v in e.verts}
            left |= {v for v in bm.verts if not v.is_manifold}
            if not left:
                break
            cut = {f for v in left for f in v.link_faces}
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        U.bm_to(bm, obj)
        bm = None
        return removed
    finally:
        if bm is not None:
            bm.free()


def auto_voxel_size(obj, target_faces=None):
    """A voxel size that keeps the detail: about as many faces as the mesh has (60k..400k), never finer than
    1/1200 of the size."""
    me = obj.data
    co = U.verts(me)
    t, _ = U.tris(me)
    area, _ = U.tri_area_volume(co, t)
    nf = len(me.polygons)
    target = target_faces or int(min(max(nf * 0.6, 60000), 400000))
    vs = math.sqrt(max(area, 1e-12) / target)
    return max(vs, (U.diag(co) or 1.0) / 1200.0)


def voxel_remesh(obj, voxel_size=None):
    """Watertight, manifold rebuild of the surface (loses UVs; keeps the shape to about one voxel)."""
    nf = len(obj.data.polygons)
    vs = float(voxel_size) if voxel_size else auto_voxel_size(obj, target_faces=int(min(max(nf, 60000), 600000)))
    mod = obj.modifiers.new("Nighty Voxel", 'REMESH')
    mod.mode = 'VOXEL'
    mod.voxel_size = vs
    mod.adaptivity = 0.0
    mod.use_smooth_shade = False
    U.apply_modifiers(obj, [mod])
    return vs


def apply_transforms(obj):
    """Bakes location / rotation / scale into the mesh (like Apply > All Transforms; parent kept)."""
    m = obj.matrix_basis.copy()
    if m == m.Identity(4):
        return False
    me = obj.data
    me.transform(m)
    if m.to_3x3().determinant() < 0:
        me.flip_normals()
    obj.matrix_basis.identity()
    me.update()
    U.refresh(obj)
    return True


def set_size(obj, size, axis="longest"):
    """Scales the mesh so its size along axis (longest / height / x / y / z) is `size` meters."""
    co = U.verts(obj.data)
    lo, hi = U.bbox(co)
    dims = hi - lo
    sc = np.array(obj.matrix_world.to_scale())
    dims_w = dims * np.abs(sc)
    idx = {"x": 0, "y": 1, "z": 2, "height": 2}.get(axis)
    cur = float(dims_w.max()) if idx is None else float(dims_w[idx])
    if cur <= 0:
        return 1.0
    f = float(size) / cur
    U.set_verts(obj.data, co * f)
    return f


def ground(obj, origin="bottom", to_ground=True):
    """origin 'bottom': origin at the bottom center of the mesh; 'center': at the bounding-box center; 'keep'.
    to_ground: move the object so its lowest point sits on z = 0."""
    me = obj.data
    co = U.verts(me)
    if len(co) == 0:
        return
    lo, hi = U.bbox(co)
    if origin in ("bottom", "center"):
        piv = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2] if origin == "bottom" else (lo[2] + hi[2]) / 2])
        U.set_verts(me, co - piv)
        from mathutils import Vector
        obj.location = obj.matrix_basis @ Vector(piv)  # the mesh stays where it was
    U.refresh(obj)
    if to_ground and obj.parent is None:
        wz = U.world_verts(obj)[:, 2].min()
        obj.location.z -= float(wz)
        U.refresh(obj)


def _smoothed_face_normals(me, lf, lv, n, area, rounds=2):
    nv = len(me.vertices)
    sn = n.copy()
    for _ in range(rounds):
        vn = np.zeros((nv, 3))
        w = (sn * area[:, None])[lf]
        for i in range(3):
            vn[:, i] = np.bincount(lv, weights=w[:, i], minlength=nv)
        vn /= np.maximum(np.linalg.norm(vn, axis=1), 1e-30)[:, None]
        fnew = np.zeros_like(sn)
        for i in range(3):
            fnew[:, i] = np.bincount(lf, weights=vn[lv, i], minlength=len(sn))
        sn = fnew / np.maximum(np.linalg.norm(fnew, axis=1), 1e-30)[:, None]
    return sn


def _fit_plane(pts, w=None):
    c = np.average(pts, axis=0, weights=w)
    d = pts - c
    cov = (d * (w[:, None] if w is not None else 1.0)).T @ d
    vals, vecs = np.linalg.eigh(cov)
    return c, vecs[:, 0], vecs[:, 1], vecs[:, 2]


FADE_FROM, FADE_TO = 12.0, 30.0  # flatten_planes: degrees the faces around a vertex lean off its flat side
CREASE_DEG, CREASE_RINGS = 70.0, 2  # ... but a wall this steep within these rings is a real crease: full snap


def flatten_planes(obj, angle=12.0, tol=0.0025, min_area=0.003, min_extent=0.02, max_move=0.006):
    """Hard-surface helper for noisy generated meshes: finds the flat sides, makes them truly flat, and puts the
    vertices where two flat sides meet exactly on the line where the planes cross (crisp edges); three or more
    sides meet in one point (crisp corners). Curved areas are left alone.
    tol / min_extent / max_move are shares of the size; min_area is a share of the surface. Returns
    (flat sides found, vertices moved)."""
    me = obj.data
    nf = len(me.polygons)
    if nf == 0:
        return 0, 0
    co = U.verts(me)
    size = U.diag(co) or 1.0
    start, total, lv, le = U.polys(me)
    lf = U.loop_face(start, total)
    n = U.face_normals(me)
    area = U.face_areas(me)
    sn = _smoothed_face_normals(me, lf, lv, n, area)
    ids, fa, fb, _count = U.edge_faces(me, start, total, le)
    cos_small = math.cos(math.radians(4.0))
    raw = np.einsum("ij,ij->i", n[fa], n[fb])
    smooth = np.einsum("ij,ij->i", sn[fa], sn[fb])
    join = (smooth > cos_small) & (raw > math.cos(math.radians(angle)))
    lab = U.components(nf, np.stack([fa[join], fb[join]], axis=1))
    total_area = area.sum() or 1.0
    order = np.argsort(lab, kind="stable")
    bounds = np.searchsorted(lab[order], np.arange(lab.max() + 2))
    planes = []  # (center, normal)
    face_plane = np.full(nf, -1, dtype=np.int64)

    def try_region(faces):
        if area[faces].sum() < min_area * total_area:
            return False
        cnt_l = total[faces]
        offs = np.repeat(start[faces] - np.concatenate([[0], np.cumsum(cnt_l)[:-1]]), cnt_l)
        loops = np.arange(int(cnt_l.sum())) + offs
        vids = np.unique(lv[loops])
        pts = co[vids]
        c, nrm, ax1, ax2 = _fit_plane(pts)
        dist = (pts - c) @ nrm
        if np.sqrt(np.mean(dist ** 2)) > tol * size:
            return False
        e1, e2 = (pts - c) @ ax1, (pts - c) @ ax2
        if min(np.ptp(e1), np.ptp(e2)) < min_extent * size:
            return False
        # the normal must agree with the faces (not a sideways fit through a thin strip)
        if abs(float(np.average(n[faces], axis=0, weights=area[faces]) @ nrm)) < math.cos(math.radians(angle)):
            return False
        face_plane[faces] = len(planes)
        planes.append((c, nrm))
        return True

    region_area = np.bincount(lab, weights=area)
    for r in np.nonzero(region_area >= min_area * total_area)[0]:
        faces = order[bounds[r]:bounds[r + 1]]
        if try_region(faces):
            continue
        # a curved region may still hold flat parts: take the faces facing its main direction and try those
        d = np.average(sn[faces], axis=0, weights=area[faces])
        if np.linalg.norm(d) < 1e-9:
            continue
        d /= np.linalg.norm(d)
        sub = faces[sn[faces] @ d > math.cos(math.radians(6.0))]
        if len(sub) == 0:
            continue
        sub_set = np.zeros(nf, dtype=bool)
        sub_set[sub] = True
        m = sub_set[fa] & sub_set[fb] & join
        sl = U.components(nf, np.stack([fa[m], fb[m]], axis=1))[sub]
        for k in np.unique(sl):
            try_region(sub[sl == k])
    if not planes:
        return 0, 0
    P_c = np.array([p[0] for p in planes])
    P_n = np.array([p[1] for p in planes])
    # which flat sides touch each vertex
    lp = face_plane[lf]
    ok = lp >= 0
    pairs = np.unique(np.stack([lv[ok], lp[ok]], axis=1), axis=0)
    new = co.copy()
    moved = 0
    cnt = np.bincount(pairs[:, 0], minlength=len(co))
    first = np.searchsorted(pairs[:, 0], np.arange(len(co)))
    limit = max_move * size
    # how much the faces around each vertex lean off its flat sides (a face of a flat side: off its own side; up to
    # two sides per vertex are looked at): inside a flat side (all under FADE_FROM degrees) the snap is full, at the
    # start of a fillet or raised rim (over FADE_TO) there is none, in between it fades. A full snap of every vertex
    # touching a flat side flattened the start of the curve up to the faces' own ragged outline: a sawtooth rim
    # around raised parts.
    has = cnt[lv] > 0
    f1 = np.where(has, pairs[np.minimum(first[lv], len(pairs) - 1), 1], 0)
    f2 = np.where(cnt[lv] > 1, pairs[np.minimum(first[lv] + 1, len(pairs) - 1), 1], f1)
    nl = n[lf]
    fpl = face_plane[lf]
    cos_l = np.where(fpl >= 0, np.abs(np.einsum("ij,ij->i", nl, P_n[np.maximum(fpl, 0)])),
                     np.maximum(np.abs(np.einsum("ij,ij->i", nl, P_n[f1])),
                                np.abs(np.einsum("ij,ij->i", nl, P_n[f2]))))
    vmin = np.ones(len(co))
    np.minimum.at(vmin, lv[has], cos_l[has])
    tilt = np.degrees(np.arccos(np.clip(vmin, -1.0, 1.0)))
    weight = np.clip((FADE_TO - tilt) / (FADE_TO - FADE_FROM), 0.0, 1.0)
    # a real crease (a wall standing up off the flat side within a couple of rings, as where a barrel goes into a
    # receiver) keeps the full snap, so it comes out crisp; only a gentle rise (a fillet, a raised rim's slope) fades
    ev = U.edges(me)
    steep = tilt.copy()
    for _ in range(CREASE_RINGS):
        nxt = steep.copy()
        np.maximum.at(nxt, ev[:, 0], steep[ev[:, 1]])
        np.maximum.at(nxt, ev[:, 1], steep[ev[:, 0]])
        steep = nxt
    weight[(steep >= CREASE_DEG) & (tilt >= CREASE_DEG * 0.5)] = 1.0
    for v in np.nonzero((cnt > 0) & (weight > 0))[0]:
        ps = pairs[first[v]:first[v] + cnt[v], 1]
        N = P_n[ps]
        dd = np.einsum("ij,ij->i", N, P_c[ps])
        p = co[v]
        if len(ps) == 1:
            q = p - N[0] * (N[0] @ p - dd[0])
        else:
            # closest point to p on the intersection of the planes (least squares; drops near-parallel planes)
            A = np.vstack([N, np.eye(3) * 1e-3])
            b = np.concatenate([dd, p * 1e-3])
            s = np.linalg.svd(N, compute_uv=False)
            if len(ps) >= 2 and s[min(1, len(s) - 1)] < 0.3:  # two (almost) parallel planes: just the first
                q = p - N[0] * (N[0] @ p - dd[0])
            else:
                q = np.linalg.lstsq(A, b, rcond=None)[0]
        if np.linalg.norm(q - p) <= limit:
            new[v] = p + (q - p) * weight[v]
            moved += 1
    U.set_verts(me, new)
    # snapping can squash tiny faces along the creases: clean those up
    bm = U.bm_from(obj)
    bmesh.ops.dissolve_degenerate(bm, dist=size * 1e-6, edges=bm.edges)
    U.bm_to(bm, obj)
    return len(planes), moved


def find_gaps(obj, tol=0.012, min_extent=0.06):
    """Plate-like gaps an image -> 3D generator leaves between parts that belong together (a gun's end cap floating
    a few millimetres off the body): two surfaces facing each other closer than `tol` (share of the size), over an
    area at least `min_extent` of the size wide in both directions. Slits, grooves, rail teeth and holes are
    narrower than that and stay. Returns [{faces (one side), normal, gap, area, extent}] (object space)."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    me = obj.data
    nf = len(me.polygons)
    if nf == 0:
        return []
    co = U.verts(me)
    size = U.diag(co) or 1.0
    t, tp = U.tris(me)
    tree = BVHTree.FromPolygons([Vector(v) for v in co], t.tolist(), all_triangles=True)
    c = U.face_centers(me)
    n = U.face_normals(me)
    area = U.face_areas(me)
    reach = tol * size
    eps = 1e-5 * size
    hit_face = np.full(nf, -1, dtype=np.int64)
    dist = np.zeros(nf)
    for i in range(nf):  # one short ray per face, out along its normal (~0.5 s per 100k faces)
        hit = tree.ray_cast(Vector(c[i] + n[i] * eps), Vector(n[i]), reach)
        if hit[0] is not None:
            hit_face[i] = tp[hit[2]]
            dist[i] = hit[3]
    gap = hit_face >= 0
    gap[gap] &= np.einsum("ij,ij->i", n[gap], n[hit_face[gap]]) < -0.7  # facing each other
    if not gap.any():
        return []
    start, total, lv, le = U.polys(me)
    ids, fa, fb, _c = U.edge_faces(me, start, total, le)
    both = gap[fa] & gap[fb]
    lab = U.components(nf, np.stack([fa[both], fb[both]], axis=1))
    out, used = [], set()
    labels, counts = np.unique(lab[gap], return_counts=True)
    for L in labels[np.argsort(-counts)]:
        if L in used:
            continue
        f = np.nonzero((lab == L) & gap)[0]
        if area[f].sum() <= 0:
            continue
        nn = np.average(n[f], axis=0, weights=area[f])
        nn /= np.linalg.norm(nn) or 1.0
        u = np.cross(nn, (1, 0, 0) if abs(nn[0]) < 0.9 else (0, 1, 0))
        u /= np.linalg.norm(u)
        v = np.cross(nn, u)
        ext = min(np.ptp(c[f] @ u), np.ptp(c[f] @ v))
        if ext < min_extent * size:
            continue
        partners = np.unique(lab[hit_face[f]])
        used.add(L)
        used.update(int(x) for x in partners)
        out.append({"faces": f, "normal": nn, "gap": float(np.median(dist[f])), "area": float(area[f].sum()),
                    "extent": float(ext)})
    return out


def _outline(patch_me):
    """The longest border loop of a patch, as an ordered array of vertex indices."""
    e = U.edges(patch_me)
    _s, _t, _lv, le = U.polys(patch_me)
    border = e[np.bincount(le, minlength=len(e)) == 1]
    if len(border) == 0:
        return None
    nxt = {}
    for a_, b_ in border:
        nxt.setdefault(int(a_), []).append(int(b_))
        nxt.setdefault(int(b_), []).append(int(a_))
    co = U.verts(patch_me)
    seen, best, best_len = set(), None, 0.0
    for start in list(nxt):
        if start in seen:
            continue
        loop, prev, cur = [start], None, start
        seen.add(start)
        while True:
            options = [x for x in nxt[cur] if x != prev and (x not in seen or x == start)]
            if not options:
                break
            prev, cur = cur, options[0]
            if cur == start:
                break
            loop.append(cur)
            seen.add(cur)
        if len(loop) >= 3:
            pts = co[loop]
            length = float(np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1).sum())
            if length > best_len:
                best, best_len = loop, length
    return np.array(best) if best is not None else None


SEAM_INSETS = (0.0, 0.3, 0.6)  # extra share of the gap the slab stays back from the slit's edge, tried in turn
# (0: flush, the neatest seam; a boolean solver can choke on a flush slab, Blender 4.2's EXACT does on some shapes)


SLIT_CELL = 0.25    # the slit is mapped on a grid of this many gaps per cell
SLIT_WALL = 1.25    # a grid point is in the slit when both parts are within this many gaps of it


def _grid_dilate(m):
    out = m.copy()
    out[1:, :] |= m[:-1, :]
    out[:-1, :] |= m[1:, :]
    out[:, 1:] |= m[:, :-1]
    out[:, :-1] |= m[:, 1:]
    return out


def _grid_erode(m):
    return ~_grid_dilate(~m)


def _grid_close(m):
    return _grid_erode(_grid_dilate(m))


def _grid_open(m):
    return _grid_dilate(_grid_erode(m))


def _slit_outline(obj, gap, c0, u, v, nn, level, tree):
    """The whole slit between the two parts, out to where it opens to the outside: points on the middle plane of the
    gap with a part close by on both sides, connected to the facing faces (enclosed holes filled). Returns the
    outline as 2D points in (u, v) around c0, or None. The slab built on it closes the joint completely, lumps and
    bits the generator left in the slit included."""
    from mathutils import Vector
    me = obj.data
    g = gap["gap"]
    pco = U.face_centers(me)[gap["faces"]]
    fu, fv = (pco - c0) @ u, (pco - c0) @ v
    h = max(SLIT_CELL * g, 1e-6)
    margin = 4.0 * g + 2.0 * h
    u0, v0 = fu.min() - margin, fv.min() - margin
    nu = int(np.ceil((fu.max() + margin - u0) / h)) + 1
    nv = int(np.ceil((fv.max() + margin - v0) / h)) + 1
    if nu * nv > 400000:   # a huge joint: coarser cells
        k = np.sqrt(nu * nv / 400000.0)
        h *= k
        nu, nv = int(nu / k) + 1, int(nv / k) + 1
    mid = c0 + nn * (level + 0.5 * g)
    up, down = Vector(nn), Vector(-nn)
    reach = SLIT_WALL * g
    occ = np.zeros((nu, nv), dtype=bool)
    for i in range(nu):
        base = mid + u * (u0 + (i + 0.5) * h)
        for j in range(nv):
            q = Vector(base + v * (v0 + (j + 0.5) * h))
            if tree.ray_cast(q, up, reach)[0] is not None and tree.ray_cast(q, down, reach)[0] is not None:
                occ[i, j] = True
    # keep what touches the facing faces, fill enclosed holes
    seed = np.zeros_like(occ)
    seed[np.clip(((fu - u0) / h).astype(int), 0, nu - 1), np.clip(((fv - v0) / h).astype(int), 0, nv - 1)] = True
    ids = np.arange(nu * nv).reshape(nu, nv)
    pairs = np.concatenate([np.stack([ids[:-1, :][occ[:-1, :] & occ[1:, :]], ids[1:, :][occ[:-1, :] & occ[1:, :]]], 1),
                            np.stack([ids[:, :-1][occ[:, :-1] & occ[:, 1:]], ids[:, 1:][occ[:, :-1] & occ[:, 1:]]], 1)])
    lab = U.components(nu * nv, pairs).reshape(nu, nv)
    keep = np.isin(lab, np.unique(lab[seed & occ])) & occ
    if not keep.any():
        return None
    outside = ~keep
    opairs = np.concatenate([np.stack([ids[:-1, :][outside[:-1, :] & outside[1:, :]],
                                       ids[1:, :][outside[:-1, :] & outside[1:, :]]], 1),
                             np.stack([ids[:, :-1][outside[:, :-1] & outside[:, 1:]],
                                       ids[:, 1:][outside[:, :-1] & outside[:, 1:]]], 1)])
    olab = U.components(nu * nv, opairs).reshape(nu, nv)
    border = np.unique(np.concatenate([olab[0, :], olab[-1, :], olab[:, 0], olab[:, -1]]))
    keep |= outside & ~np.isin(olab, border)   # holes inside the slit: filled
    # a clean outline: no one-cell notches, spurs or cells touching only at a corner (they pinch the outline)
    keep = _grid_open(_grid_close(keep))
    if not keep.any():
        return None
    # the cells as a quad patch: its longest border loop is the outline
    bm = bmesh.new()
    corner = {}

    def cv(i, j):
        k = (i, j)
        if k not in corner:
            corner[k] = bm.verts.new((u0 + i * h, v0 + j * h, 0.0))
        return corner[k]
    for i, j in zip(*np.nonzero(keep)):
        bm.faces.new((cv(i, j), cv(i + 1, j), cv(i + 1, j + 1), cv(i, j + 1)))
    tmp = bpy.data.meshes.new("nighty_slit")
    bm.to_mesh(tmp)
    bm.free()
    try:
        loop = _outline(tmp)
        pts = U.verts(tmp)[:, :2].astype(np.float64)
    finally:
        bpy.data.meshes.remove(tmp)
    if loop is None or len(loop) < 3:
        return None
    return pts[loop]


def _rdp(pts, tol):
    """Ramer-Douglas-Peucker on an open polyline: the indices kept."""
    keep = np.zeros(len(pts), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        p, q = pts[a], pts[b]
        d = q - p
        ln = np.linalg.norm(d)
        seg = pts[a + 1:b] - p
        if ln < 1e-12:
            dist = np.linalg.norm(seg, axis=1)
        else:
            dist = np.abs(seg[:, 0] * d[1] - seg[:, 1] * d[0]) / ln
        i = int(np.argmax(dist))
        if dist[i] > tol:
            m = a + 1 + i
            keep[m] = True
            stack += [(a, m), (m, b)]
    return np.nonzero(keep)[0]


def _straighten(pts, tol):
    """A closed outline traced on a grid, made clean: corners and the line between them kept within `tol` (RDP),
    then evenly resampled (about every tol) and smoothed a little, so straight runs are straight and curves round."""
    k = len(pts)
    if k < 4:
        return pts
    c = pts.mean(axis=0)
    a = int(np.argmax(np.linalg.norm(pts - c, axis=1)))           # split the loop at two far apart points
    b = int(np.argmax(np.linalg.norm(pts - pts[a], axis=1)))
    ring = np.roll(pts, -a, axis=0)
    b = (b - a) % k
    first = _rdp(ring[:b + 1], tol)
    second = _rdp(np.vstack([ring[b:], ring[:1]]), tol) + b
    idx = np.unique(np.concatenate([first, second[:-1]])) % k
    corners = ring[np.sort(idx)]
    out = []
    for i in range(len(corners)):
        p, q = corners[i], corners[(i + 1) % len(corners)]
        n = max(1, int(np.ceil(np.linalg.norm(q - p) / max(tol, 1e-9))))
        out.extend(p + (q - p) * (j / n) for j in range(n))
    out = np.array(out)
    for _ in range(4):
        out = 0.25 * np.roll(out, 1, axis=0) + 0.5 * out + 0.25 * np.roll(out, -1, axis=0)
    return out


def _untwist(pts):
    """A closed outline whose offset crosses itself at a sharp inner corner: the small loop is cut off at the
    crossing (repeated until it is simple)."""
    def cross(o, x, y):
        return (x[..., 0] - o[..., 0]) * (y[..., 1] - o[..., 1]) - (x[..., 1] - o[..., 1]) * (y[..., 0] - o[..., 0])
    for _ in range(50):
        n = len(pts)
        if n < 4:
            return pts
        a, b = pts, np.roll(pts, -1, axis=0)
        found = None
        for i in range(n):
            s1, s2 = cross(a[i], b[i], a), cross(a[i], b[i], b)
            s3, s4 = cross(a, b, a[i]), cross(a, b, b[i])
            hit = (s1 * s2 < 0) & (s3 * s4 < 0)
            hit[[i, (i - 1) % n, (i + 1) % n]] = False
            js = np.nonzero(hit)[0]
            if len(js):
                found = (i, int(js[0]))
                break
        if found is None:
            return pts
        i, j = sorted(found)
        d1, d2 = b[i] - a[i], b[j] - a[j]
        den = d1[0] * d2[1] - d1[1] * d2[0]
        tt = ((a[j][0] - a[i][0]) * d2[1] - (a[j][1] - a[i][1]) * d2[0]) / den if abs(den) > 1e-30 else 0.5
        x = a[i] + d1 * tt
        if j - i <= n - (j - i):      # drop the shorter side of the crossing (the small loop)
            pts = np.vstack([pts[:i + 1], x[None], pts[j + 1:]])
        else:
            pts = np.vstack([x[None], pts[i + 1:j + 1]])
    return pts


def _gap_filler(obj, gap, overlap, inset=0.0, tree=None):
    """A slab that closes one joint completely: the outline of the whole slit between the two parts (see
    _slit_outline), smoothed and set back half a grid cell (so nothing sticks out of the narrower part), extruded
    straight across the gap and a little into both parts."""
    me = obj.data
    start, total, lv, _le = U.polys(me)
    pco = U.verts(me)[np.unique(lv[np.isin(U.loop_face(start, total), gap["faces"])])]
    nn = np.asarray(gap["normal"], dtype=np.float64)
    u = np.cross(nn, (1, 0, 0) if abs(nn[0]) < 0.9 else (0, 1, 0))
    u /= np.linalg.norm(u)
    v = np.cross(nn, u)
    c0 = pco.mean(axis=0)
    level = float(np.median((pco - c0) @ nn))
    if tree is None:
        from mathutils import Vector
        from mathutils.bvhtree import BVHTree
        t, _tp = U.tris(me)
        tree = BVHTree.FromPolygons([Vector(x) for x in U.verts(me)], t.tolist(), all_triangles=True)
    pts = _slit_outline(obj, gap, c0, u, v, nn, level, tree)
    if pts is None:
        return None
    # the grid's stair steps out: straight runs become straight (the slab's sides come out flat, no ribs), curves
    # stay curves
    pts = _straighten(pts, 1.2 * SLIT_CELL * gap["gap"])   # one-cell jogs out too
    if len(pts) < 3:
        return None
    inset = inset + 0.5 * SLIT_CELL   # half a cell inside: the slab never stands out of the narrower part
    # set back from the edge: offset inward along the outline's normals
    area2 = float(np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1]))
    tang = np.roll(pts, -1, axis=0) - np.roll(pts, 1, axis=0)
    norm = np.stack([tang[:, 1], -tang[:, 0]], axis=1) * (1.0 if area2 > 0 else -1.0)  # outward
    norm /= np.maximum(np.linalg.norm(norm, axis=1), 1e-12)[:, None]
    pts = _untwist(pts - norm * (inset * gap["gap"]))   # an inset can fold a sharp inner corner into a small loop
    if len(pts) < 3:
        return None
    lo_h, hi_h = level - overlap, level + gap["gap"] + overlap
    gap["_slab"] = {"c0": c0, "u": u, "v": v, "nn": nn, "level": level, "outline": pts.copy(),
                    "heights": (lo_h, hi_h)}
    ring = c0 + pts[:, :1] * u + pts[:, 1:] * v
    bm = bmesh.new()
    bottom = [bm.verts.new(p + nn * lo_h) for p in ring]
    top = [bm.verts.new(p + nn * hi_h) for p in ring]
    try:
        bm.faces.new(bottom[::-1])
        bm.faces.new(top)
        k = len(ring)
        for i in range(k):
            j = (i + 1) % k
            bm.faces.new((bottom[i], bottom[j], top[j], top[i]))
    except ValueError:
        bm.free()
        return None
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4], quad_method='BEAUTY',
                          ngon_method='BEAUTY')
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def _uv_snapshot(obj):
    """Loop positions and UVs of every UV map (to give faces a boolean adds the UVs of the surface next to them)."""
    me = obj.data
    if not me.uv_layers:
        return None
    start, total, lv, _le = U.polys(me)
    pos = U.verts(me)[lv]
    maps = {}
    for lay in me.uv_layers:
        uv = np.empty(len(me.loops) * 2, dtype=np.float32)
        lay.data.foreach_get("uv", uv)
        maps[lay.name] = uv.reshape(-1, 2)
    from mathutils.bvhtree import BVHTree
    from mathutils import Vector
    co = U.verts(me)
    t, _ = U.tris(me)
    tree = BVHTree.FromPolygons([Vector(v) for v in co], t.tolist(), all_triangles=True)
    # which piece each loop is on, and how big the pieces are (a cap floating off a body: two pieces)
    _ids, fa, fb, _c = U.edge_faces(me, start, total, _le)
    comp = U.components(len(me.polygons), np.stack([fa, fb], axis=1))
    lf = U.loop_face(start, total)
    return {"pos": pos, "maps": maps, "tree": tree, "size": U.diag(co) or 1.0, "comp": comp[lf],
            "comp_size": np.bincount(comp)}


def _uvs_for_new_faces(obj, snap, box):
    """Faces the boolean added (the slab in the joint) take the UVs of the nearest original surface point, so a
    texture shows the colour next to the joint there instead of whatever sits at UV 0,0. When the joint closed a
    gap between two separate pieces, only the bigger piece (the body, not the cap) gives its UVs: the slab gets the
    body's colour and the colour border stays at the cap's edge (nearest-point UVs from both sides made stripes)."""
    if snap is None:
        return
    from mathutils import Vector
    from mathutils.kdtree import KDTree
    me = obj.data
    c = U.face_centers(me)
    lo, hi = box
    near_box = np.all((c >= lo) & (c <= hi), axis=1)  # only around the seam
    eps = 1e-5 * snap["size"]
    new = np.zeros(len(c), dtype=bool)
    idx = np.nonzero(near_box)[0]
    new[idx] = [snap["tree"].find_nearest(Vector(c[i]))[3] > eps for i in idx]
    if not new.any():
        return
    cand = np.nonzero(np.all((snap["pos"] >= lo) & (snap["pos"] <= hi), axis=1))[0]
    if len(cand) == 0:
        return
    pieces = np.unique(snap["comp"][cand])
    if len(pieces) > 1:
        body = pieces[np.argmax(snap["comp_size"][pieces])]
        cand = cand[snap["comp"][cand] == body]
    kd = KDTree(len(cand))
    for j, i in enumerate(cand):
        kd.insert(Vector(snap["pos"][i]), j)
    kd.balance()
    start, total, lv, _le = U.polys(me)
    lf = U.loop_face(start, total)
    loops = np.nonzero(new[lf])[0]
    co = U.verts(me)
    near = cand[np.array([kd.find(Vector(co[lv[i]]))[1] for i in loops], dtype=np.int64)]
    for lay in me.uv_layers:
        src = snap["maps"].get(lay.name)
        if src is None:
            continue
        uv = np.empty(len(me.loops) * 2, dtype=np.float32)
        lay.data.foreach_get("uv", uv)
        uv = uv.reshape(-1, 2)
        uv[loops] = src[near]
        lay.data.foreach_set("uv", uv.ravel())
    me.update()


def _boolean_solvers():
    ids = [i.identifier for i in bpy.types.BooleanModifier.bl_rna.properties["solver"].enum_items]
    return [x for x in ("MANIFOLD", "EXACT") if x in ids]  # MANIFOLD: Blender 4.5+, fast; EXACT: 4.2, slower


def _union_fillers(obj, gaps, overlap, inset):
    """Builds the filler slabs (set back `inset` of each gap from the edge) and unions them into the mesh with the
    first boolean solver whose result is closed. Returns the filler points (the seam), or None (mesh unchanged)."""
    bm_all = bmesh.new()
    seam = []
    for g in gaps:
        filler = _gap_filler(obj, g, overlap=overlap, inset=inset)
        if filler is None:
            continue
        seam.append(np.array([v.co[:] for v in filler.verts]))
        tmp = bpy.data.meshes.new("nighty_gap_fill")
        filler.to_mesh(tmp)
        filler.free()
        bm_all.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
    if not seam:
        bm_all.free()
        return None
    fill_me = bpy.data.meshes.new("nighty_gap_fill")
    bm_all.to_mesh(fill_me)
    bm_all.free()
    fill = bpy.data.objects.new("nighty_gap_fill", fill_me)
    bpy.context.scene.collection.objects.link(fill)
    fill.matrix_world = obj.matrix_world.copy()
    before = obj.data.copy()
    nf0 = len(before.polygons)
    done = False
    try:
        for solver in _boolean_solvers():
            mod = obj.modifiers.new("Nighty Join", 'BOOLEAN')
            mod.operation = 'UNION'
            mod.object = fill
            mod.solver = solver
            try:
                U.apply_modifiers(obj, [mod])
            except Exception:  # noqa: BLE001 - try the next solver
                U.replace_mesh(obj, before.copy())
                continue
            st = non_manifold_counts(obj)
            if len(obj.data.polygons) > 0.5 * nf0 and not (st["open_edges"] or st["bad_edges"]):
                done = True
                break
            U.replace_mesh(obj, before.copy())
    finally:
        bpy.data.objects.remove(fill)
        bpy.data.meshes.remove(fill_me)
        bpy.data.meshes.remove(before)
    if done:
        # the boolean leaves big bent n-gons along the new edges: split them into triangles that follow the
        # surface (a fan of a bent n-gon can cut through its neighbour)
        bm = U.bm_from(obj)
        big = [f for f in bm.faces if len(f.verts) > 4]
        if big:
            bmesh.ops.triangulate(bm, faces=big, quad_method='BEAUTY', ngon_method='BEAUTY')
            U.bm_to(bm, obj)
        else:
            bm.free()
    return seam if done else None


SLAB_CLEAR = 0.5    # ... and only this many corner sizes clear of our own slab
CORNER_SIZE = 0.75   # bits in a closed joint's inside corner up to this many gaps big are flattened (a third of a
#                      typical exposed strip); bigger things are real details and stay


def _corner_bits(obj, gap, before=None):
    """Where a closed joint's narrower part stands on a strip of the wider part's face (an inside corner), the
    generator's small lumps and dents in that corner are put onto the corner's two planes: the strip's plane, or the
    narrower part's side wall (whichever is nearer for a lump; the wall for a dent at its foot). Only vertices within
    CORNER_SIZE gaps of the corner that are off both planes move; anything that would make faces cross goes back.
    Returns how many vertices moved."""
    geo = gap.get("_slab")
    if geo is None:
        return 0
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from mathutils.kdtree import KDTree
    me = obj.data
    co = U.verts(me).astype(np.float64)
    g = gap["gap"]
    c0, u, v, nn, level, poly = geo["c0"], geo["u"], geo["v"], geo["nn"], geo["level"], geo["outline"]
    w = CORNER_SIZE * g
    tol = 0.05 * g
    rel = co - c0
    P = np.stack([rel @ u, rel @ v], axis=1)
    h = rel @ nn
    lo, hi = poly.min(axis=0) - 2 * w, poly.max(axis=0) + 2 * w
    cand = np.nonzero(np.all((P >= lo) & (P <= hi), axis=1) & (h > level - 2 * w) & (h < level + g + 2 * w))[0]
    if len(cand) == 0:
        return 0
    # signed distance to the outline (positive outside) and the outward normal of the nearest piece of it
    a, b = poly, np.roll(poly, -1, axis=0)
    ab = b - a
    q = P[cand]
    t = np.clip(np.einsum("nkj,kj->nk", q[:, None, :] - a[None], ab) / np.maximum((ab ** 2).sum(1), 1e-30), 0, 1)
    near = a[None] + t[..., None] * ab[None]
    dist = np.linalg.norm(q[:, None, :] - near, axis=2)
    k = np.argmin(dist, axis=1)
    area2 = float(np.sum(a[:, 0] * b[:, 1] - b[:, 0] * a[:, 1]))
    nrm = np.stack([ab[:, 1], -ab[:, 0]], axis=1) * (1.0 if area2 > 0 else -1.0)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1), 1e-30)[:, None]
    side = np.einsum("nj,nj->n", q - near[np.arange(len(q)), k], nrm[k])
    sd = dist[np.arange(len(q)), k] * np.sign(side + 1e-30)
    # which wall is the strip: the wider part's face, found just outside the outline
    t_, _tp = U.tris(me)
    tree = BVHTree.FromPolygons([Vector(x) for x in co], t_.tolist(), all_triangles=True)
    probe = poly + nrm * (2.0 * SLIT_CELL * g)
    down = up = 0
    for p2 in probe[:: max(1, len(probe) // 60)]:
        m = c0 + u * p2[0] + v * p2[1] + nn * (level + 0.5 * g)
        down += tree.ray_cast(Vector(m), Vector(-nn), 1.5 * g)[0] is not None
        up += tree.ray_cast(Vector(m), Vector(nn), 1.5 * g)[0] is not None
    if max(up, down) == 0:
        return 0
    strip_h, sgn = (level, 1.0) if down >= up else (level + g, -1.0)
    hh = h[cand]
    e1 = sgn * (hh - strip_h)          # how far off the strip, into the open corner
    # only the generator's own surface: the slab's new faces are neither a wall to fit nor a bit to move
    orig = np.ones(len(cand), dtype=bool)
    if before is not None:
        eps = 1e-5 * (U.diag(co) or 1.0)
        orig = np.array([before.find_nearest(Vector(co[i]))[3] <= eps for i in cand])
    # where the narrower part's side wall stands: its vertices a little above the corner, near the outline
    wall = (e1 > 2.5 * w) & (e1 < 5 * w) & (sd > -w) & (sd < 3 * w) & orig   # clear of the corner's bits
    if wall.sum() < 8:
        return 0
    kd = KDTree(int(wall.sum()))
    widx = np.nonzero(wall)[0]
    for j, i in enumerate(widx):
        kd.insert(Vector(co[cand[i]] - nn * (sgn * (hh[i] - strip_h))), j)   # dropped onto the strip's level
    kd.balance()
    zone = (e1 > tol) & (e1 <= 2 * w) & (sd > -w) & (sd < 4 * w) & orig
    # only where the generator had joined the parts itself (its own lumpy surface, no slab beside): next to the
    # slab the corner is ours already, and moving the generator's faces there pulls hidden faces into view
    lo_h, hi_h = geo["heights"]
    ring = c0 + poly[:, :1] * u + poly[:, 1:] * v
    kk = len(ring)
    slab_pts = [Vector(x) for x in np.vstack([ring + nn * lo_h, ring + nn * hi_h])]
    slab_tris = [(i, (i + 1) % kk, kk + (i + 1) % kk) for i in range(kk)] + [(i, kk + (i + 1) % kk, kk + i)
                                                                            for i in range(kk)]
    slab_side = BVHTree.FromPolygons(slab_pts, slab_tris)
    for i in np.nonzero(zone)[0]:
        if slab_side.find_nearest(Vector(co[cand[i]]))[3] <= SLAB_CLEAR * w:
            zone[i] = False
    # the side wall as a plane fitted to its vertices next to each spot (it need not follow the slab's outline:
    # where the parts were already joined by the generator there is no slab beside it)
    start, total, lv, _le = U.polys(me)
    lf = U.loop_face(start, total)
    fn = U.face_normals(me).astype(np.float64)
    fa_ = U.face_areas(me)
    vn = np.zeros_like(co)
    np.add.at(vn, lv, fn[lf] * fa_[lf][:, None])
    moved = 0
    new = co.copy()
    plane_n = np.zeros_like(co)
    for i in np.nonzero(zone)[0]:
        found = kd.find_n(Vector(co[cand[i]] - nn * (sgn * (hh[i] - strip_h))), 24)
        if len(found) < 8:
            continue
        pts = co[cand[widx[[j for _c, j, _d in found]]]]
        if np.linalg.norm(pts - co[cand[i]], axis=1).min() > 2 * w:   # no wall of the generator's close by
            continue
        cen = pts.mean(axis=0)
        _u_, sv, vt = np.linalg.svd(pts - cen, full_matrices=False)
        nw = vt[2]
        if sv[1] < 1e-9 or abs(float(nw @ nn)) > 0.5:   # not a wall standing up off the strip
            continue
        if float(vn[cand[widx[[j for _c, j, _d in found]]]].sum(axis=0) @ nw) < 0:
            nw = -nw                                        # outward, like the wall's own normals
        vi = cand[i]
        e2 = float((co[vi] - cen) @ nw)    # > 0: standing out of the side wall; < 0: a dent into it
        if abs(e2) <= tol or abs(e2) > w:
            continue
        if 0 < e2 and e1[i] <= e2:
            new[vi] = co[vi] - nn * (sgn * e1[i])                            # onto the strip
            plane_n[vi] = nn
        else:
            new[vi] = co[vi] - nw * e2                                       # onto the side wall
            plane_n[vi] = nw
        moved += 1
    if not moved:
        return 0
    # even the moved vertices out within their plane (projected bits bunch up into slivers otherwise)
    mv = np.nonzero(np.linalg.norm(plane_n, axis=1) > 0)[0]
    ev = U.edges(me)
    nb_sum = np.zeros_like(co)
    for _ in range(4):
        nb_sum[:] = 0.0
        np.add.at(nb_sum, ev[:, 0], new[ev[:, 1]])
        np.add.at(nb_sum, ev[:, 1], new[ev[:, 0]])
        deg = np.bincount(ev.ravel(), minlength=len(co))[:, None]
        step = 0.5 * (nb_sum[mv] / np.maximum(deg[mv], 1) - new[mv])
        step -= plane_n[mv] * np.einsum("ij,ij->i", step, plane_n[mv])[:, None]   # stay in the plane
        new[mv] += step
    U.set_verts(me, new)
    from .fragments import _put_back_crossings
    mask = np.zeros(len(co), dtype=bool)
    mask[np.nonzero(np.linalg.norm(new - co, axis=1) > 0)[0]] = True
    box = (co[mask].min(axis=0) - 2 * w, co[mask].max(axis=0) + 2 * w)
    if not _put_back_crossings(obj, co, mask, [box], U.diag(co) or 1.0):
        return 0
    return int((np.linalg.norm(U.verts(me) - co, axis=1) > 0).sum())


def join_gaps(obj, tol=0.012, min_extent=0.06):
    """Joins parts that a generator left floating a few millimetres apart (see find_gaps): each joint is closed
    completely by a slab that fills the whole slit out to where it opens to the outside (see _slit_outline),
    unioned into the mesh with a boolean (only there: nothing else moves). The colors (clean_colors) draw the border
    between the parts, so no seam line is kept. Returns a list of what was joined."""
    gaps = find_gaps(obj, tol, min_extent)
    if not gaps:
        return []
    size = U.diag(U.verts(obj.data)) or 1.0
    overlap = max(0.0015 * size, 0.25 * min(g["gap"] for g in gaps))
    uv_src = _uv_snapshot(obj)
    if uv_src is not None:
        pre_tree = uv_src["tree"]
    else:   # the surface before the join (to tell the slab's new faces from the generator's own)
        from mathutils import Vector
        from mathutils.bvhtree import BVHTree
        t, _tp = U.tris(obj.data)
        pre_tree = BVHTree.FromPolygons([Vector(x) for x in U.verts(obj.data)], t.tolist(), all_triangles=True)
    seam = None
    for inset in SEAM_INSETS:
        seam = _union_fillers(obj, gaps, overlap, inset)
        if seam is not None:
            break
    if seam is None:
        return []
    pts_all = np.concatenate(seam)
    pad = 3.0 * max(g["gap"] for g in gaps)
    _uvs_for_new_faces(obj, uv_src, (pts_all.min(axis=0) - pad, pts_all.max(axis=0) + pad))
    bits = [_corner_bits(obj, g, before=pre_tree) for g in gaps]
    return [{"gap_mm": round(g["gap"] * 1000, 1), "area_cm2": round(g["area"] * 1e4, 1),
             "width_cm": round(g["extent"] * 100, 1), "corner_bits": n} for g, n in zip(gaps, bits)]


def cleanup(obj, weld_distance="auto", floaters=0.03, keep_largest=False, holes=True, max_hole_sides=0,
            manifold="auto", voxel_size=None, normals=True, transforms=True, size=None, size_axis="longest",
            origin="bottom", to_ground=True, flatten="auto", join="auto", progress=None):
    """The whole cleanup on one mesh object, in place. Returns a report dict.

    manifold: 'auto' (targeted fixes, voxel rebuild only if still broken) | 'voxel' (always rebuild) |
    'fix' (targeted fixes only) | 'off'. flatten: 'auto' (hard-surface shapes get truly flat sides and crisp edges,
    see flatten_planes) | True | False. join: 'auto' / True: parts floating a few millimetres off each other
    (a generator's plate-like gaps, see find_gaps) become one solid | False.
    """
    p = U.Progress(progress)
    t0 = time.monotonic()
    U.require_mesh(obj)
    before = S.analyze(obj)
    rep = {"object": obj.name, "before": S.short(before), "steps": []}
    if transforms and apply_transforms(obj):
        rep["steps"].append("applied transforms")
    p(0.05, "welding")
    if weld_distance is not False:
        merged, d = weld(obj, weld_distance)
        if merged:
            rep["steps"].append(f"welded {merged:,} vertices ({U.fmt_len(d)})")
    p(0.2, "removing floaters")
    if floaters is not False and floaters is not None:
        removed, kept = remove_floaters(obj, float(floaters or 0.0), keep_largest)
        if removed:
            rep["steps"].append(f"removed {removed} floater{'s' if removed != 1 else ''} (kept {kept} part{'s' if kept != 1 else ''})")
    p(0.35, "filling holes")
    if holes:
        n = fill_holes(obj, max_hole_sides)
        if n:
            rep["steps"].append(f"filled {n} hole{'s' if n != 1 else ''}")
    if normals:
        recalc_normals(obj)
    nm = non_manifold_counts(obj)
    broken = nm["bad_edges"] or nm["bad_verts"] or nm["open_edges"]
    if manifold == "auto" and broken and obj.data.uv_layers and nm["open_edges"] <= 60:
        # a textured model (an AI model) with a few broken spots: cut them out and close them; a voxel rebuild
        # would throw its UVs and so its texture away (generated models often come with 2-6 such spots)
        n = repair_spots(obj)
        if n:
            nm2 = non_manifold_counts(obj)
            rep["steps"].append(f"repaired {nm['open_edges'] + nm['bad_edges'] + nm['bad_verts']} broken spots "
                                f"({n} faces around them rebuilt; the UVs and texture kept)")
            nm = nm2
            broken = nm["bad_edges"] or nm["bad_verts"] or nm["open_edges"]
    rebuild = manifold == "voxel" or (manifold == "auto" and broken)
    if rebuild:
        p(0.5, "voxel rebuild")
        keep = obj.data.copy()
        area0 = S.analyze(obj)["area"]
        vs = voxel_remesh(obj, voxel_size)
        area1 = S.analyze(obj)["area"]
        if not (0.3 * area0 <= area1 <= 1.6 * area0):
            # an open surface does not give a clean volume: keep the mesh as it was and say so
            U.replace_mesh(obj, keep)
            rep["steps"].append(f"voxel rebuild skipped: the surface is not closed enough ({nm['open_edges']} open "
                                f"edges left)")
            rebuild = False
        else:
            bpy.data.meshes.remove(keep)
            rep["steps"].append(f"rebuilt watertight (voxel {U.fmt_len(vs)}; was {nm['open_edges']} open / "
                                f"{nm['bad_edges']} bad edges / {nm['bad_verts']} bad vertices)")
    if rebuild:
        if floaters is not False and floaters is not None:
            removed, _kept = remove_floaters(obj, float(floaters or 0.0), keep_largest)
            if removed:
                rep["steps"].append(f"removed {removed} more floater{'s' if removed != 1 else ''}")
        if normals:
            recalc_normals(obj)
    if join and manifold != "off":
        p(0.65, "joining floating parts")
        joined = join_gaps(obj)
        for j in joined:
            more = f", {j['corner_bits']} bits in its inside corner flattened" if j.get("corner_bits") else ""
            rep["steps"].append(f"joined a part floating {j['gap_mm']} mm off ({j['width_cm']} cm wide){more}")
        if joined:
            if floaters is not False and floaters is not None:
                remove_floaters(obj, float(floaters or 0.0), keep_largest)
            if normals:
                recalc_normals(obj)
        # the generator's tiny spikes and pits left in narrow grooves
        from .fragments import smooth_fragments
        bits = smooth_fragments(obj)
        if bits:
            rep["steps"].append(f"smoothed {len(bits)} tiny spikes / pits in narrow grooves "
                                f"(at most {max(b['moved_mm'] for b in bits)} mm)")
    if flatten:
        p(0.75, "flat sides")
        if flatten == "auto":
            from .shape import classify
            flatten = classify(obj)["kind"] == "hard_surface"
        if flatten:
            n_planes, moved = flatten_planes(obj)
            if n_planes:
                rep["steps"].append(f"made {n_planes} flat side{'s' if n_planes != 1 else ''} truly flat "
                                    f"({moved:,} vertices)")
    p(0.85, "size and ground")
    if size:
        f = set_size(obj, size, size_axis)
        rep["steps"].append(f"scaled x{f:.4g} to {U.fmt_len(float(size))} ({size_axis})")
    if origin != "keep" or to_ground:
        ground(obj, origin, to_ground)
        if to_ground:
            rep["steps"].append("on the ground, origin at the bottom center" if origin == "bottom" else "on the ground")
    after = S.analyze(obj)
    rep["after"] = S.short(after)
    rep["manifold"] = after["manifold"]
    rep["faces"] = after["faces"]
    rep["parts"] = after["parts"]
    rep["size_m"] = after["size"]
    rep["seconds"] = round(time.monotonic() - t0, 2)
    p(1.0, "done")
    return rep
