# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesh checks and measurements behind verify_mesh and measure (also usable in scripts).

    rep = n.verify([body, lid])       # {"pass": bool, "errors": [...], "warnings": [...], "objects": {...}}
    n.measure(body)                   # size, center, bounds in meters
"""

import math

import bpy
from mathutils import Vector

from . import core
from .core import to_list

__all__ = ["verify", "measure", "distance", "compare"]

SKIP_INTERSECT_FACES = 60000


def _np():
    import numpy as np
    return np


class _Mesh:
    """An object's evaluated mesh as numpy arrays (world space)."""

    def __init__(self, obj, evaluated=True, depsgraph=None):
        np = _np()
        dg = depsgraph or bpy.context.evaluated_depsgraph_get()
        self.obj = obj
        src = obj.evaluated_get(dg) if evaluated else obj
        me = src.to_mesh()
        try:
            nv, ne, npoly, nl = len(me.vertices), len(me.edges), len(me.polygons), len(me.loops)
            co = np.empty(nv * 3, np.float32)
            me.vertices.foreach_get("co", co)
            self.local = co.reshape(-1, 3).astype(np.float64)
            mw = np.array(obj.matrix_world, dtype=np.float64)
            self.co = self.local @ mw[:3, :3].T + mw[:3, 3]
            ev = np.empty(ne * 2, np.int64)
            me.edges.foreach_get("vertices", ev)
            self.edges = ev.reshape(-1, 2)
            self.loop_vert = np.empty(nl, np.int64)
            me.loops.foreach_get("vertex_index", self.loop_vert)
            self.loop_edge = np.empty(nl, np.int64)
            me.loops.foreach_get("edge_index", self.loop_edge)
            self.loop_start = np.empty(npoly, np.int64)
            me.polygons.foreach_get("loop_start", self.loop_start)
            self.loop_total = np.empty(npoly, np.int64)
            me.polygons.foreach_get("loop_total", self.loop_total)
            me.calc_loop_triangles()
            nt = len(me.loop_triangles)
            tv = np.empty(nt * 3, np.int64)
            me.loop_triangles.foreach_get("vertices", tv)
            self.tris = tv.reshape(-1, 3)
            tl = np.empty(nt * 3, np.int64)
            me.loop_triangles.foreach_get("loops", tl)
            self.tri_loops = tl.reshape(-1, 3)
            tp = np.empty(nt, np.int64)
            me.loop_triangles.foreach_get("polygon_index", tp)
            self.tri_poly = tp
            self.uv = None
            self.uv_name = None
            layer = me.uv_layers.active
            if layer is not None and nl:
                uv = np.empty(nl * 2, np.float32)
                layer.data.foreach_get("uv", uv)
                self.uv = uv.reshape(-1, 2).astype(np.float64)
                self.uv_name = layer.name
            self.uv_layers = len(me.uv_layers)
            self.materials = [m.name if m else None for m in me.materials]
        finally:
            src.to_mesh_clear()

    @property
    def nv(self):
        return len(self.co)


def _components(n, edges):
    """Connected component label per vertex (numpy union-find with pointer jumping)."""
    np = _np()
    parent = np.arange(n)
    if len(edges) == 0 or n == 0:
        return parent
    a, b = edges[:, 0], edges[:, 1]
    for _ in range(200):
        pa, pb = parent[a], parent[b]
        m = np.minimum(pa, pb)
        if not ((pa != m) | (pb != m)).any():
            break
        np.minimum.at(parent, pa, m)
        np.minimum.at(parent, pb, m)
        while True:
            pp = parent[parent]
            if (pp == parent).all():
                break
            parent = pp
    return parent


def _diag(co):
    np = _np()
    if not len(co):
        return 1.0
    return float(np.linalg.norm(co.max(axis=0) - co.min(axis=0))) or 1.0


def _raster_hits(tri_px, size):
    """(pixel, triangle) pairs for pixel centers inside UV triangles given in pixel units."""
    np = _np()
    x, y = tri_px[:, :, 0], tri_px[:, :, 1]
    x0 = np.floor(x.min(axis=1) - 0.5).astype(np.int64)
    y0 = np.floor(y.min(axis=1) - 0.5).astype(np.int64)
    x1 = np.ceil(x.max(axis=1) - 0.5).astype(np.int64)
    y1 = np.ceil(y.max(axis=1) - 0.5).astype(np.int64)
    span = np.maximum(x1 - x0, y1 - y0) + 1
    out_p, out_t = [], []

    def test(px, py, t_idx):
        ax, ay = x[t_idx, 0][:, None], y[t_idx, 0][:, None]
        bx, by = x[t_idx, 1][:, None], y[t_idx, 1][:, None]
        cx, cy = x[t_idx, 2][:, None], y[t_idx, 2][:, None]
        area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        s = np.where(area >= 0, 1.0, -1.0)
        w0 = ((bx - px) * (cy - py) - (by - py) * (cx - px)) * s
        w1 = ((cx - px) * (ay - py) - (cy - py) * (ax - px)) * s
        w2 = ((ax - px) * (by - py) - (ay - py) * (bx - px)) * s
        return (w0 > 0) & (w1 > 0) & (w2 > 0) & (np.abs(area) > 1e-12)

    small = np.nonzero(span <= 6)[0]
    if len(small):
        S = 6
        offs = np.arange(S)
        gx = x0[small][:, None, None] + offs[None, None, :]
        gy = y0[small][:, None, None] + offs[None, :, None]
        gx = np.broadcast_to(gx, (len(small), S, S)).reshape(len(small), -1)
        gy = np.broadcast_to(gy, (len(small), S, S)).reshape(len(small), -1)
        inside = test(gx + 0.5, gy + 0.5, small)
        inside &= (gx >= 0) & (gx < size) & (gy >= 0) & (gy < size)
        ti, ci = np.nonzero(inside)
        out_p.append(gy[ti, ci] * size + gx[ti, ci])
        out_t.append(small[ti])
    for t in np.nonzero(span > 6)[0][:20000]:
        xs = np.arange(max(0, x0[t]), min(size, x1[t] + 1))
        ys = np.arange(max(0, y0[t]), min(size, y1[t] + 1))
        if not len(xs) or not len(ys):
            continue
        gx, gy = np.meshgrid(xs, ys)
        gx, gy = gx.ravel()[None, :], gy.ravel()[None, :]
        inside = test(gx + 0.5, gy + 0.5, np.array([t]))[0]
        out_p.append((gy[0] * size + gx[0])[inside])
        out_t.append(np.full(int(inside.sum()), t))
    if not out_p:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    return np.concatenate(out_p), np.concatenate(out_t)


def _uv_report(m, tri_area3):
    np = _np()
    if m.uv is None or not len(m.tri_loops):
        return {"uv": False}
    uvt = m.uv[m.tri_loops]  # (T, 3, 2)
    e1 = uvt[:, 1] - uvt[:, 0]
    e2 = uvt[:, 2] - uvt[:, 0]
    signed = 0.5 * (e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    au = np.abs(signed)
    rep = {"uv": True, "uv_layer": m.uv_name}
    total_u, total_3 = au.sum(), tri_area3.sum()
    if total_u <= 1e-12:
        rep.update({"uv_empty": True})
        return rep
    keep = tri_area3 > total_3 * 1e-9
    r = (au[keep] / total_u) / (tri_area3[keep] / total_3)
    r = np.clip(r, 1e-6, 1e6)
    w = tri_area3[keep] / total_3
    rep["uv_stretch"] = round(float(np.exp((np.abs(np.log(r)) * w).sum() / max(w.sum(), 1e-12)) - 1.0), 3)
    rep["uv_density_spread"] = round(float(np.percentile(r, 90) / max(np.percentile(r, 10), 1e-9)), 2)
    major = 1.0 if (signed > 0).sum() >= (signed < 0).sum() else -1.0
    rep["uv_flipped_tris"] = int(((signed * major) < -1e-14).sum())
    rep["uv_outside_0_1"] = int(((m.uv < -1e-4) | (m.uv > 1 + 1e-4)).any(axis=1).sum())
    size = 256
    lo = m.uv.min(axis=0)
    hi = m.uv.max(axis=0)
    span = max(float((hi - lo).max()), 1e-9)
    fit = 1.0 if (lo >= -1e-4).all() and (hi <= 1 + 1e-4).all() else 1.0 / span
    base = np.zeros(2) if fit == 1.0 else lo
    px = (uvt - base) * fit * size
    pix, tri = _raster_hits(px, size)
    if len(pix):
        pair = np.unique(pix * (len(m.tris) + 1) + tri)
        pix_u = pair // (len(m.tris) + 1)
        counts = np.bincount(pix_u, minlength=size * size)
        covered = int((counts > 0).sum())
        overlap = int((counts > 1).sum())
        rep["uv_coverage"] = round(covered / float(size * size), 3)
        rep["uv_overlap"] = round(overlap / float(max(covered, 1)), 4)
    return rep


def mesh_stats(obj, evaluated=True, depsgraph=None, symmetry="X", uv=True, intersections=True):
    """Topology numbers of one object (see verify for the meaning). Returns a dict."""
    np = _np()
    obj = core.get(obj)
    m = _Mesh(obj, evaluated, depsgraph)
    nv, ne, nf = m.nv, len(m.edges), len(m.loop_start)
    rep = {"verts": nv, "edges": ne, "faces": nf}
    sizes = m.loop_total
    rep["tris"] = int((sizes == 3).sum())
    rep["quads"] = int((sizes == 4).sum())
    rep["ngons"] = int((sizes > 4).sum())
    rep["triangles_total"] = int(len(m.tris))
    diag = _diag(m.co)
    rep["size"] = [round(float(v), 4) for v in (m.co.max(axis=0) - m.co.min(axis=0))] if nv else [0, 0, 0]
    # edges
    efc = np.bincount(m.loop_edge, minlength=ne) if ne else np.zeros(0, np.int64)
    rep["boundary_edges"] = int((efc == 1).sum())
    if rep["boundary_edges"]:      # their midpoints: verify() tells seams between split parts from real holes
        b = m.edges[efc == 1]
        rep["_seam_data"] = (m.co[b[:, 0]] + m.co[b[:, 1]]) * 0.5
    rep["non_manifold_edges"] = int((efc > 2).sum())
    rep["loose_edges"] = int((efc == 0).sum())
    used = np.bincount(m.edges.ravel(), minlength=nv) if ne else np.zeros(nv, np.int64)
    rep["loose_verts"] = int((used == 0).sum())
    # degenerate geometry
    if ne:
        elen = np.linalg.norm(m.co[m.edges[:, 0]] - m.co[m.edges[:, 1]], axis=1)
        rep["zero_length_edges"] = int((elen < diag * 1e-7).sum())
    else:
        rep["zero_length_edges"] = 0
    t = m.tris
    if len(t):
        v0, v1, v2 = m.co[t[:, 0]], m.co[t[:, 1]], m.co[t[:, 2]]
        cr = np.cross(v1 - v0, v2 - v0)
        tri_area = 0.5 * np.linalg.norm(cr, axis=1)
        poly_area = np.bincount(m.tri_poly, weights=tri_area, minlength=nf)
    else:
        tri_area = np.zeros(0)
        poly_area = np.zeros(nf)
        v0 = v1 = v2 = cr = np.zeros((0, 3))
    rep["zero_area_faces"] = int((poly_area < (diag * 1e-6) ** 2).sum()) if nf else 0
    rep["area"] = round(float(tri_area.sum()), 6)
    # ngons that are not flat
    nonplanar = 0
    big = np.nonzero(sizes > 4)[0]
    for p in big[:5000]:
        s, c = m.loop_start[p], m.loop_total[p]
        pts = m.co[m.loop_vert[s:s + c]]
        cen = pts.mean(axis=0)
        u, sv, vt = np.linalg.svd(pts - cen)
        dev = np.abs((pts - cen) @ vt[2]).max()
        if dev > max(1e-6, 0.002 * math.sqrt(max(poly_area[p], 1e-18))):
            nonplanar += 1
    rep["ngons_not_flat"] = nonplanar
    # normals: consistent winding and inside-out shells
    nl = len(m.loop_vert)
    if nl:
        poly_of_loop = np.repeat(np.arange(nf), sizes)
        local = np.arange(nl) - m.loop_start[poly_of_loop]
        nxt = m.loop_start[poly_of_loop] + (local + 1) % sizes[poly_of_loop]
        flag = m.loop_vert < m.loop_vert[nxt]
        order = np.argsort(m.loop_edge, kind="stable")
        starts = np.concatenate([[0], np.cumsum(efc)[:-1]])
        two = np.nonzero(efc == 2)[0]
        fs = flag[order]
        rep["flipped_faces"] = int((fs[starts[two]] == fs[starts[two] + 1]).sum())
    else:
        rep["flipped_faces"] = 0
    labels = _components(nv, m.edges)
    roots, inv = np.unique(labels, return_inverse=True)
    inv = inv.ravel()
    if nv:  # points on top of each other inside one piece (touching separate pieces are fine)
        q = np.round(m.local / max(diag * 1e-6, 1e-9)).astype(np.int64)
        rep["duplicate_verts"] = int(nv - len(np.unique(np.column_stack([inv, q]), axis=0)))
    else:
        rep["duplicate_verts"] = 0
    rep["shells"] = int(len(roots)) - rep["loose_verts"]
    inverted = 0
    open_shells = 0
    if len(t):
        vol = np.einsum("ij,ij->i", v0, np.cross(v1, v2)) / 6.0
        tri_shell = inv[t[:, 0]]
        shell_vol = np.bincount(tri_shell, weights=vol, minlength=len(roots))
        shell_area = np.bincount(tri_shell, weights=tri_area, minlength=len(roots))
        bad_edges = np.nonzero(efc != 2)[0]
        open_ids = np.unique(inv[m.edges[bad_edges, 0]]) if len(bad_edges) else np.zeros(0, np.int64)
        closed = np.ones(len(roots), bool)
        closed[open_ids] = False
        has_faces = shell_area > 0
        open_shells = int((~closed & has_faces).sum())
        tiny = shell_area.max() * 1e-9 if len(shell_area) else 0
        inverted = int(((shell_vol < 0) & closed & (shell_area > tiny)).sum())
        rep["volume"] = round(float(shell_vol[closed].sum()), 9)
    rep["inverted_shells"] = inverted
    rep["open_shells"] = open_shells
    # poles (vertices inside the surface with other than 4 edges)
    if ne:
        bverts = np.zeros(nv, bool)
        bverts[m.edges[efc == 1].ravel()] = True
        inner = (~bverts) & (used > 0)
        rep["poles"] = {"3": int(((used == 3) & inner).sum()), "5": int(((used == 5) & inner).sum()),
                        "6+": int(((used >= 6) & inner).sum())}
    # density
    if nf and rep["area"] > 0:
        rep["faces_per_m2"] = round(nf / rep["area"], 1)
        pa = poly_area[poly_area > 0]
        if len(pa) > 4:
            rep["face_size_spread"] = round(float(np.percentile(pa, 95) / max(np.percentile(pa, 5), 1e-18)), 1)
    # symmetry across the object's own X = 0 (and its middle)
    if symmetry and nv:
        rep["symmetry"] = _symmetry(m.local, str(symmetry).upper(), diag)
    if uv:
        rep.update(_uv_report(m, tri_area))
    else:
        rep["uv"] = m.uv is not None
    if intersections:
        rep["self_intersections"] = _self_intersections(m, inv) if len(t) <= SKIP_INTERSECT_FACES else "skipped"
    # object transform
    sc = obj.matrix_world.to_scale()
    rep["scale"] = [round(float(c), 4) for c in obj.scale]
    rep["scale_applied"] = all(abs(c - 1.0) < 1e-4 for c in obj.scale)
    rep["mirrored"] = obj.matrix_world.determinant() < 0
    rep["modifiers"] = [md.type.lower() for md in obj.modifiers if md.show_viewport] if obj.type == "MESH" else []
    rep["materials"] = [x for x in m.materials if x]
    rep["_shell_data"] = (m, inv, len(roots), tri_area)
    return rep


def _symmetry(local, axis, diag):
    np = _np()
    from mathutils.kdtree import KDTree
    if axis not in "XYZ" or axis == "":
        return None
    i = "XYZ".index(axis[0])
    pts = local
    if len(pts) > 40000:
        pts = pts[np.linspace(0, len(pts) - 1, 40000).astype(int)]
    tree = KDTree(len(pts))
    for k, p in enumerate(pts):
        tree.insert(p, k)
    tree.balance()
    sample = pts[np.linspace(0, len(pts) - 1, min(len(pts), 3000)).astype(int)]
    tol = diag * 2e-3
    out = {}
    mid = (local[:, i].max() + local[:, i].min()) / 2.0
    for label, plane in (("origin", 0.0), ("middle", mid)):
        hits = 0
        for p in sample:
            q = p.copy()
            q[i] = 2 * plane - q[i]
            _, _, dist = tree.find(q)
            if dist is not None and dist <= tol:
                hits += 1
        out[label] = round(hits / float(len(sample)), 3)
    return {"axis": axis, "score": max(out.values()), "about": max(out, key=out.get)}


def _self_intersections(m, shell_of_vert):
    """Triangles of one piece that pass through each other (touching along an edge does not count)."""
    np = _np()
    from mathutils.bvhtree import BVHTree
    if not len(m.tris):
        return 0
    co = m.co
    tree = BVHTree.FromPolygons([tuple(c) for c in co], m.tris.tolist(), all_triangles=True)
    pairs = tree.overlap(tree)
    if not pairs:
        return 0
    p = np.array(pairs[:40000], dtype=np.int64)
    p = p[p[:, 0] < p[:, 1]]
    tris = m.tris
    a, b = tris[p[:, 0]], tris[p[:, 1]]
    keep = (m.tri_poly[p[:, 0]] != m.tri_poly[p[:, 1]]) & (shell_of_vert[a[:, 0]] == shell_of_vert[b[:, 0]])
    shared = (a[:, :, None] == b[:, None, :]).any(axis=(1, 2))
    keep &= ~shared
    a, b = a[keep], b[keep]
    if not len(a):
        return 0
    tol = _diag(co) * 1e-6

    def straddles(t, other):
        o0, o1, o2 = co[other[:, 0]], co[other[:, 1]], co[other[:, 2]]
        nrm = np.cross(o1 - o0, o2 - o0)
        ln = np.linalg.norm(nrm, axis=1, keepdims=True)
        nrm = nrm / np.maximum(ln, 1e-30)
        d = np.einsum("ijk,ik->ij", co[t] - o0[:, None, :], nrm)
        return (d > tol).any(axis=1) & (d < -tol).any(axis=1)
    real = straddles(a, b) & straddles(b, a)
    return int(real.sum())


# ---------- floating parts across objects ----------

def _shell_boxes(rep, name):
    np = _np()
    m, inv, count, tri_area = rep["_shell_data"]
    shells = []
    if not len(m.tris):
        return shells
    tri_shell = inv[m.tris[:, 0]]
    for s in range(count):
        tri_idx = np.nonzero(tri_shell == s)[0]
        if not len(tri_idx):
            continue
        vidx = np.unique(m.tris[tri_idx].ravel())
        pts = m.co[vidx]
        shells.append({"object": name, "id": s, "min": pts.min(axis=0), "max": pts.max(axis=0), "pts": pts,
                       "tris": m.tris[tri_idx], "co": m.co, "area": float(tri_area[tri_idx].sum())})
    return shells


def _tree_of(s, inflate=0.0):
    np = _np()
    from mathutils.bvhtree import BVHTree
    key = "tree" if not inflate else "tree_in"
    if key not in s:
        vidx, local = np.unique(s["tris"].ravel(), return_inverse=True)
        tris = local.reshape(-1, 3)
        co = s["co"][vidx]
        if inflate:  # push every point out along its normal: faces lying against another part now cut into it
            v0, v1, v2 = co[tris[:, 0]], co[tris[:, 1]], co[tris[:, 2]]
            fn = np.cross(v1 - v0, v2 - v0)
            vn = np.zeros_like(co)
            for k in range(3):
                np.add.at(vn, tris[:, k], fn)
            vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-30)
            co = co + vn * inflate
        s[key] = BVHTree.FromPolygons([tuple(c) for c in co], tris.tolist(), all_triangles=True)
    return s[key]


def _touching(a, b, tol):
    if (a["min"] - tol > b["max"]).any() or (b["min"] - tol > a["max"]).any():
        return False
    ta, tb = _tree_of(a), _tree_of(b)
    if ta.overlap(tb):
        return True
    if _tree_of(a, tol).overlap(tb) or _tree_of(b, tol).overlap(ta):
        return True
    for src, dst in ((a, tb), (b, ta)):
        pts = src["pts"]
        step = max(1, len(pts) // 400)
        for p in pts[::step]:
            hit = dst.find_nearest(Vector(p), tol)
            if hit[0] is not None:
                return True
    return False


def _same_plane(per_object, limit=20000):
    """Faces of different pieces lying on the same plane, facing the same way and overlapping (z-fighting)."""
    np = _np()
    from mathutils.geometry import intersect_tri_tri_2d
    rows = []
    for name, rep in per_object.items():
        m, inv, count, tri_area = rep["_shell_data"]
        if len(m.tris):
            rows.append((name, m, inv[m.tris[:, 0]]))
    if not rows:
        return []
    diag = _diag(np.concatenate([r[1].co for r in rows]))
    buckets = {}
    for oi, (name, m, shell) in enumerate(rows):
        t = m.tris
        v0, v1, v2 = m.co[t[:, 0]], m.co[t[:, 1]], m.co[t[:, 2]]
        nrm = np.cross(v1 - v0, v2 - v0)
        ln = np.linalg.norm(nrm, axis=1)
        ok = ln > (diag * 1e-5) ** 2
        nrm[ok] /= ln[ok, None]
        ok &= nrm[:, 2] > -0.9  # faces looking down rest on something (or the ground): not seen
        off = np.einsum("ij,ij->i", nrm, v0)
        keys = np.column_stack([np.round(nrm * 2000).astype(np.int64),
                                np.round(off / max(diag * 2e-5, 1e-9)).astype(np.int64)])
        for i in np.nonzero(ok)[0]:
            buckets.setdefault(tuple(keys[i]), {}).setdefault((oi, int(shell[i])), []).append(int(i))
    found = set()
    tests = 0
    for key, pieces in buckets.items():
        if len(pieces) < 2:
            continue
        nvec = Vector([float(c) for c in key[:3]]).normalized()
        u = np.array(nvec.orthogonal().normalized())
        v = np.cross(np.array(nvec), u)
        flat = {}
        for pk, idx in pieces.items():
            m = rows[pk[0]][1]
            tri = m.co[m.tris[np.array(idx)]]  # (k, 3, 3)
            p2 = np.stack([tri @ u, tri @ v], axis=-1)  # (k, 3, 2)
            c = p2.mean(axis=1, keepdims=True)
            p2 = c + (p2 - c) * 0.98  # shrink a little: faces that only share an edge don't count
            flat[pk] = p2
        keys_ = sorted(flat)
        for x in range(len(keys_)):
            for y in range(x + 1, len(keys_)):
                ka, kb = keys_[x], keys_[y]
                pair = tuple(sorted([(rows[ka[0]][0], ka[1]), (rows[kb[0]][0], kb[1])]))
                if pair in found:
                    continue
                A, B = flat[ka], flat[kb]
                amin, amax = A.min(axis=1), A.max(axis=1)
                bmin, bmax = B.min(axis=1), B.max(axis=1)
                if len(A) * len(B) > 4_000_000:
                    A, B = A[:2000], B[:2000]
                    amin, amax, bmin, bmax = amin[:2000], amax[:2000], bmin[:2000], bmax[:2000]
                hit = ((amin[:, None, :] < bmax[None, :, :]) & (bmin[None, :, :] < amax[:, None, :])).all(axis=2)
                for i, j in zip(*np.nonzero(hit)):
                    tests += 1
                    if intersect_tri_tri_2d(*[Vector(p) for p in A[i]], *[Vector(p) for p in B[j]]):
                        found.add(pair)
                        break
                    if tests > limit:
                        break
    return [{"a": a, "b": b} for a, b in sorted({(min(x[0], y[0]), max(x[0], y[0])) for x, y in found})]


def _floating(per_object, allow, ground_tol):
    np = _np()
    shells = []
    for name, rep in per_object.items():
        if name in allow:
            continue
        shells += _shell_boxes(rep, name)
    if len(shells) < 2:
        return []
    lows = np.array([s["min"][2] for s in shells])
    ground = lows.min()
    diag = float(np.linalg.norm(np.max([s["max"] for s in shells], axis=0) - np.min([s["min"] for s in shells], axis=0)))
    tol = max(ground_tol, diag * 0.002)
    n = len(shells)
    parent = list(range(n + 1))  # n = the ground

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)
    for i, s in enumerate(shells):
        if s["min"][2] <= ground + tol:
            join(i, n)
    precise = n <= 400
    for i in range(n):
        for j in range(i + 1, n):
            if find(i) == find(j):
                continue
            a, b = shells[i], shells[j]
            if precise:
                if _touching(a, b, tol):
                    join(i, j)
            elif not ((a["min"] - tol > b["max"]).any() or (b["min"] - tol > a["max"]).any()):
                join(i, j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    main = find(n) if any(find(i) == find(n) for i in range(n)) else max(groups, key=lambda g: sum(shells[i]["area"] for i in groups[g]))
    out = []
    for g, members in groups.items():
        if g == main:
            continue
        for i in members:
            s = shells[i]
            c = (s["min"] + s["max"]) / 2.0
            out.append({"object": s["object"], "center": [round(float(v), 4) for v in c],
                        "size": [round(float(v), 4) for v in (s["max"] - s["min"])]})
    return out


# ---------- verify ----------

def _issues(name, r, allow_open, budget):
    errors, warnings = [], []
    if r["non_manifold_edges"]:
        errors.append(f"{name}: {r['non_manifold_edges']} edges shared by 3+ faces (inner walls / bad merges)")
    holes = r["boundary_edges"] - r.get("seam_edges", 0)
    if holes and not allow_open:
        errors.append(f"{name}: {holes} open edges (holes in the surface); fill them, or allow_open "
                      f"for cards / planes")
    if r["loose_verts"] or r["loose_edges"]:
        errors.append(f"{name}: {r['loose_verts']} loose vertices and {r['loose_edges']} loose edges (n.cleanup)")
    if r["zero_area_faces"]:
        errors.append(f"{name}: {r['zero_area_faces']} faces with no area (n.cleanup; from a bevel over small cuts: "
                      f"n.mark_bevel before the cuts, then n.bevel(part, limit='weight'))")
    if r["flipped_faces"]:
        errors.append(f"{name}: {r['flipped_faces']} edges between faces facing opposite ways (n.cleanup fixes "
                      f"normals)")
    if r["inverted_shells"]:
        errors.append(f"{name}: {r['inverted_shells']} parts are inside out (normals point in; n.cleanup)")
    if r["mirrored"]:
        errors.append(f"{name}: negative scale (mirrored object); apply it (n.apply_transforms) and fix normals")
    if budget and r["triangles_total"] > budget:
        errors.append(f"{name}: {r['triangles_total']} triangles, over the budget of {budget}")
    if r["duplicate_verts"]:
        warnings.append(f"{name}: {r['duplicate_verts']} vertices on top of others (weld: n.cleanup)")
    if r["ngons_not_flat"]:
        warnings.append(f"{name}: {r['ngons_not_flat']} faces with 5+ sides that are not flat (shading errors)")
    if not r["scale_applied"]:
        warnings.append(f"{name}: scale {r['scale']} not applied (n.apply_transforms)")
    si = r.get("self_intersections")
    if isinstance(si, int) and si:
        warnings.append(f"{name}: {si} faces cut through other faces of the same piece")
    if r.get("uv") and r.get("uv_overlap", 0) > 0.005:
        warnings.append(f"{name}: UVs overlap on {r['uv_overlap'] * 100:.1f}% of their area")
    if r.get("uv") and r.get("uv_stretch", 0) > 0.35:
        warnings.append(f"{name}: UVs stretched (average texel density off by {r['uv_stretch'] * 100:.0f}%)")
    return errors, warnings


def _part_seams(per):
    """Open edges that lie exactly on another checked object's open edge are where split parts meet (one closed
    model cut into parts): counted as 'seam_edges', not holes."""
    from mathutils import Vector
    from mathutils.kdtree import KDTree
    rows = [(name, r.pop("_seam_data", None)) for name, r in per.items()]
    rows = [(n, mid) for n, mid in rows if mid is not None and len(mid)]
    if len(rows) < 2:
        return
    np = _np()
    allmid = np.concatenate([mid for _, mid in rows])
    span = float(np.linalg.norm(allmid.max(axis=0) - allmid.min(axis=0))) or 1.0
    tol = max(span * 1e-5, 1e-7)
    owner = np.concatenate([np.full(len(mid), i) for i, (_, mid) in enumerate(rows)])
    tree = KDTree(len(allmid))
    for i, p in enumerate(allmid):
        tree.insert(Vector(p), i)
    tree.balance()
    for k, (name, mid) in enumerate(rows):
        n = 0
        for p in mid:
            if any(owner[idx] != k for _, idx, _ in tree.find_range(Vector(p), tol)):
                n += 1
        if n:
            per[name]["seam_edges"] = n


def verify(objs=None, allow_open=False, budget=None, symmetry="X", uv=True, allow_floating=(), evaluated=True):
    """The quality report of verify_mesh: topology, normals, loose and floating parts, UVs, scale.

    objs: objects (default every visible mesh). allow_open: open surfaces are fine (planes, leaves).
    budget: maximum triangles over all objects. Returns {"pass", "errors", "warnings", "objects", "floating"}.

        rep = n.verify([body, lid]); print(rep["pass"], rep["errors"])
    """
    objs = [o for o in (to_list(objs) if objs is not None else core.objects()) if o.type in ("MESH", "CURVE",
                                                                                              "FONT", "SURFACE")]
    if not objs:
        raise ValueError("verify: no mesh objects to check")
    core.update()
    dg = bpy.context.evaluated_depsgraph_get()
    per = {}
    errors, warnings = [], []
    for o in objs:
        per[o.name] = mesh_stats(o, evaluated, dg, symmetry=symmetry, uv=uv)
    _part_seams(per)
    for o in objs:
        r = per[o.name]
        e, w = _issues(o.name, r, allow_open, None)
        errors += e
        warnings += w
    total = sum(r["triangles_total"] for r in per.values())
    if budget and total > int(budget):
        errors.append(f"{total} triangles in all, over the budget of {int(budget)}")
    allow = set(to_list(allow_floating) and [o.name for o in to_list(allow_floating)])
    floating = _floating(per, allow, 0.0005)
    if floating:
        names = sorted({f["object"] for f in floating})
        errors.append(f"{len(floating)} floating parts (touching nothing) in {', '.join(names)}; move them onto the "
                      f"model (n.align / n.snap) or pass allow_floating")
    for pair in _same_plane(per):
        who = pair["a"] if pair["a"] == pair["b"] else f"{pair['a']} and {pair['b']}"
        warnings.append(f"{who}: pieces with faces on the same plane facing the same way (they flicker / show "
                        f"black patches); move one by a millimeter")
    for r in per.values():
        r.pop("_shell_data", None)
    return {"pass": not errors, "errors": errors, "warnings": warnings, "triangles": total,
            "objects": per, "floating": floating}


def fingerprint(obj, depsgraph=None):
    """A short hash of an object's evaluated mesh and transform (changes when the model changes)."""
    import hashlib
    np = _np()
    obj = core.get(obj)
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    h = hashlib.sha1()
    h.update(np.round(np.array(obj.matrix_world, dtype=np.float64), 6).tobytes())
    if obj.type == "MESH":
        ev = obj.evaluated_get(dg)
        me = ev.data
        n = len(me.vertices)
        co = np.empty(n * 3, np.float32)
        me.vertices.foreach_get("co", co)
        h.update(np.round(co.astype(np.float64), 6).tobytes())
        h.update(str((n, len(me.edges), len(me.polygons))).encode())
    return h.hexdigest()[:16]


# ---------- measure ----------

def measure(objs):
    """Sizes in meters: {"name": {"size": [x, y, z], "min", "max", "center"}} plus "all" for the group.

        n.measure([body, barrel])["all"]["size"]
    """
    objs = to_list(objs)
    out = {}
    for o in objs:
        b = core.bounds(o)
        out[o.name] = _box(b)
    if len(objs) > 1:
        out["all"] = _box(core.bounds(objs))
    return out


def _box(b):
    r = lambda v: [round(float(c), 4) for c in v]
    return {"size": r(b.size), "min": r(b.min), "max": r(b.max), "center": r(b.center)}


def _tree(obj, dg):
    from mathutils.bvhtree import BVHTree
    np = _np()
    m = _Mesh(obj, True, dg)
    if not len(m.tris):
        return None, m
    return BVHTree.FromPolygons([tuple(c) for c in m.co], m.tris.tolist(), all_triangles=True), m


def distance(a, b):
    """How far apart two objects are: closest surface distance (0 when touching / overlapping), center distance,
    and the gap per axis between their bounds (negative = overlapping on that axis)."""
    np = _np()
    a, b = core.get(a), core.get(b)
    core.update()
    dg = bpy.context.evaluated_depsgraph_get()
    ta, ma = _tree(a, dg)
    tb, mb = _tree(b, dg)
    ba, bb = core.bounds(a), core.bounds(b)
    gap = [round(float(max(bb.min[i] - ba.max[i], ba.min[i] - bb.max[i])), 4) for i in range(3)]
    out = {"center_distance": round((ba.center - bb.center).length, 4), "gap_xyz": gap}
    if ta is None or tb is None:
        return out
    if ta.overlap(tb):
        out["surface_distance"] = 0.0
        out["touching"] = True
        return out
    best = float("inf")
    for src, dst in ((ma, tb), (mb, ta)):
        step = max(1, len(src.co) // 3000)
        for p in src.co[::step]:
            hit = dst.find_nearest(Vector(p))
            if hit[0] is not None:
                best = min(best, hit[3])
    out["surface_distance"] = round(best, 5)
    out["touching"] = best <= 1e-4
    return out


def compare(objs, reference):
    """How well objects match a reference / ghost object: size ratios, bounds overlap (IoU) and the average surface
    distance both ways (as meters and as a share of the reference's size)."""
    np = _np()
    objs = to_list(objs)
    ref = core.get(reference)
    core.update()
    dg = bpy.context.evaluated_depsgraph_get()
    bo, br = core.bounds(objs), core.bounds(ref)
    lo = np.maximum(np.array(bo.min), np.array(br.min))
    hi = np.minimum(np.array(bo.max), np.array(br.max))
    inter = float(np.prod(np.clip(hi - lo, 0, None)))
    vol = lambda b: float(np.prod(np.array(b.size)))
    union = vol(bo) + vol(br) - inter
    out = {"size": [round(float(c), 4) for c in bo.size], "reference_size": [round(float(c), 4) for c in br.size],
           "size_ratio": [round(float(bo.size[i] / br.size[i]), 3) if br.size[i] > 1e-9 else None for i in range(3)],
           "center_offset": [round(float(c), 4) for c in (bo.center - br.center)],
           "bounds_iou": round(inter / union, 3) if union > 0 else 0.0}
    tr, mr = _tree(ref, dg)
    pts_o = np.concatenate([_Mesh(o, True, dg).co for o in objs if o.type == "MESH"] or [np.zeros((0, 3))])
    trees_o = [t for t in (_tree(o, dg)[0] for o in objs if o.type == "MESH") if t is not None]
    if tr is None or not trees_o or not len(pts_o):
        return out

    def mean_dist(points, trees):
        step = max(1, len(points) // 2000)
        d = []
        for p in points[::step]:
            best = min((t.find_nearest(Vector(p))[3] for t in trees), default=None)
            if best is not None:
                d.append(best)
        return float(np.mean(d)) if d else None
    d1 = mean_dist(pts_o, [tr])
    d2 = mean_dist(mr.co, trees_o)
    diag = float(np.linalg.norm(np.array(br.size))) or 1.0
    out["mean_distance_to_reference"] = round(d1, 5) if d1 is not None else None
    out["mean_distance_from_reference"] = round(d2, 5) if d2 is not None else None
    if d1 is not None and d2 is not None:
        out["chamfer_share"] = round((d1 + d2) / 2.0 / diag, 4)
    return out
