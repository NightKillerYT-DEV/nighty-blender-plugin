# SPDX-License-Identifier: GPL-3.0-or-later
"""Untangle a decimated mesh: faces that pass through each other, or fold back over their neighbours where the real
surface does not (the edge collapse does that on thin features and on the stair-stepped rims of generated meshes),
are taken apart where they are. Per spot it tries, in order: an edge flip, a vertex moved back onto the surface
(alone, or the spot's vertices relaxed together on the surface), and as a last resort a collapse of a short edge
there. A change is kept only if the spot gets cleaner and nothing moves off the surface by more than a small
tolerance; nothing else moves. Flat slivers get the edge across their tiny angle flipped (shape unchanged).

    from nighty.mesh.untangle import untangle
    rep = untangle(obj, reference=mesh_before_decimate)   # {"crossing": [before, after], ...}
"""

import math

import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

FOLD_DOT = -0.7    # two neighbouring faces facing more than ~135 degrees apart: a fold (if the surface does not)
FLIP_DOT = -0.3    # a face facing against the real surface under it
SLIVER_DEG = 2.0   # a triangle with an angle under this is a sliver (fixed only where flat: an edge flip)
DEV = 2e-4         # a change may take the surface this far off the original (share of the size)


def _tris_of(faces):
    """Points / triangles (fans) / owner face index for a list of bmesh faces."""
    vid, pts, tris, owner = {}, [], [], []
    for fi, f in enumerate(faces):
        ids = []
        for v in f.verts:
            k = vid.get(v)
            if k is None:
                k = vid[v] = len(pts)
                pts.append(v.co.copy())
            ids.append(k)
        for j in range(1, len(ids) - 1):
            tris.append((ids[0], ids[j], ids[j + 1]))
            owner.append(fi)
    return pts, tris, owner


def crossing_pairs(faces, tol):
    """Pairs of the given bmesh faces that pass through each other (sharing a vertex does not count; the same test
    as nighty.check's 'faces cut through other faces')."""
    faces = list(faces)
    pts, tris, owner = _tris_of(faces)
    if len(tris) < 2:
        return []
    tree = BVHTree.FromPolygons(pts, tris, all_triangles=True)
    p = np.array(tree.overlap(tree), dtype=np.int64).reshape(-1, 2)
    if not len(p):
        return []
    co = np.array(pts, dtype=np.float64)
    tr = np.array(tris, dtype=np.int64)
    ow = np.array(owner, dtype=np.int64)
    p = p[p[:, 0] < p[:, 1]]
    a, b = tr[p[:, 0]], tr[p[:, 1]]
    keep = ~(a[:, :, None] == b[:, None, :]).any(axis=(1, 2)) & (ow[p[:, 0]] != ow[p[:, 1]])
    p, a, b = p[keep], a[keep], b[keep]
    if not len(p):
        return []

    def straddles(t, o):
        o0, o1, o2 = co[o[:, 0]], co[o[:, 1]], co[o[:, 2]]
        n = np.cross(o1 - o0, o2 - o0)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
        d = np.einsum("ijk,ik->ij", co[t] - o0[:, None, :], n)
        return (d > tol).any(axis=1) & (d < -tol).any(axis=1)
    real = straddles(a, b) & straddles(b, a)
    out = {(min(i, j), max(i, j)) for i, j in zip(ow[p[real, 0]].tolist(), ow[p[real, 1]].tolist())}
    return [(faces[i], faces[j]) for i, j in sorted(out)]


def surface_tree(src):
    """A BVH tree of the surface to stay on (a bpy Mesh, a BMesh or a BVHTree already)."""
    if isinstance(src, BVHTree):
        return src
    if isinstance(src, bmesh.types.BMesh):
        return BVHTree.FromBMesh(src)
    src.calc_loop_triangles()
    co = [v.co.copy() for v in src.vertices]
    return BVHTree.FromPolygons(co, [t.vertices[:] for t in src.loop_triangles], all_triangles=True)


def _face_index(bm):
    faces = list(bm.faces)
    kd = KDTree(len(faces))
    for i, f in enumerate(faces):
        kd.insert(f.calc_center_median(), i)
    kd.balance()
    return kd, faces


def _can_flip(e):
    """An edge between two triangles whose other two corners are not joined already (a flip would double that
    edge and leave the mesh non-manifold)."""
    if len(e.link_faces) != 2 or any(len(f.verts) != 3 for f in e.link_faces):
        return False
    a, b = e.verts
    c, d = [next(v for v in f.verts if v is not a and v is not b) for f in e.link_faces]
    if c is d:
        return False
    return not any(x.other_vert(c) is d for x in c.link_edges)


def _min_angle(f):
    vs = [v.co for v in f.verts]
    k = len(vs)
    best = 180.0
    for i in range(k):
        a, b, c = vs[i - 1], vs[i], vs[(i + 1) % k]
        u, w = a - b, c - b
        if u.length < 1e-12 or w.length < 1e-12:
            return 0.0
        best = min(best, math.degrees(u.angle(w)))
    return best


class _Untangler:
    def __init__(self, bm, tree, size):
        self.bm = bm
        self.tree = tree
        self.tol = 1e-6 * size          # touching / crossing tolerance (as nighty.check)
        self.dev = DEV * size
        self.area_eps = (1e-6 * size) ** 2
        self.fixed = {"flip": 0, "move": 0, "collapse": 0}
        self._near = {}

    def near(self, p):
        key = (p[0], p[1], p[2])   # unchanged faces ask about the same points again and again
        hit = self._near.get(key)
        if hit is None:
            q, n, _i, d = self.tree.find_nearest(p)
            hit = self._near[key] = (q, n, d if d is not None else 0.0)
        return hit

    # ---- what is wrong
    def artifact_fold(self, e):
        f1, f2 = e.link_faces
        if f1.normal.dot(f2.normal) >= FOLD_DOT:
            return False
        n1 = self.near(f1.calc_center_median())[1]
        n2 = self.near(f2.calc_center_median())[1]
        return n1 is not None and n2 is not None and n1.dot(n2) > 0.0   # the real surface does not fold here

    def flipped(self, f):
        n = self.near(f.calc_center_median())[1]
        return n is not None and f.normal.dot(n) < FLIP_DOT

    def region(self, verts, index=None):
        """The faces around a spot: three rings, plus anything close in space (the other side of a thin part)."""
        kd, kd_faces = index or (self.kd, self.kd_faces)
        faces = {f for v in verts for f in v.link_faces}
        for _ in range(2):
            faces |= {g for f in list(faces) for v in f.verts for g in v.link_faces}
        c = sum((v.co for v in verts), Vector()) / max(1, len(verts))
        r = max((v.co - c).length for v in verts)
        r += 2.0 * max((e.calc_length() for v in verts for e in v.link_edges), default=0.0)
        for _co, i, _d in kd.find_range(c, r):
            f = kd_faces[i]
            if f.is_valid:
                faces.add(f)
        return [f for f in faces if f.is_valid]

    def score(self, faces):
        faces = [f for f in faces if f.is_valid]
        for f in faces:
            f.normal_update()
        cross = len(crossing_pairs(faces, self.tol))
        edges = {e for f in faces for e in f.edges}
        folds = sum(1 for e in edges if len(e.link_faces) == 2 and self.artifact_fold(e))
        flips = sum(1 for f in faces if self.flipped(f))
        verts = {v for f in faces for v in f.verts}
        broken = (sum(1 for e in edges if len(e.link_faces) != 2) + sum(1 for v in verts if not v.is_manifold)
                  + sum(1 for f in faces if f.calc_area() <= self.area_eps))
        return 10 * cross + folds + flips + 100 * broken

    # ---- fixes; each returns True if it kept a change
    def try_flips(self, verts):
        region = self.region(verts)
        before = self.score(region)
        if before == 0:
            return True
        edges = sorted({e for v in verts for e in v.link_edges if e.other_vert(v) in verts
                        and len(e.link_faces) == 2}, key=lambda e: (-e.calc_length(), e.index))
        for e in edges:
            if not e.is_valid or not _can_flip(e):
                continue
            ne = bmesh.utils.edge_rotate(e, True)
            if ne is None:
                continue
            mid = (ne.verts[0].co + ne.verts[1].co) / 2
            if self.near(mid)[2] <= self.dev and self.score(self.region(verts)) < before:
                return True
            bmesh.utils.edge_rotate(ne, True)
        return False

    def try_moves(self, verts):
        region = self.region(verts)
        before = self.score(region)
        if before == 0:
            return True
        old = {v: v.co.copy() for v in verts}

        def ok():
            return self.score(self.region(verts)) < before and all(self.near(v.co)[2] <= self.dev for v in verts)
        for v in sorted(verts, key=lambda x: x.index):   # one vertex: back onto the surface, or toward the
            # middle of its neighbours (on it); in index order, so a run gives the same mesh every time
            nb = [e.other_vert(v).co for e in v.link_edges]
            avg = sum(nb, Vector()) / max(1, len(nb))
            for target in (self.near(v.co)[0], self.near((avg + v.co) / 2)[0], self.near(avg)[0]):
                if target is None:
                    continue
                v.co = target
                if ok():
                    return True
                v.co = old[v]
        for _ in range(4):   # the whole spot (a small pleat): relax it on the surface
            new = {}
            for v in verts:
                nb = [e.other_vert(v).co for e in v.link_edges]
                avg = sum(nb, Vector()) / max(1, len(nb))
                new[v] = self.near(avg)[0] or v.co
            for v, c in new.items():
                v.co = c
            if ok():
                return True
        for v, c in old.items():
            v.co = c
        return False

    def try_collapse(self, verts):
        """On a copy (a collapse cannot be undone in place): the short edges of the spot, one at a time, merged to
        their middle on the surface. Returns True and swaps the copy in when one leaves the spot cleaner."""
        region = self.region(verts)
        before = self.score(region)
        if before == 0:
            return True
        bm = self.bm
        bm.verts.index_update()
        bm.edges.index_update()
        edges = sorted({e for v in verts for e in v.link_edges if e.other_vert(v) in verts},
                       key=lambda e: (e.calc_length(), e.index))[:4]
        vidx = [v.index for v in verts]
        for e in edges:
            cp = bm.copy()
            cp.verts.ensure_lookup_table()
            cp.edges.ensure_lookup_table()
            ce = cp.edges[e.index]
            mid = (ce.verts[0].co + ce.verts[1].co) / 2
            target = self.near(mid)[0] or mid
            if (target - mid).length > self.dev:
                cp.free()
                continue
            keep_verts = {cp.verts[i] for i in vidx}
            try:
                bmesh.ops.collapse(cp, edges=[ce], uvs=True)
            except Exception:  # noqa: BLE001 - not collapsible here
                cp.free()
                continue
            alive = {v for v in keep_verts if v.is_valid}
            for v in alive:
                if (v.co - mid).length < 1e-9:
                    v.co = target
            if alive and self.score(self.region(alive, index=_face_index(cp))) < before:
                self.bm.free()
                self.bm = cp
                return True
            cp.free()
        return False

    # ---- driver
    def sites(self):
        """Spots to fix (sets of vertices): crossing pairs, folds the real surface does not have, faces facing
        against it."""
        bm = self.bm
        bm.normal_update()
        faces = list(bm.faces)
        out, counts = [], {"crossing": 0, "folds": 0, "flipped": 0}
        for a, b in crossing_pairs(faces, self.tol):
            out.append({*a.verts, *b.verts})
            counts["crossing"] += 1
        for e in bm.edges:
            if len(e.link_faces) == 2 and e.link_faces[0].normal.dot(e.link_faces[1].normal) < FOLD_DOT:
                if self.artifact_fold(e):
                    out.append({*e.link_faces[0].verts, *e.link_faces[1].verts})
                    counts["folds"] += 1
        for f in faces:
            if self.flipped(f):
                out.append(set(f.verts))
                counts["flipped"] += 1
        return out, counts

    def index(self):
        self.kd, self.kd_faces = _face_index(self.bm)

    def run(self, rounds):
        first = last = None
        for _ in range(rounds):
            self.bm.verts.index_update()
            self.bm.edges.index_update()
            sites, last = self.sites()
            if first is None:
                first = last
            if not sites:
                break
            self.index()
            progress = False
            touched = set()
            for verts in sites:
                verts = {v for v in verts if v.is_valid}
                if not verts or verts & touched:
                    continue
                if self.try_flips(verts):
                    self.fixed["flip"] += 1
                elif self.try_moves(verts):
                    self.fixed["move"] += 1
                elif self.try_collapse(verts):
                    self.fixed["collapse"] += 1
                    progress = True
                    break   # the mesh is a new copy now: look again
                else:
                    continue
                progress = True
                touched |= verts
            if not progress:
                break
        _s, last = self.sites()
        return first or last, last

    def slivers(self):
        """Flat slivers: flip the edge across the tiny angle when both faces lie flat (shape unchanged)."""
        n = 0
        for f in list(self.bm.faces):
            if not f.is_valid or len(f.verts) != 3 or _min_angle(f) >= SLIVER_DEG:
                continue
            longest = max(f.edges, key=lambda e: e.calc_length())
            if len(longest.link_faces) != 2 or not _can_flip(longest):
                continue
            g = longest.link_faces[0] if longest.link_faces[1] is f else longest.link_faces[1]
            if len(g.verts) != 3 or f.normal.dot(g.normal) < math.cos(math.radians(3.0)):
                continue
            before = min(_min_angle(f), _min_angle(g))
            ne = bmesh.utils.edge_rotate(longest, True)
            if ne is None:
                continue
            new = list(ne.link_faces)
            for x in new:
                x.normal_update()
            if (min(_min_angle(x) for x in new) > before and all(x.calc_area() > self.area_eps for x in new)
                    and new[0].normal.dot(new[1].normal) > math.cos(math.radians(3.0))):
                n += 1
            else:
                bmesh.utils.edge_rotate(ne, True)
        return n


def untangle(obj, reference=None, rounds=6, slivers=True):
    """Takes apart faces of `obj` that cross each other or fold back over their neighbours (see the module doc).
    reference: the mesh (bpy Mesh or BMesh) the surface should stay on: the dense or pre-decimate mesh (default:
    obj's own mesh as it is now). Returns {"crossing": [before, after], "folds": [...], "flipped": [...],
    "fixed": {"flip": n, "move": n, "collapse": n}, "slivers": n}."""
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    if not len(bm.faces):
        bm.free()
        return {"crossing": [0, 0], "folds": [0, 0], "flipped": [0, 0],
                "fixed": {"flip": 0, "move": 0, "collapse": 0}, "slivers": 0}
    co = np.array([v.co[:] for v in bm.verts])
    size = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0))) or 1.0
    own = None
    if reference is None:
        own = bm.copy()
        reference = own
    u = _Untangler(bm, surface_tree(reference), size)
    n0 = len(bm.faces)
    first, last = u.run(rounds)
    n_sl = u.slivers() if slivers else 0
    topped = _top_up(u.bm, n0 - len(u.bm.faces))
    u.bm.normal_update()
    u.bm.to_mesh(me)
    me.update()
    u.bm.free()
    if own is not None:
        own.free()
    return {"crossing": [first["crossing"], last["crossing"]], "folds": [first["folds"], last["folds"]],
            "flipped": [first["flipped"], last["flipped"]], "fixed": dict(u.fixed), "slivers": n_sl,
            "faces_added_back": topped}


def _top_up(bm, missing):
    """Collapses cost 2 faces each: give them back by splitting the longest edges that lie flat (both faces in one
    plane, so the shape does not change), keeping an exact face count. Returns faces added."""
    if missing < 2:
        return 0
    flat = math.cos(math.radians(1.0))
    cand = [e for e in bm.edges if len(e.link_faces) == 2 and all(len(f.verts) == 3 for f in e.link_faces)
            and e.link_faces[0].normal.dot(e.link_faces[1].normal) > flat and not e.seam and e.smooth]
    cand.sort(key=lambda e: -e.calc_length())
    chosen, used = [], set()
    for e in cand:
        if len(chosen) * 2 >= missing:
            break
        fs = set(e.link_faces)
        if fs & used:
            continue
        used |= fs
        chosen.append(e)
    if not chosen:
        return 0
    n0 = len(bm.faces)
    res = bmesh.ops.subdivide_edges(bm, edges=chosen, cuts=1, use_grid_fill=False)
    new_faces = {f for f in res["geom"] if isinstance(f, bmesh.types.BMFace)} | {
        f for v in res["geom_inner"] if isinstance(v, bmesh.types.BMVert) for f in v.link_faces}
    big = [f for f in new_faces if f.is_valid and len(f.verts) > 3]
    if big:
        bmesh.ops.triangulate(bm, faces=big, quad_method='BEAUTY', ngon_method='BEAUTY')
    return len(bm.faces) - n0
