# SPDX-License-Identifier: GPL-3.0-or-later
"""UV unwrapping: seams from sharp edges and angle (hard-surface) or Smart UV Project (organic), islands packed with
a margin that fits the texture size, the same texel density on every part, and an overlap check."""

import math
import time

import bmesh
import bpy
import numpy as np

from . import _util as U

# space between islands in pixels per texture size (bakes bleed into it); smaller when there are many islands
MARGIN_PX = {512: 4, 1024: 8, 2048: 12, 4096: 16, 8192: 24}
_LAST = {}


def texture_px(size):
    if isinstance(size, str):
        s = size.strip().upper()
        if s.endswith("K"):
            return int(float(s[:-1]) * 1024)
        return int(s)
    return int(size or 2048)


# ---------------------------------------------------------------- reading UVs

def _uvs(me, name=None):
    lay = me.uv_layers.get(name) if name else me.uv_layers.active
    if lay is None:
        return None
    uv = np.empty(len(me.loops) * 2, dtype=np.float32)
    lay.data.foreach_get("uv", uv)
    return uv.reshape(-1, 2).astype(np.float64)


def _raster(tri_uv, res, flag=False):
    """Counts how many UV triangles cover each pixel center (shared edges count once). flag=True also returns the
    triangles that touch a pixel covered more than once."""
    grid = np.zeros((res, res), dtype=np.int32)
    hits = []
    p = tri_uv * res - 0.5  # pixel centers at integer coordinates
    lo = np.floor(p.min(axis=1)).astype(np.int64) + 1
    hi = np.floor(p.max(axis=1)).astype(np.int64)
    lo = np.clip(lo, 0, res - 1)
    hi = np.clip(hi, -1, res - 1)
    w = hi - lo + 1
    h = w[:, 1]
    w = w[:, 0]
    ok = (w > 0) & (h > 0)
    a, b, c = p[:, 0], p[:, 1], p[:, 2]
    den = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
    ok &= np.abs(den) > 0.5  # needle triangles under a quarter pixel cover nothing (and only add noise)
    eps = 2e-4  # UVs are float32: pixel centres on a shared edge must not count for both triangles

    def fill(idx, kx, ky):
        if len(idx) == 0:
            return
        ox, oy = np.meshgrid(np.arange(kx), np.arange(ky), indexing="ij")
        ox, oy = ox.ravel(), oy.ravel()
        px = lo[idx, 0][:, None] + ox[None, :]
        py = lo[idx, 1][:, None] + oy[None, :]
        inb = (px <= hi[idx, 0][:, None]) & (py <= hi[idx, 1][:, None])
        A, B, C, D = a[idx], b[idx], c[idx], den[idx][:, None]
        l1 = ((B[:, 1] - C[:, 1])[:, None] * (px - C[:, 0][:, None]) + (C[:, 0] - B[:, 0])[:, None] * (py - C[:, 1][:, None])) / D
        l2 = ((C[:, 1] - A[:, 1])[:, None] * (px - C[:, 0][:, None]) + (A[:, 0] - C[:, 0])[:, None] * (py - C[:, 1][:, None])) / D
        l3 = 1 - l1 - l2
        inside = inb & (l1 > eps) & (l2 > eps) & (l3 > eps)
        np.add.at(grid, (px[inside], py[inside]), 1)
        if flag:
            rows = np.nonzero(inside)[0]
            hits.append((idx[rows], px[inside], py[inside]))

    small = ok & (w <= 8) & (h <= 8)
    fill(np.nonzero(small)[0], 8, 8)
    mid = ok & ~small & (w <= 32) & (h <= 32)
    idx = np.nonzero(mid)[0]
    for s in range(0, len(idx), 2000):
        fill(idx[s:s + 2000], 32, 32)
    for i in np.nonzero(ok & ~small & ~mid)[0]:
        fill(np.array([i]), int(w[i]), int(h[i]))
    if flag:
        bad = set()
        for t, x, y in hits:
            m = grid[x, y] > 1
            if m.any():
                bad.update(np.unique(t[m]).tolist())
        return grid, np.array(sorted(bad), dtype=np.int64)
    return grid


def overlap_faces(objs, res=1024, name=None):
    """{object name: bool mask of faces whose UVs overlap something} (empty when there is no overlap): islands that
    fold over themselves (exact) plus anything covering a pixel twice."""
    tri_uv, owners = [], []
    for o in U.as_objects(objs):
        uv = _uvs(o.data, name)
        if uv is None:
            continue
        lo = U.tri_loops(o.data)
        _t, tp = U.tris(o.data)
        tri_uv.append(uv[lo])
        owners.append((o, tp))
    if not tri_uv:
        return {}
    _g, bad = _raster(np.concatenate(tri_uv), res, flag=True)
    out = {}
    base = 0
    for o, tp in owners:
        sel = bad[(bad >= base) & (bad < base + len(tp))] - base
        m = folded_faces(o.data) if name is None else np.zeros(len(o.data.polygons), dtype=bool)
        m[tp[sel]] = True
        if m.any():
            out[o.name] = m
        base += len(tp)
    return out


def uv_overlap(objs, res=1024, name=None):
    """Share of the used UV pixels covered more than once (0 = no overlaps), over all objects together (they share
    one texture)."""
    tri_uv = []
    for o in U.as_objects(objs):
        uv = _uvs(o.data, name)
        if uv is None:
            continue
        lo = U.tri_loops(o.data)
        tri_uv.append(uv[lo])
    if not tri_uv:
        return None
    g = _raster(np.concatenate(tri_uv), res)
    used = int((g > 0).sum())
    over = int((g > 1).sum())
    return {"overlap": round(over / used, 5) if used else 0.0, "overlap_px": over, "coverage": round(used / res ** 2, 4)}


def uv_report(objs, texture_size=2048, name=None):
    """Per object: islands, UV area, texel density (pixels per meter); plus overlap for all together."""
    size = texture_px(texture_size)
    rows = []
    dens = []
    for o in U.as_objects(objs):
        me = o.data
        uv = _uvs(me, name)
        if uv is None:
            rows.append({"name": o.name, "uv": False})
            continue
        lo = U.tri_loops(me)
        t, _tp = U.tris(me)
        co = U.world_verts(o)
        a3 = 0.5 * np.linalg.norm(np.cross(co[t[:, 1]] - co[t[:, 0]], co[t[:, 2]] - co[t[:, 0]]), axis=1).sum()
        u = uv[lo]
        a2 = 0.5 * np.abs((u[:, 1, 0] - u[:, 0, 0]) * (u[:, 2, 1] - u[:, 0, 1]) -
                          (u[:, 2, 0] - u[:, 0, 0]) * (u[:, 1, 1] - u[:, 0, 1])).sum()
        d = math.sqrt(a2 / a3) * size if a3 > 0 else 0.0
        dens.append(d)
        rows.append({"name": o.name, "islands": len(islands(me)), "uv_area": round(float(a2), 4),
                     "px_per_m": round(d, 1)})
    out = {"objects": rows, "texture": size}
    if dens:
        out["texel_spread"] = round(max(dens) / max(min(dens), 1e-9), 3)
    ov = uv_overlap(objs, name=name)
    if ov:
        out.update(ov)
    out["folded_faces"] = int(sum(folded_faces(o.data).sum() for o in U.as_objects(objs) if o.data.uv_layers))
    return out


def _island_data(me):
    """(island label per face, edge ids, face a, face b, same-UV flag per edge) or None without UVs."""
    uv = _uvs(me)
    start, total, lv, le = U.polys(me)
    if uv is None or len(start) == 0:
        return None
    ids, fa, fb, _c = U.edge_faces(me, start, total, le)
    lf = U.loop_face(start, total)
    nvp = len(me.vertices) + 1
    fv = lf * nvp + lv  # per face-vertex uv lookup via sort
    order = np.argsort(fv)
    fv_s = fv[order]
    e = U.edges(me)[ids]

    def uv_at(f, v):
        pos = np.searchsorted(fv_s, f * nvp + v)
        return uv[order[np.clip(pos, 0, len(order) - 1)]]

    same = (np.abs(uv_at(fa, e[:, 0]) - uv_at(fb, e[:, 0])).max(axis=1) < 1e-6) &            (np.abs(uv_at(fa, e[:, 1]) - uv_at(fb, e[:, 1])).max(axis=1) < 1e-6)
    lab = U.components(len(start), np.stack([fa[same], fb[same]], axis=1))
    return lab, ids, fa, fb, same


def islands(me):
    """UV islands: faces joined by edges whose UVs match on both sides (list of face index arrays)."""
    d = _island_data(me)
    if d is None:
        return []
    lab = d[0]
    order = np.argsort(lab, kind="stable")
    cuts = np.searchsorted(lab[order], np.arange(lab.max() + 2))
    return [order[cuts[i]:cuts[i + 1]] for i in range(lab.max() + 1)]


def folded_faces(me):
    """Faces of islands that overlap themselves, found exactly (not by pixels): a triangle facing the other way, or
    the island's border crossing itself (a thin triangle folded over its neighbour, a tube flattened onto itself)."""
    d = _island_data(me)
    nf = len(me.polygons)
    out = np.zeros(nf, dtype=bool)
    if d is None:
        return out
    lab, ids, fa, fb, same = d
    uv = _uvs(me)
    start, total, lv, le = U.polys(me)
    # 1) flipped triangles
    lo = U.tri_loops(me)
    _t, tp = U.tris(me)
    u = uv[lo]
    sa = 0.5 * ((u[:, 1, 0] - u[:, 0, 0]) * (u[:, 2, 1] - u[:, 0, 1]) - (u[:, 2, 0] - u[:, 0, 0]) * (u[:, 1, 1] - u[:, 0, 1]))
    tl = lab[tp]
    major = np.sign(np.bincount(tl, weights=sa, minlength=lab.max() + 1))
    # zero-area UV triangles (needle slivers) cover nothing: they are not folds
    tiny = np.abs(sa) <= 1e-12 + 1e-6 * (np.median(np.abs(sa)) if len(sa) else 0.0)
    flip = (np.sign(sa) == -major[tl]) & ~tiny & (major[tl] != 0)
    bad_isl = set(np.unique(tl[flip]).tolist())
    # 2) around one UV point the corners of an island add up to more than a full turn: the faces there lie on top
    #    of each other (a fan wrapped twice) even though none is flipped
    def corner(p0, p1, p2):
        a, b = p1 - p0, p2 - p0
        cr = np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
        return np.arctan2(cr, np.einsum("ij,ij->i", a, b))
    ang = np.stack([corner(u[:, 0], u[:, 1], u[:, 2]), corner(u[:, 1], u[:, 2], u[:, 0]),
                    corner(u[:, 2], u[:, 0], u[:, 1])], axis=1)
    q = np.round(u * 1e6).astype(np.int64)  # (t, 3, 2) corner points
    keys = np.stack([np.repeat(tl, 3), q[:, :, 0].ravel(), q[:, :, 1].ravel()], axis=1)
    _uk, inv = np.unique(keys, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    turn = np.bincount(inv, weights=ang.ravel())
    over = turn > 2 * np.pi + 1e-3
    if over.any():
        bad_isl |= set(np.unique(np.repeat(tl, 3)[over[inv]]).tolist())
    # 3) island borders that cross themselves
    interior = np.zeros(len(me.edges), dtype=bool)
    interior[ids[same]] = True
    nxt = np.arange(len(lv)) + 1
    nxt[start + total - 1] = start
    lf = U.loop_face(start, total)
    border = ~interior[le]
    bl = np.nonzero(border)[0]
    if len(bl):
        p, q = uv[bl], uv[nxt[bl]]
        il = lab[lf[bl]]
        order = np.argsort(il, kind="stable")
        il_s = il[order]
        cuts = np.searchsorted(il_s, np.arange(lab.max() + 2))
        for i in range(lab.max() + 1):
            seg = order[cuts[i]:cuts[i + 1]]
            if len(seg) < 4 or i in bad_isl:
                continue
            if _segments_cross(p[seg], q[seg]):
                bad_isl.add(i)
    if bad_isl:
        out[np.isin(lab, np.array(sorted(bad_isl)))] = True
    return out


def _segments_cross(p, q, chunk=300):
    """True when any two of the segments p[i]-q[i] cross (segments that share an end point do not count)."""
    n = len(p)
    eps = 1e-9

    def orient(a, b, c):
        return (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0])
    for s0 in range(0, n, chunk):
        A, B = p[s0:s0 + chunk, None, :], q[s0:s0 + chunk, None, :]
        C, D = p[None, :, :], q[None, :, :]
        # quick reject by bounding boxes
        ov = (np.minimum(A[..., 0], B[..., 0]) <= np.maximum(C[..., 0], D[..., 0])) &              (np.minimum(C[..., 0], D[..., 0]) <= np.maximum(A[..., 0], B[..., 0])) &              (np.minimum(A[..., 1], B[..., 1]) <= np.maximum(C[..., 1], D[..., 1])) &              (np.minimum(C[..., 1], D[..., 1]) <= np.maximum(A[..., 1], B[..., 1]))
        if not ov.any():
            continue
        share = (np.abs(A - C).max(-1) < 1e-7) | (np.abs(A - D).max(-1) < 1e-7) |                 (np.abs(B - C).max(-1) < 1e-7) | (np.abs(B - D).max(-1) < 1e-7)
        m = ov & ~share
        idx = np.nonzero(m)
        if len(idx[0]) == 0:
            continue
        a, b = p[s0 + idx[0]], q[s0 + idx[0]]
        c, d = p[idx[1]], q[idx[1]]
        d1, d2 = orient(a, b, c), orient(a, b, d)
        d3, d4 = orient(c, d, a), orient(c, d, b)
        cross = (((d1 > eps) & (d2 < -eps)) | ((d1 < -eps) & (d2 > eps))) &                 (((d3 > eps) & (d4 < -eps)) | ((d3 < -eps) & (d4 > eps)))
        if cross.any():
            return True
    return False


# ---------------------------------------------------------------- seams

def _mark_seams(obj, angle, clear=True, min_area=0.002):
    """Seams around charts: the mesh is cut into smooth patches at creases sharper than `angle` (and at marked-sharp
    and material borders), tiny patches join a neighbour, and the seams are the patch borders. Patch borders are
    always closed lines, so every chart is a real island (a lone crease never leaves a dead-end seam)."""
    from .parts import _merge_small, _region_labels
    me = obj.data
    start, total, lv, le = U.polys(me)
    ids, ang, _ = U.dihedral(me, start, total, le)
    cut = np.zeros(len(me.edges), dtype=bool)
    cut[ids[ang > angle]] = True
    cut |= U.edge_flags(me, "use_edge_sharp") & False  # sharp-by-angle marks (35 deg) would cut far too much
    if len(me.materials) > 1:
        ids2, fa, fb, _c = U.edge_faces(me, start, total, le)
        m = U.face_materials(me)
        cut[ids2[m[fa] != m[fb]]] = True
    lab = _merge_small(me, _region_labels(me, cut), min_area)
    area = U.face_areas(me)
    biggest = float(np.bincount(lab, weights=area).max() / (area.sum() or 1.0)) if len(lab) else 0.0
    ids2, fa, fb, _c = U.edge_faces(me, start, total, le)
    seam = np.zeros(len(me.edges), dtype=bool) if clear else U.edge_flags(me, "use_seam")
    seam[ids2[lab[fa] != lab[fb]]] = True
    if len(me.materials) > 1:
        m = U.face_materials(me)
        seam[ids2[m[fa] != m[fb]]] = True
    me.edges.foreach_set("use_seam", seam)
    me.update()
    return int(seam.sum()), biggest


def _more_seams(obj, bad_faces, angle):
    """Adds seams inside the faces that unwrapped badly, on edges sharper than `angle`. Returns how many."""
    me = obj.data
    start, total, lv, le = U.polys(me)
    ids, ang, _ = U.dihedral(me, start, total, le)
    _i, fa, fb, _c = U.edge_faces(me, start, total, le)
    pick = (ang > angle) & (bad_faces[fa] | bad_faces[fb])
    seam = U.edge_flags(me, "use_seam")
    before = int(seam.sum())
    seam[ids[pick]] = True
    me.edges.foreach_set("use_seam", seam)
    me.update()
    return int(seam.sum()) - before


def _bad_islands(me, stretch=4.0, bad_share=0.08):
    """Faces of UV islands that unwrapped badly (closed shells or tubes without enough seams come out flipped,
    squashed or stretched). A face is bad when its UV / 3D area ratio is more than `stretch` times off the island's
    typical ratio, or flipped; an island is bad when more than bad_share of its area is bad."""
    uv = _uvs(me)
    nf = len(me.polygons)
    if uv is None or nf == 0:
        return np.zeros(nf, dtype=bool)
    lo = U.tri_loops(me)
    _t, tp = U.tris(me)
    u = uv[lo]
    sa = 0.5 * ((u[:, 1, 0] - u[:, 0, 0]) * (u[:, 2, 1] - u[:, 0, 1]) - (u[:, 2, 0] - u[:, 0, 0]) * (u[:, 1, 1] - u[:, 0, 1]))
    suv = np.bincount(tp, weights=sa, minlength=nf)
    a3 = U.face_areas(me)
    out = np.zeros(nf, dtype=bool)
    for isl in islands(me):
        s = suv[isl]
        a = a3[isl]
        major = 1.0 if s.sum() >= 0 else -1.0
        r = (s * major) / np.maximum(a, 1e-20)
        good_r = r[r > 0]
        if len(good_r) == 0:
            out[isl] = True
            continue
        med = np.median(good_r)
        bad = (r <= 0) | (r > med * stretch) | (r < med / stretch)
        if a[bad].sum() > bad_share * a.sum():
            out[isl] = True
    return out


def _select_faces(me, mask):
    me.polygons.foreach_set("select", mask)
    # vertices / edges of selected faces too (edit mode reads them)
    start, total, lv, le = U.polys(me)
    vs = np.zeros(len(me.vertices), dtype=bool)
    es = np.zeros(len(me.edges), dtype=bool)
    lm = mask[U.loop_face(start, total)]
    vs[lv[lm]] = True
    es[le[lm]] = True
    me.vertices.foreach_set("select", vs)
    me.edges.foreach_set("select", es)
    me.update()


def uv_unwrap(objs, texture_size=2048, method="auto", seam_angle=None, margin_px=None, shared=True,
              uv_name="UVMap", progress=None):
    """Unwraps one or more objects into ONE shared UV atlas (shared=True: one texture set for the whole asset;
    False: each object fills its own 0..1 square).

    method: 'auto' (xatlas for triangle meshes; else seams for hard-surface, Smart UV Project for organic) |
    'seams' | 'smart' |
    'xatlas'. auto uses xatlas (shipped with the extension) for triangle meshes (generated, low poly): fewer, bigger
    islands. Returns a report (islands, texel density, overlap)."""
    from . import shape as SH
    p = U.Progress(progress)
    t0 = time.monotonic()
    objs = [U.require_mesh(o) for o in U.as_objects(objs)]
    if not objs:
        raise ValueError("no mesh objects to unwrap")
    size = texture_px(texture_size)
    mpx = margin_px if margin_px is not None else MARGIN_PX.get(size, max(4, size // 128))
    margin = mpx / size
    rep = {"texture": size, "margin_px": mpx, "objects": []}
    for o in objs:
        me = o.data
        if me.uv_layers.get(uv_name) is None:
            if len(me.uv_layers) == 0:
                me.uv_layers.new(name=uv_name)
            else:
                me.uv_layers.active.name = uv_name if me.uv_layers.get(uv_name) is None else me.uv_layers.active.name
        lay = me.uv_layers.get(uv_name) or me.uv_layers.active
        me.uv_layers.active = lay
        try:
            lay.active_render = True
        except AttributeError:
            pass
    groups = [objs] if shared else [[o] for o in objs]
    xatlas_done = set()
    from . import xa
    tri_share = min((_tri_share(o.data) for o in objs), default=0.0)
    use_xa = method == "xatlas" or (method == "auto" and xa.available() and tri_share >= 0.9)
    if method == "xatlas" and not xa.available():
        raise ValueError("xatlas is not available here; use 'auto', 'seams' or 'smart'")
    if use_xa:
        # triangle meshes (generated, low poly): xatlas charts and packs them all in one go
        p(0.1, "xatlas")
        try:
            for g in groups:
                info = _xatlas_group(g, size, mpx)
                for o in g:
                    xatlas_done.add(o.name)
                    rep["objects"].append({"name": o.name, "method": "xatlas", "charts": info["charts"].get(o.name)})
                rep["xatlas"] = {k: info[k] for k in ("utilization", "seconds") if k in info}
        except Exception as e:  # noqa: BLE001 - xatlas missing / failed: Blender's own unwrap below
            if method == "xatlas":
                raise
            rep["note"] = f"xatlas failed ({str(e)[:120]}); used Blender's unwrap"
            xatlas_done.clear()
            rep["objects"] = []
    plan = {}
    for i, o in enumerate(objs):
        if o.name in xatlas_done:
            plan[o.name] = "xatlas"
            continue
        m = method
        if m == "auto":
            m = "seams" if SH.classify(o)["kind"] == "hard_surface" else "smart"
        why = None
        if m == "seams":
            n, biggest = _mark_seams(o, float(seam_angle or 60.0))
            if method == "auto" and biggest > 0.35:
                # its creases don't close into clean charts (typical for generated / decimated meshes)
                m, why = "smart", "creases don't close into charts"
            else:
                rep["objects"].append({"name": o.name, "method": "seams from sharp edges", "seams": n})
        plan[o.name] = m
        if m == "smart":
            row = {"name": o.name, "method": "smart project"}
            if why:
                row["why"] = why
            rep["objects"].append(row)
    p(0.1, "unwrapping")
    if not xatlas_done:
        for g in groups:
            _unwrap_group(g, plan, margin, seam_angle, p)
    p(0.9, "checking")
    if "margin" in _LAST:
        rep["margin_px"] = max(1, int(round(_LAST.pop("margin") * size)))
    rep["report"] = uv_report(objs, size, uv_name)
    rep["seconds"] = round(time.monotonic() - t0, 2)
    return rep


def _edit(objs):
    """Enter edit mode on all objs together (multi-object editing)."""
    return U.override(objs[0], objs)


def _unwrap_group(objs, plan, margin, seam_angle, p):
    with _edit(objs):
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            bpy.ops.mesh.select_mode(type='FACE')
            # 1) per object: unwrap by seams, or smart project
            bpy.ops.object.mode_set(mode='OBJECT')
            for o in objs:
                if plan[o.name] == "xatlas":
                    _select_faces(o.data, np.zeros(len(o.data.polygons), dtype=bool))
                else:
                    _select_faces(o.data, np.ones(len(o.data.polygons), dtype=bool))
            seam_objs = [o for o in objs if plan[o.name] == "seams"]
            smart_objs = [o for o in objs if plan[o.name] == "smart"]
            # seams: unwrap only those objects' faces
            if seam_objs:
                for o in smart_objs:
                    _select_faces(o.data, np.zeros(len(o.data.polygons), dtype=bool))
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.uv.unwrap(method='ANGLE_BASED', fill_holes=True, correct_aspect=True, margin=margin)
                bpy.ops.object.mode_set(mode='OBJECT')
                # islands that came out squashed or folded (closed shells, tubes, bevel strips): cut them at gentler
                # creases and unwrap them again; what still fails is projected (Smart UV Project)
                for gentler in (40.0, 25.0, None):
                    bad_any = False
                    for o in objs:
                        bad = np.zeros(len(o.data.polygons), dtype=bool)
                        if o in seam_objs:
                            bad = _bad_islands(o.data) | folded_faces(o.data)
                            if gentler is not None and bad.any():
                                _more_seams(o, bad, gentler)
                        _select_faces(o.data, bad)
                        bad_any |= bool(bad.any())
                    if not bad_any:
                        break
                    bpy.ops.object.mode_set(mode='EDIT')
                    if gentler is not None:
                        bpy.ops.uv.unwrap(method='ANGLE_BASED', fill_holes=True, correct_aspect=True, margin=margin)
                    else:
                        bpy.ops.uv.smart_project(angle_limit=math.radians(50.0), island_margin=margin,
                                                 area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
                    bpy.ops.object.mode_set(mode='OBJECT')
            if smart_objs:
                for o in objs:
                    _select_faces(o.data, np.full(len(o.data.polygons), o in smart_objs, dtype=bool))
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.uv.smart_project(angle_limit=math.radians(66.0), island_margin=margin, area_weight=0.0,
                                         correct_aspect=True, scale_to_bounds=False)
                bpy.ops.object.mode_set(mode='OBJECT')
            p(0.6, "packing")
            # 2) same texel density everywhere, then pack all islands of the group into one square
            for o in objs:
                _select_faces(o.data, np.ones(len(o.data.polygons), dtype=bool))
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.uv.select_all(action='SELECT')
            bpy.ops.uv.average_islands_scale()
            # 3) islands that overlap themselves (a tube with no seam along it, a surface that curls under itself):
            #    project them again with Smart UV Project at a smaller angle (cuts them by facing direction). A quick
            #    box pack keeps islands apart, so whatever overlaps here overlaps itself.
            for _round in range(4):
                _pack(margin, fast=True)
                bpy.ops.object.mode_set(mode='OBJECT')
                bad = overlap_faces(objs, res=2048)
                if not bad or _round == 3:
                    break
                for o in objs:
                    m = bad.get(o.name)
                    sel = np.zeros(len(o.data.polygons), dtype=bool)
                    if m is not None:
                        for isl in islands(o.data):
                            if m[isl].any():
                                sel[isl] = True
                    _select_faces(o.data, sel)
                bpy.ops.object.mode_set(mode='EDIT')
                # last round: 1 degree = every face its own island, which cannot overlap itself
                bpy.ops.uv.smart_project(angle_limit=math.radians((50.0, 30.0, 1.0)[_round]), island_margin=margin,
                                         area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
                bpy.ops.object.mode_set(mode='OBJECT')
                for o in objs:
                    _select_faces(o.data, np.ones(len(o.data.polygons), dtype=bool))
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.uv.select_all(action='SELECT')
                bpy.ops.uv.average_islands_scale()
            # 4) the real, tight pack; if it lets islands touch (seen in 4.2), keep the box pack instead. Hundreds
            #    of small islands would be mostly margin: the gap shrinks with the island count (never under 1/512)
            n_isl = sum(len(islands(o.data)) for o in objs)
            margin = max(margin * min(1.0, math.sqrt(200.0 / max(n_isl, 1))), 1.0 / 512)
            _LAST["margin"] = margin
            for o in objs:
                _select_faces(o.data, np.ones(len(o.data.polygons), dtype=bool))
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.uv.select_all(action='SELECT')
            _pack(margin)
            bpy.ops.object.mode_set(mode='OBJECT')
            if overlap_faces(objs, res=2048):
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.uv.select_all(action='SELECT')
                _pack(margin, fast=True)
        finally:
            if bpy.context.view_layer.objects.active and bpy.context.view_layer.objects.active.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')


def _pack(margin, fast=False):
    kw = dict(rotate=True, scale=True, merge_overlap=False, margin=margin)
    try:
        bpy.ops.uv.pack_islands(udim_source='CLOSEST_UDIM', margin_method='FRACTION',
                                shape_method='AABB' if fast else 'CONCAVE', rotate_method='ANY', **kw)
    except TypeError:
        bpy.ops.uv.pack_islands(**kw)


def _tri_share(me):
    _s, total, _lv, _le = U.polys(me)
    return float((total == 3).mean()) if len(total) else 0.0


def _xatlas_group(objs, size, margin_px):
    """xatlas charts + packing for these objects into one atlas (world-space sizes, so the texel density is the same
    on every part). Faces that are not triangles take their UVs from their first triangle. If a chart comes out
    folded (rare), those charts are projected again with Blender and everything is packed again by xatlas, keeping
    the islands."""
    from . import xa
    meshes, tri_info = [], []
    for o in objs:
        t, _tp = U.tris(o.data)
        meshes.append((U.world_verts(o), t))
        tri_info.append(U.tri_loops(o.data))
    pad = max(1, int(margin_px))
    parts, info = xa.run(meshes, resolution=size, padding=pad, chart=XATLAS_CHART)
    charts = {}
    for o, lo, (_vm, ix, uvs, n_charts) in zip(objs, tri_info, parts):
        charts[o.name] = n_charts
        _set_loop_uvs(o.data, lo, ix, uvs)
    info["charts"] = charts
    info["repaired"] = _repair_and_repack(objs, size, pad)
    return info


XATLAS_CHART = {"max_cost": 3.0, "fix_winding": True}  # a bit bigger charts than xatlas' default (fewer seams)


def _set_loop_uvs(me, lo, ix, uvs):
    uv = np.zeros((len(me.loops), 2), dtype=np.float32)
    uv[lo[::-1].ravel()] = uvs[ix[::-1].ravel()]  # later triangles first: each loop keeps its first triangle's UV
    me.uv_layers.active.data.foreach_set("uv", uv.ravel())
    me.update()


def _split_by_uv(obj):
    """World-space vertices split where the UVs differ, the triangles on them and their UVs (for a pack-only run)."""
    me = obj.data
    uv = _uvs(me)
    lo = U.tri_loops(me)
    start, total, lv, _le = U.polys(me)
    q = np.round(uv * 1e6).astype(np.int64)
    key = np.stack([lv, q[:, 0], q[:, 1]], axis=1)
    _u, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    co = U.world_verts(obj)
    return co[lv[first]], inv[lo], uv[first], lo


def _repair_and_repack(objs, size, pad):
    """Charts that fold over themselves get Smart UV Project (66, 30, 15, 8, then 4 degrees: smaller angles cut more)
    until nothing folds; then xatlas packs all islands again as they are (that also clears any overlap between
    charts). Returns how many faces were redone (0: xatlas' own result was clean)."""
    from . import xa
    ov = uv_overlap(objs, res=size)
    folded = {o.name: folded_faces(o.data) for o in objs}
    if not any(m.any() for m in folded.values()) and (ov is None or ov["overlap_px"] <= 16):
        return 0  # (a few pixels where thin slivers touch: nothing a texture would show)
    redo = 0
    for angle in (66.0, 30.0, 15.0, 8.0, 4.0):
        if not any(m.any() for m in folded.values()):
            break
        for o in objs:
            me = o.data
            sel = np.zeros(len(me.polygons), dtype=bool)
            m = folded[o.name]
            if m.any():
                for isl in islands(me):
                    if m[isl].any():
                        sel[isl] = True
            redo += int(sel.sum())
            _select_faces(me, sel)
        with _edit(objs):
            bpy.ops.object.mode_set(mode='EDIT')
            try:
                bpy.ops.uv.smart_project(angle_limit=math.radians(angle), island_margin=0.0, area_weight=0.0,
                                         correct_aspect=True, scale_to_bounds=False)
            finally:
                bpy.ops.object.mode_set(mode='OBJECT')
        folded = {o.name: folded_faces(o.data) for o in objs}
    redo = max(redo, 1)
    if redo:
        # xatlas packs kept islands at their UV size: give every island the same pixels per meter first
        for o in objs:
            _select_faces(o.data, np.ones(len(o.data.polygons), dtype=bool))
        with _edit(objs):
            bpy.ops.object.mode_set(mode='EDIT')
            try:
                bpy.ops.uv.select_all(action='SELECT')
                bpy.ops.uv.average_islands_scale()
            finally:
                bpy.ops.object.mode_set(mode='OBJECT')
        split = [_split_by_uv(o) for o in objs]
        parts, _info = xa.run([(v, f, u) for v, f, u, _lo in split], resolution=size, padding=pad)
        for o, (_v, _f, _u, lo), (_vm, ix, uvs, _n) in zip(objs, split, parts):
            _set_loop_uvs(o.data, lo, ix, uvs)
    return redo
