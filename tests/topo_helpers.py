# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared test helpers (run inside Blender by tests/run.py): Skip, checks, and synthetic messy meshes like the ones
image -> 3D generators make."""

import math
import os
import random
import tempfile

import bmesh
import bpy
import numpy as np
from mathutils import Vector, noise


class Skip(Exception):
    """Raise to skip a test (with the reason)."""


def check(cond, msg="check failed"):
    if not cond:
        raise AssertionError(msg)


def near(a, b, tol, msg=""):
    if abs(a - b) > tol:
        raise AssertionError(f"{msg} {a} != {b} (tol {tol})".strip())


def scratch_dir():
    d = os.environ.get("NIGHTY_TEST_OUT") or os.path.join(tempfile.gettempdir(), "nighty-tests")
    os.makedirs(d, exist_ok=True)
    return d


def link(obj):
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    return obj


def obj_from_bm(name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return link(bpy.data.objects.new(name, me))


def _voxelize(obj, voxel):
    mod = obj.modifiers.new("v", 'REMESH')
    mod.mode = 'VOXEL'
    mod.voxel_size = voxel
    mod.adaptivity = 0.0
    dg = bpy.context.evaluated_depsgraph_get()
    new = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    obj.modifiers.remove(mod)
    old = obj.data
    obj.data = new
    bpy.data.meshes.remove(old)


def _soup(obj, jitter, seed, delete_spots=0, spot_radius=0.0):
    """Triangulates, jitters, cuts holes, and unwelds every face (triangle soup) like raw generator output."""
    rnd = random.Random(seed)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    for v in bm.verts:
        v.co += Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1))) * jitter
    if delete_spots:
        faces = list(bm.faces)
        for _ in range(delete_spots):
            c = rnd.choice(faces).calc_center_median()
            gone = [f for f in bm.faces if (f.calc_center_median() - c).length < spot_radius]
            bmesh.ops.delete(bm, geom=gone, context='FACES_ONLY')
    bmesh.ops.split_edges(bm, edges=bm.edges)  # every triangle on its own vertices
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def noisy_sphere(name="Blob", radius=0.5, voxel=0.012, floaters=6, holes=3, seed=3):
    """An organic blob like a marching-cubes generator output: bumpy, dense triangle soup with floaters and holes."""
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=5, radius=radius)
    for v in bm.verts:
        n = v.co.normalized()
        v.co = n * radius * (1.0 + 0.12 * noise.noise(n * 2.2) + 0.04 * noise.noise(n * 6.0))
    obj = obj_from_bm(name, bm)
    _voxelize(obj, voxel)
    rnd = random.Random(seed)
    if floaters:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        for i in range(floaters):
            d = Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1))).normalized()
            r = rnd.uniform(0.004, 0.012)
            m = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r)
            off = d * radius * rnd.uniform(1.15, 1.4)
            bmesh.ops.translate(bm, verts=m["verts"], vec=off)
        bm.to_mesh(obj.data)
        bm.free()
    _soup(obj, voxel * 0.15, seed, delete_spots=holes, spot_radius=voxel * 2.5)
    return obj


# A rifle-like side silhouette (x forward, z up) in meters: stock, receiver, slanted grip.
RIFLE_PROFILE = [(-0.45, 0.10), (-0.45, 0.22), (-0.20, 0.20), (-0.15, 0.24), (0.25, 0.24), (0.25, 0.14),
                 (0.02, 0.14), (-0.02, 0.02), (-0.09, 0.02), (-0.06, 0.14), (-0.20, 0.14)]
RIFLE_HALF_THICK = 0.025
BARREL = {"x0": 0.24, "x1": 0.60, "z": 0.20, "r": 0.02}


def prism(name, profile=RIFLE_PROFILE, half=RIFLE_HALF_THICK):
    """The clean, sharp-edged extruded silhouette (ground truth for sharp edges)."""
    bm = bmesh.new()
    a = [bm.verts.new((x, -half, z)) for x, z in profile]
    b = [bm.verts.new((x, half, z)) for x, z in profile]
    n = len(profile)
    bm.faces.new(list(reversed(a)))
    bm.faces.new(b)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((a[i], a[j], b[j], b[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return obj_from_bm(name, bm)


def barrel(name, segs=48):
    bm = bmesh.new()
    res = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segs, radius1=BARREL["r"],
                                radius2=BARREL["r"], depth=BARREL["x1"] - BARREL["x0"])
    rot = __import__("mathutils").Matrix.Rotation(math.pi / 2, 4, 'Y')
    bmesh.ops.transform(bm, matrix=rot, verts=bm.verts)
    bmesh.ops.translate(bm, verts=bm.verts, vec=((BARREL["x0"] + BARREL["x1"]) / 2, 0, BARREL["z"]))
    return obj_from_bm(name, bm)


def hard_surface(name="Rifle", voxel=0.004, jitter=0.0006, seed=5, soup=True):
    """A dense scanned-like hard-surface shape: the rifle silhouette + barrel, voxel-fused into one dense
    triangulated shell with slight noise. Returns (obj, ground-truth sharp segments (k, 2, 3))."""
    body = prism(name)
    gt = list(_segments(body, 35.0))
    bar = barrel(name + "_barrel")
    # barrel sharp circles that stay outside the body: the front cap and the junction ring at the receiver face
    r, z = BARREL["r"], BARREL["z"]
    for x in (0.25, BARREL["x1"]):
        k = 64
        for i in range(k):
            t0, t1 = 2 * math.pi * i / k, 2 * math.pi * (i + 1) / k
            gt.append(((x, r * math.sin(t0), z + r * math.cos(t0)), (x, r * math.sin(t1), z + r * math.cos(t1))))
    # join + voxel = a fused union
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.from_mesh(bar.data)
    bm.to_mesh(body.data)
    bm.free()
    bpy.data.objects.remove(bar)
    _voxelize(body, voxel)
    if soup:
        _soup(body, jitter, seed)
    return body, np.array(gt, dtype=np.float64)


def _segments(obj, angle):
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    out = []
    for e in bm.edges:
        if len(e.link_faces) == 2 and math.degrees(e.calc_face_angle()) > angle:
            out.append((tuple(e.verts[0].co), tuple(e.verts[1].co)))
    bm.free()
    return out


def rifle_parts(name="Kit"):
    """Separate loose parts (body, barrel, scope) in one object, plus two materials."""
    body = prism(name)
    bar = barrel(name + "_b")
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=0.025, radius2=0.025, depth=0.22)
    bmesh.ops.transform(bm, matrix=__import__("mathutils").Matrix.Rotation(math.pi / 2, 4, 'Y'), verts=bm.verts)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(0.02, 0, 0.29))
    scope = obj_from_bm(name + "_s", bm)
    m1 = bpy.data.materials.new("Metal")
    m2 = bpy.data.materials.new("Polymer")
    body.data.materials.append(m2)
    body.data.materials.append(m1)
    bm = bmesh.new()
    bm.from_mesh(body.data)
    for o in (bar, scope):
        o2 = bmesh.new()
        o2.from_mesh(o.data)
        for f in o2.faces:
            f.material_index = 1
        tmp = bpy.data.meshes.new("tmp")
        o2.to_mesh(tmp)
        o2.free()
        bm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
        bpy.data.objects.remove(o)
    bm.to_mesh(body.data)
    bm.free()
    return body


def render(objs, path, wire=True, res=640, color="OBJECT"):
    """Quick workbench render (front 3/4 view) for looking at results by eye."""
    sc = bpy.context.scene
    try:
        sc.render.engine = 'BLENDER_WORKBENCH'
    except TypeError:
        pass
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.film_transparent = False
    sh = sc.display.shading
    sh.light = 'STUDIO'
    sh.color_type = color
    sh.show_cavity = False
    pts = []
    for o in objs:
        for c in o.bound_box:
            pts.append(o.matrix_world @ Vector(c))
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    ctr, size = (lo + hi) / 2, (hi - lo).length
    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = size * 1.05
    cam = bpy.data.objects.new("cam", cam_data)
    sc.collection.objects.link(cam)
    d = Vector((1.0, -1.6, 0.9)).normalized()
    cam.location = ctr + d * size * 2
    cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    sc.camera = cam
    added = []
    if wire:  # a dark wire-only twin of every object
        for o in objs:
            w = bpy.data.objects.new(o.name + "_wire", o.data)
            w.matrix_world = o.matrix_world
            m = w.modifiers.new("wire", 'WIREFRAME')
            m.thickness = size * 0.0015
            m.use_replace = True
            m.use_even_offset = False
            w.color = (0.05, 0.06, 0.08, 1)
            sc.collection.objects.link(w)
            added.append(w)
    hidden = [o for o in sc.objects if o not in objs and o not in added and o.type == 'MESH' and not o.hide_render]
    for o in hidden:
        o.hide_render = True
    palette = [(0.75, 0.78, 0.82, 1), (0.85, 0.45, 0.35, 1), (0.4, 0.7, 0.45, 1), (0.4, 0.5, 0.85, 1),
               (0.85, 0.75, 0.3, 1), (0.65, 0.4, 0.8, 1)]
    for i, o in enumerate(objs):
        o.color = palette[i % len(palette)] if len(objs) > 1 else palette[0]
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    for o in hidden:
        o.hide_render = False
    for w in added:
        bpy.data.objects.remove(w)
    bpy.data.objects.remove(cam)
    return path


def xatlas_dir():
    """A folder with the xatlas module for this Python, unpacked from the wheels the extension ships (tests run from
    the repo, where Blender has not installed them). None when no wheel fits."""
    import sys
    import zipfile
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wheels = os.path.join(here, "addon", "nighty_blender", "wheels")
    tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    plat = {"win32": "win_amd64", "darwin": "macosx", "linux": "manylinux"}.get(sys.platform, "?")
    for name in sorted(os.listdir(wheels)) if os.path.isdir(wheels) else []:
        if f"-{tag}-" in name and plat in name:
            out = os.path.join(scratch_dir(), "xatlas-" + tag)
            if not os.path.isdir(out):
                with zipfile.ZipFile(os.path.join(wheels, name)) as z:
                    z.extractall(out)
            return out
    return None


def crossing_pairs(obj):
    """Pairs of faces that pass through each other (sharing a vertex does not count; same test as nighty.check)."""
    from mathutils.bvhtree import BVHTree
    me = obj.data
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    co = np.zeros(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    tris = np.zeros(n * 3, dtype=np.int32)
    me.loop_triangles.foreach_get("vertices", tris)
    tris = tris.reshape(-1, 3).astype(np.int64)
    poly = np.zeros(n, dtype=np.int32)
    me.loop_triangles.foreach_get("polygon_index", poly)
    tree = BVHTree.FromPolygons(co.tolist(), tris.tolist(), all_triangles=True)
    p = np.array(tree.overlap(tree), dtype=np.int64).reshape(-1, 2)
    p = p[p[:, 0] < p[:, 1]]
    a, b = tris[p[:, 0]], tris[p[:, 1]]
    keep = ~(a[:, :, None] == b[:, None, :]).any(axis=(1, 2)) & (poly[p[:, 0]] != poly[p[:, 1]])
    a, b = a[keep], b[keep]
    if not len(a):
        return 0
    tol = float(np.linalg.norm(co.max(0) - co.min(0))) * 1e-6

    def straddles(t, o):
        o0, o1, o2 = co[o[:, 0]], co[o[:, 1]], co[o[:, 2]]
        nrm = np.cross(o1 - o0, o2 - o0)
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-30)
        d = np.einsum("ijk,ik->ij", co[t] - o0[:, None, :], nrm)
        return (d > tol).any(axis=1) & (d < -tol).any(axis=1)
    return int((straddles(a, b) & straddles(b, a)).sum())
