# SPDX-License-Identifier: GPL-3.0-or-later
"""Split a mesh into parts (barrel, scope, grip...): by loose pieces, by regions between sharp or concave edges, by
material, by cutting planes, or by labels an AI part-segmentation model wrote (the engine's job later: it registers
a segmenter here, or writes an integer face attribute 'nighty_part')."""

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from . import _util as U

_SEGMENTERS = {}


def register_segmenter(name, fn):
    """fn(obj) -> (face_labels: sequence of int per face, names: dict label -> name or None). Used by
    split_parts(method='ai' or method=name). The engine registers its part-segmentation model here."""
    _SEGMENTERS[name] = fn


def segmenters():
    return sorted(_SEGMENTERS)


def _region_labels(me, cut_edges):
    """Faces connected across manifold edges that are not cut -> region label per face."""
    start, total, lv, le = U.polys(me)
    ids, fa, fb, _count = U.edge_faces(me, start, total, le)
    keep = ~cut_edges[ids]
    return U.components(len(start), np.stack([fa[keep], fb[keep]], axis=1))


PROXY_FACES = 8000


def _crease_labels(me, method, angle):
    if method == "concave":
        return _concave_parts(me, angle)
    start, total, lv, le = U.polys(me)
    ids, ang, concave = U.dihedral(me, start, total, le)
    cut = np.zeros(len(me.edges), dtype=bool)
    cut[ids[ang > float(angle)]] = True
    cut |= U.edge_flags(me, "use_edge_sharp")
    return _region_labels(me, cut)


def _concave_parts(me, angle):
    """Parts meet at inner (concave) creases: a barrel goes into a receiver, a scope sits on a rail. First the mesh
    is cut into smooth patches at every crease; then neighbouring patches join again unless most of the border
    between them is concave. Deciding per border (not per edge) keeps it working on noisy, decimated meshes."""
    start, total, lv, le = U.polys(me)
    ids, ang, concave = U.dihedral(me, start, total, le)
    cut = np.zeros(len(me.edges), dtype=bool)
    cut[ids[ang > min(float(angle), 20.0)]] = True  # over-cutting is fine: the vote below joins convex borders
    patch = _merge_small(me, _region_labels(me, cut), 0.001)
    ids2, fa, fb, _c = U.edge_faces(me, start, total, le)  # same edge order as dihedral()
    co = U.verts(me)
    e = U.edges(me)[ids2]
    elen = np.linalg.norm(co[e[:, 0]] - co[e[:, 1]], axis=1)
    pa, pb = patch[fa], patch[fb]
    border = pa != pb
    k = int(patch.max() + 1)
    lo, hi = np.minimum(pa, pb)[border], np.maximum(pa, pb)[border]
    key = lo * k + hi
    uk, inv = np.unique(key, return_inverse=True)
    total_len = np.bincount(inv, weights=elen[border])
    conc_len = np.bincount(inv, weights=elen[border] * (concave[border] & (ang[border] > 8.0)))
    join = conc_len < 0.5 * total_len
    pairs = np.stack([uk[join] // k, uk[join] % k], axis=1)
    lab = U.components(k, pairs)
    return lab[patch]


def _proxy_labels(obj, method, angle, target=PROXY_FACES):
    """Regions found on a small decimated copy (noise and voxel-rounded creases become clean single edges there),
    carried back to every face of the dense mesh by the nearest proxy face, then made connected again."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    me = obj.data
    tmp = bpy.data.objects.new("_nighty_parts_proxy", me.copy())
    bpy.context.scene.collection.objects.link(tmp)
    try:
        _s, tot, _lv, _le = U.polys(me)
        mod = tmp.modifiers.new("d", 'DECIMATE')
        mod.ratio = min(1.0, target / max(int((tot - 2).sum()), 1))
        mod.use_collapse_triangulate = True
        U.apply_modifiers(tmp, [mod])
        pm = tmp.data
        plab = _merge_small(pm, _crease_labels(pm, method, angle), 0.004)
        pco = U.verts(pm)
        ps, pt, plv, _ple = U.polys(pm)
        polys = [plv[a:a + b].tolist() for a, b in zip(ps, pt)]
        tree = BVHTree.FromPolygons([Vector(v) for v in pco], polys)
        centers = U.face_centers(me)
        lab = np.empty(len(centers), dtype=np.int64)
        for i, c in enumerate(centers):
            hit = tree.find_nearest(Vector(c))
            lab[i] = plab[hit[2]] if hit[2] is not None else 0
    finally:
        m2 = tmp.data
        bpy.data.objects.remove(tmp)
        bpy.data.meshes.remove(m2)
    # nearest-face carry-over can leave stray specks: keep each label connected
    start, total, lv, le = U.polys(me)
    ids, fa, fb, _c = U.edge_faces(me, start, total, le)
    same = lab[fa] == lab[fb]
    return U.components(len(lab), np.stack([fa[same], fb[same]], axis=1))


def _merge_small(me, labels, min_area_frac):
    """Regions smaller than min_area_frac of the total area join the neighbour they share most border with."""
    if min_area_frac <= 0:
        return labels
    area = U.face_areas(me)
    start, total, lv, le = U.polys(me)
    ids, fa, fb, _c = U.edge_faces(me, start, total, le)
    co = U.verts(me)
    e = U.edges(me)[ids]
    elen = np.linalg.norm(co[e[:, 0]] - co[e[:, 1]], axis=1)
    tot = area.sum() or 1.0
    labels = labels.copy()
    for _ in range(50):
        k = int(labels.max() + 1)
        ra = np.bincount(labels, weights=area, minlength=k)
        present = np.nonzero(ra > 0)[0]
        if len(present) <= 1:
            break
        small = (ra < min_area_frac * tot) & (ra > 0)
        if not small.any():
            break
        la, lb = labels[fa], labels[fb]
        border = la != lb
        # both directions: (region, neighbour, shared border length)
        r = np.concatenate([la[border], lb[border]])
        nb = np.concatenate([lb[border], la[border]])
        w = np.concatenate([elen[border], elen[border]])
        m = small[r]
        r, nb, w = r[m], nb[m], w[m]
        if len(r) == 0:
            break
        key = r * k + nb
        uk, inv = np.unique(key, return_inverse=True)
        wsum = np.bincount(inv, weights=w)
        ur, unb = uk // k, uk % k
        # prefer the neighbour with the longest shared border; tie-break toward bigger regions
        score = wsum + ra[unb] * 1e-9
        best = np.full(k, -1, dtype=np.int64)
        best_s = np.full(k, -1.0)
        for a, b, s in zip(ur.tolist(), unb.tolist(), score.tolist()):
            if s > best_s[a]:
                best_s[a], best[a] = s, b
        # merge only the smallest of two small regions that point at each other (no swaps)
        mapping = np.arange(k)
        for a in np.nonzero(best >= 0)[0]:
            b = best[a]
            if best[b] == a and ra[b] < ra[a]:
                continue
            mapping[a] = b
        for _j in range(32):  # resolve chains a -> b -> c
            nxt = mapping[mapping]
            if np.array_equal(nxt, mapping):
                break
            mapping = nxt
        labels = mapping[labels]
    _, labels = np.unique(labels, return_inverse=True)
    return labels.reshape(-1)


def _where(c, lo, hi):
    """'top front left' style words for a part's center inside the whole bounding box (Blender's front view:
    -Y is front, +X is right, +Z is up)."""
    ext = np.maximum(hi - lo, 1e-9)
    t = (c - lo) / ext
    w = []
    if t[2] > 0.66:
        w.append("top")
    elif t[2] < 0.34:
        w.append("bottom")
    if t[1] < 0.34:
        w.append("front")
    elif t[1] > 0.66:
        w.append("back")
    if t[0] < 0.34:
        w.append("left (-X)")
    elif t[0] > 0.66:
        w.append("right (+X)")
    return " ".join(w) or "middle"


def _form(size):
    s = np.sort(np.asarray(size, dtype=float))[::-1]
    if s[0] <= 0:
        return "point"
    if s[1] < s[0] * 0.3:
        return "long" if s[2] > s[1] * 0.4 else "long and flat"
    if s[2] < s[0] * 0.2:
        return "flat"
    return "chunky"


def _plane_labels(obj, planes):
    """Cuts the mesh along each plane (real cut edges), then labels faces by side."""
    bm = U.bm_from(obj)
    for pl in planes:
        co = Vector(pl.get("point", (0, 0, 0)))
        no = Vector(pl.get("normal", (1, 0, 0))).normalized()
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-6, plane_co=co, plane_no=no, clear_inner=False,
                               clear_outer=False)
    U.bm_to(bm, obj)
    c = U.face_centers(obj.data)
    lab = np.zeros(len(c), dtype=np.int64)
    for i, pl in enumerate(planes):
        no = np.array(pl.get("normal", (1, 0, 0)), dtype=float)
        no = no / (np.linalg.norm(no) or 1.0)
        side = (c - np.array(pl.get("point", (0, 0, 0)), dtype=float)) @ no > 0
        lab |= side.astype(np.int64) << i
    _, lab = np.unique(lab, return_inverse=True)
    return lab.reshape(-1)


def labels_for(obj, method="auto", angle=30.0, planes=None, attribute="nighty_part"):
    """(face labels, names or None, method used, why)."""
    me = obj.data
    nf = len(me.polygons)
    if method == "auto":
        comp = U.face_components(me)
        if comp.max() + 1 > 1:
            return comp, None, "loose", "it has separate loose pieces"
        if len(me.materials) > 1 and len(np.unique(U.face_materials(me))) > 1:
            return U.face_materials(me), None, "material", "one piece; split by its materials"
        return labels_for(obj, "concave", angle)[:2] + ("concave", "one piece; split where parts meet at inner "
                                                                    "(concave) creases")
    if method == "loose":
        return U.face_components(me), None, "loose", ""
    if method == "material":
        return U.face_materials(me), None, "material", ""
    if method in ("sharp", "concave"):
        if nf > PROXY_FACES * 1.5:
            return _proxy_labels(obj, method, angle), None, method, ""
        return _crease_labels(me, method, angle), None, method, ""
    if method == "plane":
        if not planes:
            raise ValueError("method 'plane' needs planes: [{point: [x,y,z], normal: [x,y,z]}]")
        return _plane_labels(obj, planes), None, "plane", ""
    if method == "attribute":
        a = me.attributes.get(attribute)
        if a is None or a.domain != 'FACE':
            raise ValueError(f"no face attribute {attribute!r} on {obj.name!r}")
        buf = np.zeros(nf, dtype=np.int32)
        a.data.foreach_get("value", buf)
        names = obj.get("nighty_part_names")
        return buf.astype(np.int64), (dict(names) if names else None), "attribute", ""
    seg = _SEGMENTERS.get(method) or (_SEGMENTERS.get(next(iter(_SEGMENTERS))) if method == "ai" and _SEGMENTERS else None)
    if seg is None:
        if method == "ai":
            raise ValueError("AI part segmentation comes with the engine (not installed yet); use loose, concave, "
                             "sharp, material or plane")
        raise ValueError(f"unknown split method {method!r}")
    lab, names = seg(obj)
    return np.asarray(lab, dtype=np.int64), names, method, "AI part segmentation"


def split_parts(obj, method="auto", angle=30.0, planes=None, min_size=0.01, names=None, cap=None,
                attribute="nighty_part", keep_original=False, progress=None):
    """Splits one mesh object into part objects. Returns (parts, report).

    min_size: parts with less than this share of the surface (0.01 = 1%) join a neighbour (region methods) or are
    kept as they are (loose / material / attribute). names: list of names in the reported order (biggest first)
    or a dict {label: name}. cap: close the cut openings of each part ('plane' does by default).
    The original object is removed (keep_original=True hides it instead). Parts keep the object's origin,
    transform, materials, UVs and the bake source link."""
    p = U.Progress(progress)
    U.require_mesh(obj)
    me = obj.data
    p(0.05, "finding parts")
    lab, auto_names, used, why = labels_for(obj, method, angle, planes, attribute)
    if used in ("sharp", "concave", "plane"):
        lab = _merge_small(obj.data, lab, float(min_size or 0))
    me = obj.data
    k = int(lab.max() + 1) if len(lab) else 0
    area = U.face_areas(me)
    ra = np.bincount(lab, weights=area, minlength=k)
    order = [int(i) for i in np.argsort(-ra) if ra[i] > 0 or k == 1]
    if cap is None:
        cap = used == "plane"
    co_w = U.world_verts(obj)
    lo, hi = U.bbox(co_w)
    base = obj.name
    parts, rows = [], []
    src = obj.get("nighty_bake_source")
    for n, l in enumerate(order):
        p(0.1 + 0.8 * n / max(len(order), 1), f"part {n + 1} of {len(order)}")
        if isinstance(names, dict):
            nm = names.get(str(l)) or names.get(l)
        elif isinstance(names, (list, tuple)) and n < len(names):
            nm = names[n]
        else:
            nm = (auto_names.get(l) or auto_names.get(str(l))) if auto_names else None
        label = nm or f"part{n + 1:02d}"
        mesh = U.submesh(me, lab == l, f"{me.name}_{label}")
        ob = bpy.data.objects.new(f"{base}_{label}", mesh)
        ob.matrix_world = obj.matrix_world.copy()
        ob.parent = obj.parent
        if obj.parent is not None:
            ob.matrix_parent_inverse = obj.matrix_parent_inverse.copy()
        for col in obj.users_collection or [bpy.context.scene.collection]:
            col.objects.link(ob)
        if src is not None:
            ob["nighty_bake_source"] = src
            ob["nighty_high"] = getattr(src, "name", src)
        ob["nighty_part_of"] = base
        if cap:
            from .fix import fill_holes
            fill_holes(ob)
        pc = U.world_verts(ob)
        plo, phi = U.bbox(pc)
        size = phi - plo
        rows.append({"name": ob.name, "faces": len(mesh.polygons),
                     "size_m": [round(float(x), 4) for x in size],
                     "center": [round(float(x), 4) for x in (plo + phi) / 2],
                     "where": _where((plo + phi) / 2, lo, hi), "form": _form(size),
                     "area_share": round(float(ra[l] / (ra.sum() or 1)), 4)})
        parts.append(ob)
    if keep_original:
        obj.hide_set(True)
        obj.hide_render = True
    else:
        bpy.data.objects.remove(obj)
    rep = {"method": used, "parts": rows, "count": len(parts)}
    if why:
        rep["why"] = why
    p(1.0, "done")
    return parts, rep
