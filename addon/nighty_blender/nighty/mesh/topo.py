# SPDX-License-Identifier: GPL-3.0-or-later
"""Retopology: Quads (QuadriFlow built in, or Instant Meshes / QuadWild / Quad Remesher when present), Low poly
(decimate to an exact face count) and Auto (picks per shape and says why). The dense original stays hidden as the
bake source (obj["nighty_bake_source"])."""

import math
import time

import bmesh
import bpy
import numpy as np

from . import _util as U
from . import stats as S
from . import shape as SH
from . import untangle as UT

# Detail -> triangles (what game engines count). Quads mode makes half as many quads (same triangle budget).
DETAIL_TRIANGLES = {"low": 3000, "medium": 12000, "high": 40000}


def detail_faces(detail="medium", mode="triangles"):
    tris = DETAIL_TRIANGLES.get(detail or "medium", DETAIL_TRIANGLES["medium"])
    return tris // 2 if mode == "quads" else tris


# ---------------------------------------------------------------- bake source

def bake_source(obj):
    """The hidden dense original kept for baking (or None)."""
    src = obj.get("nighty_bake_source")
    if isinstance(src, str):
        src = bpy.data.objects.get(src)
    if src is not None:
        try:
            src.name
        except ReferenceError:
            return None
    return src


def keep_bake_source(obj, mesh=None):
    """Keeps a hidden copy of the object's current (dense) mesh as its bake source; an existing one is kept (it is
    the true original). Returns the source object."""
    old = bake_source(obj)
    if old is not None:
        return old
    me = mesh if mesh is not None else obj.data.copy()
    me.name = obj.data.name + "_high"
    src = bpy.data.objects.new(obj.name + "_high", me)
    src.matrix_world = obj.matrix_world.copy()
    src.parent = obj.parent
    if obj.parent is not None:
        src.matrix_parent_inverse = obj.matrix_parent_inverse.copy()
    for col in obj.users_collection or [bpy.context.scene.collection]:
        col.objects.link(src)
    src.hide_render = True
    src.hide_select = True
    try:
        src.hide_set(True)
    except RuntimeError:
        src.hide_viewport = True
    src["nighty_role"] = "bake_source"
    src["nighty_low"] = obj.name
    obj["nighty_bake_source"] = src
    obj["nighty_high"] = src.name  # the bake code (nighty.bake) finds high polys by this name
    return src


# ---------------------------------------------------------------- reprojection

def reproject(obj, source, method="nearest"):
    """Pulls the vertices onto the source surface (Shrinkwrap, applied). method: nearest | project."""
    mod = obj.modifiers.new("Nighty Reproject", 'SHRINKWRAP')
    mod.target = source
    if method == "project":
        mod.wrap_method = 'PROJECT'
        mod.use_negative_direction = True
        mod.use_positive_direction = True
    else:
        mod.wrap_method = 'NEAREST_SURFACEPOINT'
    mod.wrap_mode = 'ON_SURFACE'
    hide = source.hide_viewport
    source.hide_viewport = False  # a hidden target still evaluates, but be safe
    try:
        U.apply_modifiers(obj, [mod])
    finally:
        source.hide_viewport = hide
    return obj


def snap_to_sharp(obj, segments, max_dist):
    """Moves vertices that sit close to a sharp edge of the original exactly onto it (crisper hard-surface
    corners after a quad remesh). segments: world-space (k, 2, 3). Returns how many moved."""
    if len(segments) == 0:
        return 0
    from mathutils.kdtree import KDTree
    from mathutils import Vector
    co_w = U.world_verts(obj)
    mw = np.array(obj.matrix_world)
    inv = np.linalg.inv(mw)
    p, q = segments[:, 0], segments[:, 1]
    mids = (p + q) / 2
    half = np.linalg.norm(q - p, axis=1) / 2
    kd = KDTree(len(mids))
    for i, m in enumerate(mids):
        kd.insert(Vector(m), i)
    kd.balance()
    reach = float(half.max()) + max_dist
    moved = 0
    new = co_w.copy()
    # which vertices lie on a crease of the result (an edge loop that bends): only those may snap
    me = obj.data
    start, total, lv, le = U.polys(me)
    ids, ang, _ = U.dihedral(me, start, total, le)
    e = U.edges(me)[ids[ang > 20.0]]
    on_crease = np.zeros(len(co_w), dtype=bool)
    on_crease[e.ravel()] = True
    for vi in np.nonzero(on_crease)[0]:
        v = co_w[vi]
        best, bd = None, max_dist
        for (_c, i, _d) in kd.find_range(Vector(v), reach):
            a, b = p[i], q[i]
            ab = b - a
            L2 = float(ab @ ab) or 1e-20
            t = min(1.0, max(0.0, float((v - a) @ ab) / L2))
            c = a + ab * t
            d = float(np.linalg.norm(v - c))
            if d < bd:
                best, bd = c, d
        if best is not None:
            new[vi] = best
            moved += 1
    if moved:
        U.set_verts(me, new @ inv[:3, :3].T + inv[:3, 3])
    return moved


# ---------------------------------------------------------------- decimate (low poly)

def _protect_group(obj, keep_seams, weight=0.5):
    """Vertex group for the Decimate modifier: 1 = free to collapse, lower = collapse later. Only UV seams and
    material borders get it (so UVs and material borders survive). Sharp edges need nothing: the collapse keeps
    them by itself, and protecting them made fans of thin, folded triangles."""
    me = obj.data
    keep = np.zeros(len(me.edges), dtype=bool)
    start, total, lv, le = U.polys(me)
    if keep_seams:
        keep |= U.edge_flags(me, "use_seam")
    if len(me.materials) > 1:
        ids2, fa, fb, _c = U.edge_faces(me, start, total, le)
        mats = U.face_materials(me)
        keep[ids2[mats[fa] != mats[fb]]] = True
    if not keep.any():
        return None
    w = np.ones(len(me.vertices))
    w[U.edges(me)[keep].ravel()] = weight
    vg = obj.vertex_groups.get("nighty_decimate") or obj.vertex_groups.new(name="nighty_decimate")
    vg.add(np.nonzero(w >= 1.0)[0].tolist(), 1.0, 'REPLACE')
    vg.add(np.nonzero(w < 1.0)[0].tolist(), float(weight), 'REPLACE')
    return vg


def _planar(obj, angle_deg):
    bm = U.bm_from(obj)
    before = len(bm.faces)
    bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(angle_deg), use_dissolve_boundaries=False,
                             verts=bm.verts, edges=bm.edges, delimit={'SHARP', 'SEAM', 'MATERIAL'})
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 3], quad_method='BEAUTY',
                          ngon_method='BEAUTY')
    after = len(bm.faces)
    U.bm_to(bm, obj)
    return before, after


def _repair_fins(obj):
    """The edge collapse can leave folded faces: duplicates and fins (edges shared by 3+ faces), which later come
    apart as one-triangle 'parts'. Removes duplicates, keeps the two best faces on each such edge, closes the holes
    that leaves (triangulated; a hole whose edge runs through one vertex twice is widened by the faces around its
    corners first) and drops loose bits, repeating until the mesh is closed again (a few passes at most). Returns
    how many faces were removed."""
    from . import fix as F
    removed = F._remove_duplicate_faces(obj)
    bm = U.bm_from(obj)
    try:
        def dangling(f):   # a fin's other edges are open or also over-shared; a real face's are not
            return sum(1 for ed in f.edges if len(ed.link_faces) != 2)

        def fins():
            kill = set()
            for e in bm.edges:
                if len(e.link_faces) > 2:
                    faces = sorted((f for f in e.link_faces if f not in kill),
                                   key=lambda f: (-dangling(f), f.calc_area()))
                    kill.update(faces[:max(0, len(faces) - 2)])
            return kill

        def crumbs():      # pieces the collapse cut loose (1-3 faces touching nothing): never a real part
            kill, seen = set(), set()
            for f in bm.faces:        # whole connected pieces (a search cut short would split big pieces up)
                if f in seen:
                    continue
                comp, stack = [f], [f]
                seen.add(f)
                while stack:
                    for ed in stack.pop().edges:
                        for g in ed.link_faces:
                            if g not in seen:
                                seen.add(g)
                                comp.append(g)
                                stack.append(g)
                if len(comp) <= 3:
                    kill.update(comp)
            return kill

        def drop(faces):
            bmesh.ops.delete(bm, geom=list(faces), context='FACES_ONLY')
            wire = [e for e in bm.edges if not e.link_faces]
            if wire:
                bmesh.ops.delete(bm, geom=wire, context='EDGES')
            loose = [v for v in bm.verts if not v.link_faces]
            if loose:
                bmesh.ops.delete(bm, geom=loose, context='VERTS')

        def fill():
            for _ in range(3):
                border = [e for e in bm.edges if e.is_boundary]
                if not border:
                    return 0
                made = bmesh.ops.holes_fill(bm, edges=border, sides=0).get("faces", [])
                big = [f for f in made if len(f.verts) > 3]
                if big:
                    bmesh.ops.triangulate(bm, faces=big, quad_method='BEAUTY', ngon_method='BEAUTY')
                border = [e for e in bm.edges if e.is_boundary]
                if not border:
                    return 0
                ring = {f for e in border for v in e.verts for f in v.link_faces}
                drop(ring)
                count[0] += len(ring)
            return len([e for e in bm.edges if e.is_boundary])

        count = [0]
        start = fins() | (crumbs() if len(bm.faces) > 1000 else set())
        if not start and not removed:
            return 0
        kill = start
        for _ in range(4):
            if kill:
                drop(kill)
                count[0] += len(kill)
            fill()
            kill = fins()
            if not kill and not any(e.is_boundary for e in bm.edges):
                break
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        U.bm_to(bm, obj)
        bm = None
    finally:
        if bm is not None:
            bm.free()
    return removed + count[0]


def decimate(obj, faces=None, ratio=None, symmetry="auto", planar="auto", keep_sharp=35.0, keep_seams=True,
             protect=0.5, progress=None, untangle=True):
    """Low poly: collapses the mesh to `faces` triangles (exact within a few faces) or by `ratio`.
    symmetry: 'auto' | 'x' | 'y' | 'z' | None. planar: degrees for a first flat-area merge, 'auto' (2 degrees on
    hard-surface shapes) or None. keep_sharp: angle; edges sharper than it are marked sharp afterwards (the collapse
    keeps crisp edges by itself). keep_seams: UV seams / material borders collapse last. untangle: faces the
    collapse left crossing each other or folded back are taken apart afterwards (see untangle.py). Output is all
    triangles. Returns a report."""
    p = U.Progress(progress)
    t0 = time.monotonic()
    U.require_mesh(obj)
    me = obj.data
    rep = {"object": obj.name, "steps": []}
    _s, tot0, _lv, _le = U.polys(me)
    tris0 = int((tot0 - 2).sum())
    rep["before"] = f"{len(tot0):,} faces ({tris0:,} triangles)"
    surface = UT.surface_tree(me) if untangle else None   # the shape before any collapse, for the untangle pass
    if symmetry == "auto":
        axes = SH.symmetry(obj)
        symmetry = axes[0] if axes else None
        if symmetry:
            rep["steps"].append(f"symmetric on {symmetry.upper()}: decimating both sides the same")
    if planar == "auto":
        planar = 2.0 if SH.classify(obj)["kind"] == "hard_surface" else None
    target = int(faces) if faces else max(4, int(round(tris0 * float(ratio or 0.5))))
    if tris0 > target * 8 and tris0 > 60000:
        # one quick pass down to a few times the target first (all in C): the flat-area merge and the exact-count
        # search below then run on a small mesh (a flat-area merge on 500k faces alone took 24 s)
        p(0.05, "first pass")
        mod = obj.modifiers.new("Nighty Decimate", 'DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.use_collapse_triangulate = True
        if symmetry:
            mod.use_symmetry = True
            mod.symmetry_axis = symmetry.upper()
        mod.ratio = max(1e-6, min(1.0, target * 4 / tris0))
        U.apply_modifiers(obj, [mod])
    if planar:
        p(0.1, "merging flat areas")
        b, a = _planar(obj, float(planar))
        if a < b:
            rep["steps"].append(f"merged flat areas ({b:,} -> {a:,} faces)")
    # triangulate so face counts are triangle counts from here on
    bm = U.bm_from(obj)
    big = [f for f in bm.faces if len(f.verts) > 3]
    if big:
        bmesh.ops.triangulate(bm, faces=big, quad_method='BEAUTY', ngon_method='BEAUTY')
    U.bm_to(bm, obj)
    cur = len(obj.data.polygons)
    if cur <= target:
        rep["steps"].append(f"already at {cur:,} triangles (target {target:,})")
    else:
        vg = _protect_group(obj, keep_seams, protect) if protect else None
        mod = obj.modifiers.new("Nighty Decimate", 'DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.use_collapse_triangulate = True
        if symmetry:
            mod.use_symmetry = True
            mod.symmetry_axis = symmetry.upper()
        if vg is not None:
            mod.vertex_group = vg.name
            mod.vertex_group_factor = 1.0
        # search the ratio that lands on the target (each try re-runs the decimate from the full mesh)
        lo_r, hi_r = 0.0, 1.0
        r = target / cur
        best = None
        for i in range(10):
            mod.ratio = max(1e-6, min(1.0, r))
            n = U.evaluated_face_count(obj)
            p(0.1 + 0.08 * i, f"decimating ({n:,} faces)")
            if best is None or abs(n - target) < abs(best[1] - target) or (
                    abs(n - target) == abs(best[1] - target) and n <= target):
                best = (mod.ratio, n)
            if abs(n - target) <= max(2, target * 0.002):
                break
            if n > target:
                hi_r = min(hi_r, mod.ratio)
            else:
                lo_r = max(lo_r, mod.ratio)
            r_new = mod.ratio * target / max(n, 1)
            if not (lo_r < r_new < hi_r):
                r_new = (lo_r + hi_r) / 2
            r = r_new
        mod.ratio = best[0]
        p(0.9, "applying")
        U.apply_modifiers(obj, [mod])
        if vg is not None:
            obj.vertex_groups.remove(obj.vertex_groups["nighty_decimate"])
        rep["steps"].append(f"decimated to {len(obj.data.polygons):,} triangles (target {target:,})")
    fins = _repair_fins(obj)
    if fins:
        rep["steps"].append(f"removed {fins} folded faces the collapse left (edges with 3+ faces), holes closed")
    if surface is not None:
        p(0.92, "untangling")
        _untangle_step(obj, surface, rep)
    if keep_sharp:
        U.mark_sharp_by_angle(obj.data, float(keep_sharp))
    st = S.analyze(obj)
    rep["after"] = S.short(st)
    rep["faces"] = st["faces"]
    rep["triangles"] = st["triangles"]
    rep["target"] = target
    rep["seconds"] = round(time.monotonic() - t0, 2)
    return rep


def _untangle_step(obj, surface, rep):
    """The untangle pass after a decimate (its own function: other passes hook into decimate around it)."""
    u = UT.untangle(obj, reference=surface)
    rep["untangle"] = u
    c, f, fl = u["crossing"], u["folds"], u["flipped"]
    if c[0] or f[0] or fl[0]:
        n = u["fixed"]
        rep["steps"].append(
            f"untangled the low poly: faces cutting through others {c[0]} -> {c[1]}, folded edges {f[0]} -> {f[1]}, "
            f"faces turned against the surface {fl[0]} -> {fl[1]} ({n['flip']} edge flips, {n['move']} vertex "
            f"moves, {n['collapse']} slivers merged)")
    return u


# ---------------------------------------------------------------- quads

def quadriflow(obj, faces, keep_sharp=True, symmetry=None, seed=0, timeout=300):
    """Blender's built-in QuadriFlow (MIT) on a manifold mesh, in place. Returns the face count.
    It runs in its own background Blender: QuadriFlow can crash (seen in 4.2) or stall on some meshes, and that must
    never take Blender (or a whole job) down with it. Raises RuntimeError when it fails, crashes or times out."""
    import os
    if os.environ.get("NIGHTY_QF_HERE") == "1":
        return _quadriflow_here(obj, faces, keep_sharp, symmetry, seed)
    from . import worker as W
    if not W.available():
        return _quadriflow_here(obj, faces, keep_sharp, symmetry, seed)
    tmp = bpy.data.objects.new("nighty_qf_in", obj.data)
    tmp_name = tmp.name
    run = W.Run([tmp], [{"op": "quadriflow", "args": {"faces": int(faces), "keep_sharp": bool(keep_sharp),
                                                       "symmetry": symmetry, "seed": int(seed)}}],
                env_extra={"NIGHTY_QF_HERE": "1"})
    bpy.data.objects.remove(tmp)
    try:
        code = run.run_blocking(timeout=timeout)
        if code != 0:
            raise RuntimeError("QuadriFlow crashed or stalled on this shape" if code else "QuadriFlow failed")
        _res, loaded = run.collect()
        ob = loaded.get(tmp_name)
        if ob is None:
            raise RuntimeError("QuadriFlow gave no result")
        new = ob.data
        bpy.data.objects.remove(ob)
        U.replace_mesh(obj, new)
    finally:
        run.close()
    return len(obj.data.polygons)


def _quadriflow_here(obj, faces, keep_sharp=True, symmetry=None, seed=0):
    """QuadriFlow in this Blender (blocking; used inside the background Blender).
    QuadriFlow refuses edges shorter than 0.0001 units, so the mesh is scaled to ~10 units while it runs and welded
    at that tiny size first. (Not much bigger: at ~1000 units its sharp-edge mode stalls on dense meshes.)"""
    from mathutils import Matrix
    me = obj.data
    size = U.diag(U.verts(me)) or 1.0
    k = 10.0 / size
    me.transform(Matrix.Scale(k, 4))
    bm = U.bm_from(obj)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=2.5e-4)
    bmesh.ops.dissolve_degenerate(bm, dist=2.5e-4, edges=bm.edges)
    U.bm_to(bm, obj)
    me = obj.data
    me.use_mirror_x = symmetry == "x"
    me.use_mirror_y = symmetry == "y"
    me.use_mirror_z = symmetry == "z"
    try:
        with U.override(obj):
            res = bpy.ops.object.quadriflow_remesh(
                use_mesh_symmetry=bool(symmetry), use_preserve_sharp=bool(keep_sharp), use_preserve_boundary=True,
                preserve_attributes=False, smooth_normals=False, mode='FACES', target_faces=int(faces),
                seed=int(seed))
    finally:
        obj.data.transform(Matrix.Scale(1.0 / k, 4))
        obj.data.update()
    if 'FINISHED' not in res:
        raise RuntimeError("QuadriFlow could not remesh this shape")
    return len(obj.data.polygons)


def _prepare_for_quads(obj, faces, rep, p, sharp):
    """QuadriFlow needs a manifold mesh with consistent normals. Dense input is pre-reduced: much faster, and the
    final shape comes from reprojecting onto the original anyway. With sharp-edge preservation on noisy dense input
    QuadriFlow can stall, so then it is reduced further (which also removes the noise)."""
    from .fix import non_manifold_counts, voxel_remesh, recalc_normals
    nm = non_manifold_counts(obj)
    if nm["open_edges"] or nm["bad_edges"] or nm["bad_verts"]:
        p(0.05, "making it watertight")
        vs = voxel_remesh(obj)
        rep["steps"].append(f"made watertight for remeshing (voxel {U.fmt_len(vs)})")
    recalc_normals(obj)
    limit = max(int(faces) * 6, 15000) if sharp else max(int(faces) * 10, 50000)
    tri = len(obj.data.polygons)
    if tri > limit:
        p(0.1, "pre-reducing")
        decimate(obj, faces=limit, symmetry=None, planar=None, keep_sharp=35.0 if sharp else None, keep_seams=False,
                 untangle=False)
        rep["steps"].append(f"pre-reduced {tri:,} -> {limit:,} triangles first")


def _open_edges(me):
    _s, _t, _lv, le = U.polys(me)
    return int((np.bincount(le, minlength=len(me.edges)) == 1).sum()) if len(le) else 0


def _quadriflow_best(obj, faces, sharp, symmetry, rep, p):
    """Runs QuadriFlow up to 3 times (other seed / corrected target) and keeps the best result: closed (QuadriFlow
    sometimes leaves small holes) and nearest to the face count. Leftover holes are filled."""
    work = obj.data.copy()
    best = None  # (score, mesh)
    target = int(faces)
    sym = symmetry
    try:
        for attempt in range(3):
            if attempt:
                U.replace_mesh(obj, work.copy())
            p(0.25 + 0.2 * attempt, "QuadriFlow" + (f" (try {attempt + 1})" if attempt else ""))
            try:
                n = quadriflow(obj, target, keep_sharp=sharp, symmetry=sym, seed=attempt)
            except RuntimeError as e:
                if sym:  # symmetry fails on slightly asymmetric input: go on without it
                    sym = None
                    rep["steps"].append("QuadriFlow symmetry failed; remeshed without it")
                elif sharp:  # its sharp-edge mode is the fragile part: go on without it (edges are snapped later)
                    sharp = False
                    rep["steps"].append(f"QuadriFlow sharp mode failed ({e}); remeshed without it")
                if attempt == 2 and best is None:
                    raise
                continue
            holes = _open_edges(obj.data)
            off = abs(n - faces) / max(faces, 1)
            score = (holes > 0, off)
            if best is None or score < best[0]:
                if best is not None:
                    bpy.data.meshes.remove(best[1])
                best = (score, obj.data.copy())
            if holes == 0 and off <= 0.12:
                break
            target = max(8, int(target * faces / max(n, 1)))
        U.replace_mesh(obj, best[1])
    finally:
        bpy.data.meshes.remove(work)
    _close_holes(obj, rep, "QuadriFlow")


def _close_holes(obj, rep, who):
    """Remeshers sometimes leave small holes: close them (quads where the fill allows)."""
    if not _open_edges(obj.data):
        return
    bm = U.bm_from(obj)
    res = bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=0)
    new = res.get("faces", [])
    if new:
        tri = bmesh.ops.triangulate(bm, faces=new, quad_method='BEAUTY', ngon_method='BEAUTY')
        bmesh.ops.join_triangles(bm, faces=tri["faces"], angle_face_threshold=math.radians(40),
                                 angle_shape_threshold=math.radians(40))
    U.bm_to(bm, obj)
    rep["steps"].append(f"closed {len(new)} small hole{'s' if len(new) != 1 else ''} {who} left")


def quads(obj, faces, keep_sharp=35.0, symmetry=None, engine="auto", source=None, progress=None, rep=None,
          hard=True):
    """Quad remesh in place with the best available engine. source: object to reproject onto (the dense
    original). hard: the shape is hard-surface (QuadriFlow's own sharp-edge mode is only used then). Returns the
    engine used."""
    from . import external as X
    p = U.Progress(progress)
    rep = rep if rep is not None else {"steps": []}
    eng = X.pick_quad_engine(engine)
    if eng == "instant_meshes":
        p(0.1, "Instant Meshes")
        closed = not _open_edges(obj.data)
        try:
            X.instant_meshes(obj, faces, crease=keep_sharp if keep_sharp else None)
        except X.RemesherTimeout as e:
            rep["steps"].append(f"Instant Meshes stopped answering twice ({e}); used QuadriFlow instead")
            eng = "quadriflow_fallback"
        else:
            if closed:
                _close_holes(obj, rep, "Instant Meshes")
            from .fix import recalc_normals
            recalc_normals(obj)  # its output can have a few faces turned the other way
    if eng == "instant_meshes":
        pass
    elif eng == "quadwild":
        p(0.1, "QuadWild")
        X.quadwild(obj, faces, sharp=keep_sharp)
    elif eng == "qremeshify":
        p(0.1, "QRemeshify")
        X.qremeshify(obj, faces, sharp=keep_sharp, symmetry=symmetry)
    else:
        eng = "quadriflow"
        sharp = bool(keep_sharp) and hard
        _prepare_for_quads(obj, faces, rep, p.sub(0.0, 0.2), sharp)
        _quadriflow_best(obj, faces, sharp, symmetry, rep, p)
    rep["steps"].append(f"{X.ENGINE_NAMES.get(eng, eng)}: {len(obj.data.polygons):,} faces")
    if source is not None:
        p(0.8, "reprojecting")
        reproject(obj, source)
        rep["steps"].append("reprojected onto the original")
        if keep_sharp:
            segs = S.sharp_segments(source, float(keep_sharp) + 10.0, min_chain=0.03)
            size = U.diag(U.world_verts(obj)) or 1.0
            edge = math.sqrt((S.analyze(obj)["area"] or 1.0) / max(len(obj.data.polygons), 1))
            moved = snap_to_sharp(obj, segs, min(edge * 0.5, size * 0.02))
            if moved:
                rep["steps"].append(f"snapped {moved:,} vertices onto sharp edges")
    return eng


def _finish_shading(obj, keep_sharp, hard=False):
    """Smooth shading with crisp edges. Hard-surface low poly also gets weighted normals (bigger faces win), so flat
    sides shade flat instead of smearing dark into their neighbours (custom normals; exports keep them)."""
    me = obj.data
    if keep_sharp:
        U.mark_sharp_by_angle(me, float(keep_sharp), clear=True)
    else:
        U.mark_sharp_by_angle(me, 180.0, clear=True)
    if hard and len(me.polygons):
        mod = obj.modifiers.new("Nighty Weighted Normals", 'WEIGHTED_NORMAL')
        mod.mode = 'FACE_AREA'
        mod.weight = 50
        mod.keep_sharp = True
        mod.thresh = 0.01
        U.apply_modifiers(obj, [mod])


def triangulate_option(obj, triangulate):
    if triangulate == "now":
        bm = U.bm_from(obj)
        bmesh.ops.triangulate(bm, faces=bm.faces, quad_method='BEAUTY', ngon_method='BEAUTY')
        U.bm_to(bm, obj)
        return "triangulated"
    if triangulate == "on_export":
        mod = obj.modifiers.get("Nighty Triangulate") or obj.modifiers.new("Nighty Triangulate", 'TRIANGULATE')
        mod.quad_method = 'BEAUTY'
        mod.ngon_method = 'BEAUTY'
        try:
            mod.keep_custom_normals = True
        except AttributeError:
            pass
        return "Triangulate modifier added (applied on export)"
    return None


def retopo(obj, mode="auto", detail="medium", faces=None, keep_sharp=True, sharp_angle=35.0, engine="auto",
           symmetry="auto", reproject_result=True, keep_source=True, triangulate="keep", progress=None,
           source=None):
    """Retopology of one mesh object, in place.

    mode: 'quads' | 'triangles' (low poly) | 'auto' (quads for organic shapes; for hard-surface it tries quads and
    low poly and keeps the one that holds the shape and sharp edges better, and says why).
    detail: 'low' | 'medium' | 'high' (see DETAIL_TRIANGLES) unless faces (exact count) is given.
    keep_sharp: keep edges sharper than sharp_angle crisp. symmetry: 'auto' | 'x' | 'y' | 'z' | None.
    keep_source: keep the dense original hidden as the bake source. source: an explicit dense object to reproject
    onto (the tools pass the bake source when there is one). triangulate: 'keep' | 'now' | 'on_export'.
    """
    p = U.Progress(progress)
    t0 = time.monotonic()
    U.require_mesh(obj)
    rep = {"object": obj.name, "steps": []}
    old_src = bake_source(obj)
    if old_src is not None and source is None:
        # retopo again: start from the dense original, not from the last result
        U.replace_mesh(obj, old_src.data.copy())
        source = old_src
        rep["steps"].append(f"started again from the dense original ({old_src.name})")
    _s, tot0, _lv, _le = U.polys(obj.data)
    rep["before"] = f"{len(tot0):,} faces"
    cls = SH.classify(obj)
    rep["shape"] = cls["kind"]
    planar = 2.0 if cls["kind"] == "hard_surface" else None
    sharp = float(sharp_angle) if keep_sharp else None
    if symmetry == "auto":
        axes = SH.symmetry(obj)
        symmetry = axes[0] if axes else None
    if symmetry:
        rep["steps"].append(f"mirror-symmetric on {symmetry.upper()}")
    # the dense original: kept hidden for baking, used for reprojection
    made_src = None
    if source is None:
        if keep_source:
            source = made_src = keep_bake_source(obj)
        elif reproject_result:
            source = made_src = bpy.data.objects.new(obj.name + "_tmp_src", obj.data.copy())
            source.matrix_world = obj.matrix_world.copy()
            bpy.context.scene.collection.objects.link(source)
    want = mode
    if mode == "auto":
        want = "quads" if cls["kind"] == "organic" else "compare"
    src_for_reproject = source if reproject_result else None
    if want == "compare":
        rep["steps"].append(cls["why"])
        tri_target = int(faces) if faces else detail_faces(detail, "triangles")
        quad_target = int(faces) // 2 if faces else detail_faces(detail, "quads")
        base = obj.data.copy()
        ref = S.sharp_segments(source, sharp or 35.0, min_chain=0.03)  # the real creases (noise dropped)
        p(0.05, "trying quads")
        q_rep = {"steps": []}
        try:
            eng = quads(obj, quad_target, keep_sharp=sharp, symmetry=symmetry, engine=engine,
                        source=src_for_reproject, progress=p.sub(0.05, 0.5), rep=q_rep, hard=True)
            q_mesh = obj.data.copy()
            q_err = S.surface_error(obj, source)
            q_sharp = S.sharp_kept(ref, obj, sharp or 35.0) if sharp else 1.0
        except Exception as e:  # noqa: BLE001 - any remesher failure just means "use low poly"
            q_mesh, q_err, q_sharp, eng = None, {"mean": 1.0}, 0.0, None
            rep["steps"].append(f"quads failed ({e}); using low poly")
        p(0.55, "trying low poly")
        U.replace_mesh(obj, base.copy())
        d_rep = decimate(obj, faces=tri_target, symmetry=symmetry, planar=planar, keep_sharp=sharp or 35.0,
                         progress=p.sub(0.55, 0.85))
        d_err = S.surface_error(obj, source)
        d_sharp = S.sharp_kept(ref, obj, sharp or 35.0) if sharp else 1.0
        bpy.data.meshes.remove(base)
        use_quads = q_mesh is not None and q_err["mean"] <= d_err["mean"] * 1.6 + 0.0005 and q_sharp >= d_sharp - 0.12
        if use_quads:
            U.replace_mesh(obj, q_mesh)
            rep["steps"] += q_rep["steps"]
            rep["result"] = "quads"
            rep["why"] = (f"{cls['kind'].replace('_', '-')}; quads kept the shape (error {q_err['mean'] * 100:.2f}% "
                          f"vs {d_err['mean'] * 100:.2f}%) and {round(q_sharp * 100)}% of sharp edges")
        else:
            if q_mesh is not None:
                bpy.data.meshes.remove(q_mesh)
            rep["steps"] += d_rep["steps"]
            rep["result"] = "triangles"
            reason = []
            if q_mesh is not None and q_sharp < d_sharp - 0.12:
                reason.append(f"quads rounded the sharp edges ({round(q_sharp * 100)}% kept vs {round(d_sharp * 100)}%)")
            if q_mesh is not None and q_err["mean"] > d_err["mean"] * 1.6 + 0.0005:
                reason.append(f"quads drifted from the shape ({q_err['mean'] * 100:.2f}% vs {d_err['mean'] * 100:.2f}%)")
            rep["why"] = "hard-surface; low poly kept it crisper: " + ("; ".join(reason) or "quads failed")
        rep["engine"] = eng if use_quads else "decimate"
    elif want == "quads":
        if mode == "auto":
            rep["why"] = cls["why"] + " -> quads"
        target = int(faces) if faces else detail_faces(detail, "quads")
        eng = quads(obj, target, keep_sharp=sharp, symmetry=symmetry, engine=engine, source=src_for_reproject,
                    progress=p.sub(0.0, 0.9), rep=rep, hard=cls["kind"] == "hard_surface")
        rep["result"] = "quads"
        rep["engine"] = eng
    else:
        target = int(faces) if faces else detail_faces(detail, "triangles")
        d_rep = decimate(obj, faces=target, symmetry=symmetry, planar=planar, keep_sharp=sharp or False,
                         progress=p.sub(0.0, 0.9))
        rep["steps"] += d_rep["steps"]
        rep["result"] = "triangles"
        rep["engine"] = "decimate"
    _finish_shading(obj, sharp, hard=cls["kind"] == "hard_surface")
    t = triangulate_option(obj, triangulate)
    if t:
        rep["steps"].append(t)
    if made_src is not None and not keep_source:
        bpy.data.objects.remove(made_src)
        source = None
    st = S.analyze(obj)
    rep["after"] = S.short(st)
    rep["faces"] = st["faces"]
    rep["triangles"] = st["triangles"]
    rep["quad_ratio"] = st["quad_ratio"]
    rep["manifold"] = st["manifold"]
    if source is not None:
        rep["error"] = S.surface_error(obj, source)
        rep["bake_source"] = source.name if keep_source else None
    rep["seconds"] = round(time.monotonic() - t0, 2)
    p(1.0, "done")
    return rep
