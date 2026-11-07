# SPDX-License-Identifier: GPL-3.0-or-later
# Topology tests (b-topo): cleanup, retopo (quads / low poly / auto), parts, UVs, LODs, the background worker and the
# six tools, on synthetic messy meshes like image -> 3D generators make. Every test starts from an empty scene.

import json
import math
import os
import sys
import time

import bpy
import numpy as np

import topo_helpers as H
from nighty_blender.nighty import mesh as nm
from nighty_blender.nighty.mesh import external as X
from nighty_blender.nighty.mesh import worker as W

TIMES = {}
FRESH_SCENE = True  # main's tests/run.py gives every test an empty scene (these tests also reset it themselves)


def _fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _timed(label, fn):
    t0 = time.monotonic()
    out = fn()
    TIMES[label] = round(time.monotonic() - t0, 2)
    print(f"    time {label}: {TIMES[label]} s")
    return out


def _rifle_clean():
    """The dense hard-surface rifle after cleanup, and its ground-truth sharp edges moved along with it."""
    hs, gt = H.hard_surface()
    lo0 = np.min([v.co[:] for v in hs.data.vertices], axis=0)
    nm.cleanup(hs)
    lo1 = nm.analyze(hs)["min"]
    return hs, gt + (np.array(lo1) - lo0)


def _copy(obj, name):
    o = obj.copy()
    o.data = obj.data.copy()
    o.name = name
    bpy.context.scene.collection.objects.link(o)
    return o


# ---------------------------------------------------------------- cleanup

def test_cleanup_generated_blob():
    _fresh()
    ob = H.noisy_sphere()
    ob.rotation_euler = (0.3, 0.2, 0.5)
    ob.scale = (2.0, 2.0, 2.0)
    ob.location = (1, 2, 3)
    before = nm.analyze(ob)
    H.check(before["parts"] > 1000 and not before["manifold"], "the test blob should start as raw triangle soup")
    rep = _timed("cleanup 69k-tri blob", lambda: nm.cleanup(ob, size=1.2, size_axis="height"))
    st = nm.analyze(ob)
    H.check(st["manifold"], f"not manifold: {st}")
    H.check(st["parts"] == 1, f"floaters left: {st['parts']} parts")
    H.check(st["boundary_edges"] == 0 and st["flipped_edges"] == 0, "holes or flipped normals left")
    H.near(st["size"][2], 1.2, 1e-3, "height")
    H.near(st["min"][2], 0.0, 1e-4, "on the ground")
    co = np.array([v.co[:] for v in ob.data.vertices])
    H.near(co[:, 2].min(), 0.0, 1e-5, "origin at the bottom")
    H.near((co[:, 0].min() + co[:, 0].max()) / 2, 0.0, 1e-5, "origin centered x")
    H.near((co[:, 1].min() + co[:, 1].max()) / 2, 0.0, 1e-5, "origin centered y")
    H.check(tuple(ob.scale) == (1.0, 1.0, 1.0) and tuple(ob.rotation_euler) == (0.0, 0.0, 0.0), "transforms applied")
    steps = " | ".join(rep["steps"])
    H.check("removed 6 floaters" in steps and "filled" in steps and "voxel" not in steps, steps)
    H.check(not st["normals_inward"], "normals point inward")


def test_cleanup_voxel_rebuild_for_bad_geometry():
    _fresh()
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.edges.ensure_lookup_table()
    e = bm.edges[0]
    v = bm.verts.new(e.verts[0].co * 0.5 + e.verts[1].co * 0.5 + e.verts[0].co.normalized() * 0.8)
    bm.faces.new((e.verts[0], e.verts[1], v))  # a fin: three faces on one edge
    ob = H.obj_from_bm("Fin", bm)
    H.check(nm.analyze(ob)["non_manifold_edges"] >= 1, "test mesh should be non-manifold")
    rep = nm.cleanup(ob, floaters=None)
    st = nm.analyze(ob)
    H.check(st["manifold"], f"still not manifold: {st}")
    H.check(any("rebuilt watertight" in s for s in rep["steps"]), rep["steps"])


# ---------------------------------------------------------------- shape

def test_classify_and_symmetry():
    _fresh()
    blob = H.noisy_sphere()
    nm.cleanup(blob)
    rifle, _gt = _rifle_clean()
    c1, c2 = nm.classify(blob), nm.classify(rifle)
    H.check(c1["kind"] == "organic", f"blob: {c1}")
    H.check(c2["kind"] == "hard_surface", f"rifle: {c2}")
    H.check(c1["why"] and c2["why"], "a reason is given")
    H.check("y" in nm.symmetry(rifle), "the rifle is mirror-symmetric on Y")
    H.check(nm.symmetry(blob) == [], "the blob is not symmetric")


# ---------------------------------------------------------------- retopo

def test_retopo_quads_organic():
    _fresh()
    ob = H.noisy_sphere()
    nm.cleanup(ob)
    rep = _timed("quads 2000 on blob (QuadriFlow)", lambda: nm.retopo(ob, mode="quads", faces=2000,
                                                                     engine="quadriflow"))
    st = nm.analyze(ob)
    H.check(abs(st["faces"] - 2000) <= 300, f"face count {st['faces']}")
    H.check(st["quad_ratio"] >= 0.95, f"quads {st['quad_ratio']}")
    H.check(st["manifold"], "manifold")
    H.check(rep["error"]["mean"] < 0.003, f"shape error {rep['error']}")
    src = nm.bake_source(ob)
    H.check(src is not None and src.hide_render and src.get("nighty_role") == "bake_source", "bake source kept")
    H.check(len(src.data.polygons) > 60000, "bake source is the dense original")
    H.check(rep["engine"] == "quadriflow", rep)


def test_retopo_triangles_exact_count_keeps_sharp():
    _fresh()
    rifle, gt = _rifle_clean()
    rep = _timed("low poly 5000 on rifle", lambda: nm.retopo(rifle, mode="triangles", faces=5000))
    st = nm.analyze(rifle)
    H.check(abs(st["faces"] - 5000) <= 4 and st["tris"] == st["faces"], f"{st['faces']} faces")
    H.check(st["manifold"], "manifold")
    kept = nm.sharp_kept(gt, rifle, tol=0.006)
    print(f"    sharp edges kept (low poly 5000): {kept}")
    H.check(kept >= 0.9, f"sharp edges kept {kept}")
    H.check(rep["error"]["mean"] < 0.002, rep["error"])
    H.check(rifle.data.has_custom_normals, "hard-surface low poly gets weighted normals")


def test_retopo_quads_hard_surface():
    _fresh()
    rifle, gt = _rifle_clean()
    rep = _timed("quads 3000 on rifle", lambda: nm.retopo(rifle, mode="quads", faces=3000, symmetry=None))
    st = nm.analyze(rifle)
    H.check(st["quad_ratio"] >= 0.95, f"quads {st['quad_ratio']}")
    H.check(abs(st["faces"] - 3000) <= 450, f"face count {st['faces']}")
    H.check(st["manifold"], "manifold")
    kept = nm.sharp_kept(gt, rifle, tol=0.006)
    print(f"    sharp edges kept (quads 3000): {kept}; steps {rep['steps']}")
    H.check(kept >= 0.8, f"sharp edges kept {kept}")
    H.check(st["marked_sharp"] > 0, "sharp edges marked for shading")


def test_retopo_auto_picks_and_explains():
    _fresh()
    blob = H.noisy_sphere()
    nm.cleanup(blob)
    r1 = nm.retopo(blob, mode="auto", detail="low")
    H.check(r1["result"] == "quads" and "organic" in r1["why"], r1)
    H.near(r1["faces"], nm.detail_faces("low", "quads"), 300, "low detail quads")
    rifle, _gt = _rifle_clean()
    r2 = _timed("auto on rifle", lambda: nm.retopo(rifle, mode="auto", detail="low"))
    print(f"    auto on rifle -> {r2['result']}: {r2['why']}")
    H.check(r2["result"] in ("quads", "triangles") and "hard-surface" in r2["why"], r2)
    H.check(nm.analyze(rifle)["manifold"], "manifold")


def test_retopo_again_starts_from_original():
    _fresh()
    ob = H.noisy_sphere()
    nm.cleanup(ob)
    nm.retopo(ob, mode="quads", faces=1500)
    rep = nm.retopo(ob, mode="triangles", faces=800)
    H.check(any("dense original" in s for s in rep["steps"]), rep["steps"])
    H.check(abs(nm.analyze(ob)["faces"] - 800) <= 4, "second target")
    H.check(sum(1 for o in bpy.data.objects if o.get("nighty_role") == "bake_source") == 1, "one bake source")


def test_decimate_keeps_symmetry():
    _fresh()
    rifle, _gt = _rifle_clean()
    rep = nm.decimate(rifle, faces=3000, symmetry="auto")
    H.check(any("symmetric on y" in s.lower() for s in rep["steps"]), rep["steps"])
    H.check(abs(rep["triangles"] - 3000) <= 4, rep)
    H.check("y" in nm.symmetry(rifle), "still symmetric after decimate")


# ---------------------------------------------------------------- parts

def test_split_parts_methods():
    _fresh()
    kit = H.rifle_parts()
    k2 = _copy(kit, "Kit2")
    parts, rep = nm.split_parts(kit, method="auto", names=["receiver", "barrel", "scope"])
    H.check(rep["method"] == "loose" and len(parts) == 3, rep)
    names = sorted(p.name for p in parts)
    H.check(names == ["Kit_barrel", "Kit_receiver", "Kit_scope"], names)
    H.check("Kit" not in bpy.data.objects, "original removed")
    for p in parts:
        H.check(nm.analyze(p)["manifold"], f"{p.name} manifold")
        H.check(len(p.data.materials) == 2, "materials kept")
    bar = bpy.data.objects["Kit_barrel"]
    row = next(r for r in rep["parts"] if r["name"] == "Kit_barrel")
    H.check(row["form"].startswith("long"), row)
    mats, rep2 = nm.split_parts(k2, method="material")
    H.check(len(mats) == 2, rep2)
    del bar
    # a cut plane through the fused rifle: two closed halves
    rifle, _gt = _rifle_clean()
    halves, rep3 = nm.split_parts(rifle, method="plane", planes=[{"point": [0, 0, 0], "normal": [1, 0, 0]}])
    H.check(len(halves) == 2, rep3)
    for h in halves:
        H.check(nm.analyze(h)["manifold"], f"{h.name}: cut not capped")


def test_split_parts_concave_and_attribute():
    _fresh()
    rifle, _gt = _rifle_clean()
    r2 = _copy(rifle, "Rifle2")
    parts, rep = nm.split_parts(rifle, method="concave", angle=30, min_size=0.02)
    print(f"    concave split: {[(r['name'], r['form'], r['where']) for r in rep['parts']]}")
    # the barrel goes into the receiver at a concave ring: it comes off as a long part (the grip shares its flat
    # sides with the body in this extruded test shape, so it stays on)
    H.check(len(parts) >= 2, f"{len(parts)} parts")
    barrel = [r for r in rep["parts"] if r["form"] == "long"]
    H.check(len(barrel) == 1 and barrel[0]["center"][0] > 0.3 and "right" in barrel[0]["where"], rep["parts"])
    # labels an AI segmenter wrote as a face attribute
    me = r2.data
    att = me.attributes.new("nighty_part", 'INT', 'FACE')
    cx = np.array([p.center.x for p in me.polygons])
    att.data.foreach_set("value", (cx > 0.25).astype(np.int32))
    r2["nighty_part_names"] = {"0": "body", "1": "barrel"}
    parts2, rep2 = nm.split_parts(r2, method="attribute")
    H.check(sorted(p.name for p in parts2) == ["Rifle2_barrel", "Rifle2_body"], rep2)
    # the engine's hook
    nm.register_segmenter("halves", lambda o: ((np.array([p.center.z for p in o.data.polygons]) > 0.15).astype(int), None))
    H.check("halves" in nm.segmenters(), "segmenter registered")


# ---------------------------------------------------------------- UVs

def test_uv_unwrap_shared_atlas_no_overlap():
    _fresh()
    kit = H.rifle_parts()
    parts, _rep = nm.split_parts(kit, method="loose")
    rep = _timed("uv 3 parts", lambda: nm.uv_unwrap(parts, texture_size="2K"))
    r = rep["report"]
    print(f"    uv: overlap_px {r['overlap_px']}, coverage {r['coverage']}, texel spread {r['texel_spread']}")
    H.check(r["overlap_px"] == 0 and r["folded_faces"] == 0, f"overlap {r}")
    H.check(r["texel_spread"] <= 1.15, f"texel density differs between parts: {r['texel_spread']}")
    H.check(r["coverage"] >= 0.25, f"atlas mostly empty: {r['coverage']}")
    H.check(rep["margin_px"] == 12, rep)
    for row in r["objects"]:
        H.check(row["uv_area"] > 0 and row["islands"] >= 1, row)


def test_uv_unwrap_retopo_results():
    _fresh()
    blob = H.noisy_sphere()
    nm.cleanup(blob)
    nm.retopo(blob, mode="quads", faces=1500)
    rifle, _gt = _rifle_clean()
    nm.retopo(rifle, mode="triangles", faces=4000)
    rep = _timed("uv blob + rifle", lambda: nm.uv_unwrap([blob, rifle], texture_size=1024))
    r = rep["report"]
    print(f"    uv: {rep['objects']}; overlap_px {r['overlap_px']}, spread {r['texel_spread']}")
    H.check(r["overlap_px"] == 0 and r["folded_faces"] == 0, f"overlap {r}")
    H.check(r["texel_spread"] <= 1.15, f"texel spread {r['texel_spread']}")
    H.check(2 <= rep["margin_px"] <= 8, rep)  # 8 px at 1K, less when there are hundreds of islands


# ---------------------------------------------------------------- LODs

def test_make_lods():
    _fresh()
    rifle, _gt = _rifle_clean()
    nm.retopo(rifle, mode="triangles", faces=6000)
    nm.uv_unwrap([rifle], texture_size=1024)
    lods, rep = _timed("lods", lambda: nm.make_lods(rifle, ratios=[0.5, 0.25, 0.1]))
    tris = [r["triangles"] for r in rep["lods"]]
    H.check(tris[0] == 6000, tris)
    for got, want in zip(tris[1:], (3000, 1500, 600)):
        H.check(abs(got - want) <= 4, tris)
    H.check([o.name for o in lods] == ["Rifle_LOD1", "Rifle_LOD2", "Rifle_LOD3"], [o.name for o in lods])
    for o in lods:
        H.check(len(o.data.uv_layers) == 1 and o.hide_get(), "UVs kept, hidden")
        H.check(nm.analyze(o)["manifold"], f"{o.name} manifold")
    lods2, _ = nm.make_lods(rifle, ratios=[0.5])  # again: replaces the old ones
    H.check("Rifle_LOD2" not in bpy.data.objects and lods2[0].name == "Rifle_LOD1", "old LODs replaced")


# ---------------------------------------------------------------- engines

def test_engines_and_instant_meshes_plumbing():
    _fresh()
    eng = X.engines()
    H.check(eng["quadriflow"]["available"], eng)
    H.check(X.pick_quad_engine("quadriflow") == "quadriflow", "quadriflow pick")
    if not eng["instant_meshes"]["available"]:
        try:
            X.pick_quad_engine("instant_meshes")
            raise AssertionError("should refuse when Instant Meshes is missing")
        except ValueError as e:
            H.check("Instant Meshes" in str(e), str(e))
    # a stand-in program with Instant Meshes' command line: checks the OBJ export / run / import path
    import tempfile
    fake = os.path.join(tempfile.mkdtemp(prefix="nighty-im-fake-"), "fake_instant_meshes.py")  # own folder per run
    with open(fake, "w", encoding="utf-8") as f:
        f.write(
            "import sys\n"
            "a = sys.argv[1:]\n"
            "src, out = a[0], a[a.index('-o') + 1]\n"
            "assert a[a.index('-r') + 1] == '4' and a[a.index('-p') + 1] == '4' and '-f' in a\n"
            "v = [l for l in open(src) if l.startswith('v ')]\n"
            "f = [l for l in open(src) if l.startswith('f ')]\n"
            "open(out, 'w').write(''.join(v) + ''.join(f))\n")
    ob = H.noisy_sphere(floaters=0, holes=0)
    nm.cleanup(ob)
    n = len(ob.data.polygons)
    X.instant_meshes(ob, 1000, crease=35, exe=[sys.executable, fake])
    H.check(len(ob.data.polygons) == n and nm.analyze(ob)["manifold"], "round trip through the OBJ files")


def test_xatlas_uvs_on_low_poly():
    """xatlas (shipped as wheels) charts a generated-style low poly in fewer, bigger islands; it runs in Blender's
    python.exe, never imported inside Blender."""
    _fresh()
    from nighty_blender.nighty.mesh import xa
    old = os.environ.get("NIGHTY_XATLAS_DIR")
    if not xa.available():
        d = H.xatlas_dir()
        if d is None:
            print("    skip: no xatlas wheel for this system")
            return
        os.environ["NIGHTY_XATLAS_DIR"] = d
    try:
        rifle, _gt = _rifle_clean()
        nm.retopo(rifle, mode="triangles", faces=4000)
        r2 = _copy(rifle, "Rifle2")
        r2.location.x += 1.5
        rep = _timed("uv xatlas 2 x 4000 tris", lambda: nm.uv_unwrap([rifle, r2], texture_size="2K"))
        r = rep["report"]
        print(f"    xatlas: {rep['objects']}, islands {[o['islands'] for o in r['objects']]}, coverage {r['coverage']}")
        H.check([o["method"] for o in rep["objects"]] == ["xatlas", "xatlas"], rep)
        H.check(r["overlap_px"] == 0 and r["folded_faces"] == 0, r)
        H.check(r["texel_spread"] <= 1.1, r)
        H.check(all(o["islands"] < 400 for o in r["objects"]), r)
        H.check("xatlas" not in sys.modules, "xatlas must never be imported inside Blender")
        smart = _copy(rifle, "Rifle3")
        rs = nm.uv_unwrap([smart], texture_size="2K", method="smart")["report"]
        H.check(r["objects"][0]["islands"] < rs["objects"][0]["islands"], ("fewer islands than Smart UV Project", r, rs))
    finally:
        if old is None:
            os.environ.pop("NIGHTY_XATLAS_DIR", None)
        else:
            os.environ["NIGHTY_XATLAS_DIR"] = old


def test_instant_meshes_download_is_hash_checked():
    """The add-on's own downloader (the plugin's Get Instant Meshes button does the same in Nighty Vault): the offer,
    then download, SHA-256 check, unpack, check again (a local server with a stand-in build)."""
    _fresh()
    import hashlib
    import http.server
    import io
    import threading
    import zipfile
    from nighty_blender.nighty.mesh import external as X
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="nighty-im-setup-")   # its own folder: suites running side by side never share it
    exe_bytes = b"MZ stand-in instant meshes" * 100
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Instant Meshes.exe", exe_bytes)
    blob = buf.getvalue()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/im.zip"
    key = X._platform_key()
    saved = dict(X.INSTANT_MESHES_DOWNLOAD[key])
    old_env = {k: os.environ.get(k) for k in ("NIGHTY_TOOLS_DIR", "NIGHTY_INSTANT_MESHES")}
    os.environ["NIGHTY_TOOLS_DIR"] = tmp
    os.environ.pop("NIGHTY_INSTANT_MESHES", None)
    try:
        H.check(saved.get("sha256") and saved.get("exe_sha256"), "the real build is pinned")
        X.INSTANT_MESHES_DOWNLOAD[key].update(
            url=url, size=len(blob), sha256=hashlib.sha256(blob).hexdigest(), exe="Instant Meshes.exe",
            exe_size=len(exe_bytes), exe_sha256=hashlib.sha256(exe_bytes).hexdigest())
        offer = X.instant_meshes_offer()
        H.check("OK to download" in offer["ask"] and os.path.normpath(offer["folder"]).startswith(
            os.path.normpath(tmp)), offer)
        H.check(not os.path.exists(X.instant_meshes_path()), "nothing downloaded without a yes")
        path = X.install_instant_meshes(url=url, check=lambda u: True)
        H.check(os.path.isfile(path) and open(path, "rb").read() == exe_bytes, path)
        H.check(os.path.isfile(os.path.join(os.path.dirname(path), "SOURCE.txt")), "source note")
        os.remove(path)
        X.INSTANT_MESHES_DOWNLOAD[key]["sha256"] = "0" * 64  # a changed file on the server is refused
        try:
            X.install_instant_meshes(url=url, check=lambda u: True)
            raise AssertionError("a wrong SHA-256 must be refused")
        except Exception as e:  # noqa: BLE001
            H.check("sha" in str(e).lower() or "match" in str(e).lower() or "hash" in type(e).__name__.lower(), repr(e))
        H.check(not os.path.exists(path), "nothing kept after a hash mismatch")
    finally:
        X.INSTANT_MESHES_DOWNLOAD[key].clear()
        X.INSTANT_MESHES_DOWNLOAD[key].update(saved)
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        srv.shutdown()


def test_instant_meshes_real_build():
    """With the real, pinned Instant Meshes (installed by the plugin, or given by NIGHTY_INSTANT_MESHES):
    clean quads near the asked count, closed, close to the shape."""
    _fresh()
    from nighty_blender.nighty.mesh import external as X
    exe = X.find_instant_meshes()
    pins = X.INSTANT_MESHES_DOWNLOAD[X._platform_key()]
    if not exe or not isinstance(exe, str) or not os.path.isfile(exe) or X._sha256(exe) != pins.get("exe_sha256"):
        print("    skip: the pinned Instant Meshes build is not installed here")
        return
    ob = H.noisy_sphere()
    nm.cleanup(ob)
    rep = _timed("Instant Meshes 2000 on blob", lambda: nm.retopo(ob, mode="quads", faces=2000,
                                                                  engine="instant_meshes"))
    st = nm.analyze(ob)
    H.check(rep["engine"] == "instant_meshes", rep)
    H.check(abs(st["faces"] - 2000) <= 400 and st["quad_ratio"] >= 0.95, st)
    H.check(st["boundary_edges"] == 0 and st["non_manifold_edges"] == 0 and st["flipped_edges"] == 0, st)
    H.check(rep["error"]["mean"] < 0.003, rep["error"])


def test_join_floating_part_keeps_designed_grooves():
    """A generator's end cap floating a few mm off the body becomes one solid; a designed groove (narrower than the
    plate-like gap rule) stays open; the rest of the shape does not move."""
    _fresh()
    import bmesh
    from mathutils import Vector
    from nighty_blender.nighty.mesh import _util as U

    def box(name, size, at):
        bm = bmesh.new()
        v = bmesh.ops.create_cube(bm, size=1.0)["verts"]
        bmesh.ops.scale(bm, vec=size, verts=v)
        bmesh.ops.translate(bm, vec=at, verts=v)
        return H.obj_from_bm(name, bm)
    ob = box("Gun", (0.1, 0.4, 0.1), (0, 0, 0))
    cutter = box("Cutter", (0.12, 0.004, 0.03), (0, -0.05, 0.05))  # a 4 mm wide, 15 mm deep groove on top
    mod = ob.modifiers.new("b", 'BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.object = cutter
    mod.solver = 'EXACT'
    U.apply_modifiers(ob, [mod])
    bpy.data.objects.remove(cutter)
    cap = box("Cap", (0.11, 0.06, 0.11), (0, 0.2 + 0.004 + 0.03, 0))  # floating 4 mm off the +Y end
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.from_mesh(cap.data)
    bm.to_mesh(ob.data)
    bm.free()
    bpy.data.objects.remove(cap)
    H._voxelize(ob, 0.0015)  # dense, like a generator's output
    H.check(nm.analyze(ob)["parts"] == 2, "test setup: cap is a separate piece")
    before = ob.copy(); before.data = ob.data.copy(); bpy.context.scene.collection.objects.link(before)
    rep = _timed("cleanup with join", lambda: nm.cleanup(ob, origin="keep", to_ground=False, flatten=False))
    st = nm.analyze(ob)
    print(f"    join: {rep['steps']}")
    H.check(any("joined a part floating" in x for x in rep["steps"]), rep["steps"])
    H.check(st["parts"] == 1 and st["manifold"], st)
    H.check(H.crossing_pairs(ob) == 0, "no faces cut through each other at the new seam")
    tree = nm.stats.bvh(ob)
    hit = tree.ray_cast(Vector((0, -0.05, 0.2)), Vector((0, 0, -1)))
    H.check(hit[0] is not None and hit[0].z < 0.04, ("the designed groove stays open", hit[0]))
    gap_mid = tree.ray_cast(Vector((0.2, 0.202, 0)), Vector((-1, 0, 0)))
    print(f"    joint side: the ray from outside stops at x = {gap_mid[0].x if gap_mid[0] else None}")
    # closed right out to the narrower part's side (the body's, x = 0.05), not just a slab inside a seam
    H.check(gap_mid[0] is not None and gap_mid[0].x > 0.047, ("the joint is closed to the surface", gap_mid[0]))
    top = tree.ray_cast(Vector((0.03, 0.202, 0.2)), Vector((0, 0, -1)))
    H.check(top[0] is not None and top[0].z > 0.047, ("closed on top too", top[0]))
    # the filled joint's outer side is flat and straight along the part's edge (no ribs from the grid it was mapped on)
    xs = []
    for z in np.linspace(-0.035, 0.035, 15):
        hz = tree.ray_cast(Vector((0.2, 0.202, z)), Vector((-1, 0, 0)))
        xs.append(hz[0].x if hz[0] is not None else 0.0)
    print(f"    joint side x over its height: {min(xs):.5f} .. {max(xs):.5f}")
    H.check(float(np.ptp(xs)) < 0.0006, ("the joint's side is flat", xs))
    pts = nm.stats.sample_points(before, 4000, 5)
    far = pts[pts[:, 1] < 0.15]
    d = np.array([tree.find_nearest(Vector(q))[3] for q in far])
    H.check(float(np.percentile(d, 99)) < 0.0015, f"the rest did not move: p99 {np.percentile(d, 99)}")


def test_untangle_takes_crossing_faces_apart():
    """A vertex dragged across its neighbours (what an edge collapse does on thin or stair-stepped bits): its faces
    fold over and cut through others. The untangle pass takes them apart without changing the face count or
    moving the surface."""
    _fresh()
    import bmesh
    from nighty_blender.nighty.mesh import untangle as UT
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=4, radius=0.3)
    ob = H.obj_from_bm("Ball", bm)
    ref = ob.data.copy()
    me = ob.data
    v = me.vertices[0]
    nb = [e.vertices[1] if e.vertices[0] == 0 else e.vertices[0] for e in me.edges if 0 in e.vertices]
    far = me.vertices[nb[0]].co
    v.co = v.co + (far - v.co) * 2.2   # past its neighbour: its fan folds over
    me.update()
    before = H.crossing_pairs(ob)
    H.check(before > 0, "test setup: the dragged vertex makes faces cross")
    n0 = len(me.polygons)
    rep = UT.untangle(ob, reference=ref)
    print(f"    untangle: {rep}")
    H.check(H.crossing_pairs(ob) == 0, ("no faces cross any more", rep))
    H.check(rep["folds"][1] == 0 and rep["flipped"][1] == 0, rep)
    H.check(len(me.polygons) == n0, "same face count")
    st = nm.analyze(ob)
    H.check(st["manifold"] and st["parts"] == 1, st)
    err = nm.surface_error(ob, H.link(bpy.data.objects.new("Ref", ref)))
    H.check(err["max"] < 0.002, err)
    bpy.data.meshes.remove(ref, do_unlink=True)


def test_decimate_leaves_no_crossing_faces():
    """Low poly from a dense generator-like hard-surface mesh at two budgets: no faces cutting through others
    (nighty.check's warning), and the untangle pass says what it did."""
    _fresh()
    for faces in (3000, 800):
        ob, _gt = H.hard_surface(f"Rifle{faces}")
        nm.cleanup(ob, origin="keep", to_ground=False)
        rep = nm.decimate(ob, faces=faces)
        n = H.crossing_pairs(ob)
        print(f"    {faces}: {len(ob.data.polygons)} faces, crossing pairs {n}, untangle {rep.get('untangle')}")
        H.check(n == 0, (faces, rep["steps"]))
        H.check(abs(len(ob.data.polygons) - faces) <= max(4, faces * 0.003), len(ob.data.polygons))
        bpy.data.objects.remove(ob)


def test_flat_sides_fade_out_next_to_raised_parts():
    """flatten_planes flattens a noisy flat side but leaves the start of a raised part's fillet where it was (a
    hard snap there drew a ragged sawtooth rim around raised parts)."""
    _fresh()
    import bmesh
    from mathutils import Vector
    from nighty_blender.nighty.mesh import fix as F
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(0.4, 0.4, 0.06), verts=bm.verts)
    ob = H.obj_from_bm("Plate", bm)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=0.06)
    bmesh.ops.scale(bm, vec=(1, 1, 0.5), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(0, 0, 0.03), verts=bm.verts)
    dome = H.obj_from_bm("Dome", bm)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.from_mesh(dome.data)
    bm.to_mesh(ob.data)
    bm.free()
    bpy.data.objects.remove(dome)
    H._voxelize(ob, 0.004)
    H._soup(ob, 0.00015, 3)
    nm.cleanup(ob, origin="keep", to_ground=False, flatten=False)
    me = ob.data
    co0 = np.array([v.co[:] for v in me.vertices])
    # vertices on the dome's slope (their faces lean well off the top plane)
    steep = np.zeros(len(co0), dtype=bool)
    for p in me.polygons:
        if (abs(p.normal.z) < math.cos(math.radians(F.FADE_TO + 4)) and p.center.z > 0.02
                and math.hypot(p.center.x, p.center.y) < 0.08):
            steep[list(p.vertices)] = True
    planes, moved = F.flatten_planes(ob)
    co1 = np.array([v.co[:] for v in me.vertices])
    H.check(planes >= 1 and moved > 0, (planes, moved))
    d = np.linalg.norm(co1 - co0, axis=1)
    print(f"    flat sides {planes}, moved {moved}; slope vertices moved max {d[steep].max() * 1000:.3f} mm")
    H.check(d[steep].max() < 1e-6, "the dome's slope stays where it was")
    top = (co1[:, 2] > 0.029) & (np.hypot(co1[:, 0], co1[:, 1]) > 0.09) & (np.abs(co1[:, 0]) < 0.17) & (
        np.abs(co1[:, 1]) < 0.17)
    H.check(float(np.ptp(co1[top, 2])) < 0.0005, f"the top is flat: {np.ptp(co1[top, 2])}")


def test_tiny_spike_in_a_groove_is_smoothed():
    """A generator's spike standing in a narrow groove is smoothed down; the groove and everything else stay."""
    _fresh()
    import bmesh
    from mathutils import Vector
    from nighty_blender.nighty.mesh import fragments as FR

    def box(name, size, at):
        bm = bmesh.new()
        v = bmesh.ops.create_cube(bm, size=1.0)["verts"]
        bmesh.ops.scale(bm, vec=size, verts=v)
        bmesh.ops.translate(bm, vec=at, verts=v)
        return H.obj_from_bm(name, bm)
    ob = box("Body", (0.1, 0.2, 0.1), (0, 0, 0))
    cutter = box("Cutter", (0.12, 0.006, 0.04), (0, 0.0, 0.05))   # a 6 mm wide, 20 mm deep groove on top
    mod = ob.modifiers.new("b", 'BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.object = cutter
    mod.solver = 'EXACT'
    U_ = __import__("nighty_blender.nighty.mesh._util", fromlist=["x"])
    U_.apply_modifiers(ob, [mod])
    bpy.data.objects.remove(cutter)
    H._voxelize(ob, 0.0012)
    me = ob.data
    # a spike: the wall vertex nearest the middle of the groove's -Y wall, pulled 2 mm into the groove
    co = np.array([v.co[:] for v in me.vertices])
    target = np.array([0.0, -0.003, 0.04])
    i = int(np.argmin(np.linalg.norm(co - target, axis=1)))
    me.vertices[i].co.y += 0.002
    me.update()
    co0 = np.array([v.co[:] for v in me.vertices])
    old = FR.SPIKE
    FR.SPIKE = 0.012   # this test part is small (25 cm): the spike and groove are as big as on a 60 cm gun
    try:
        spots = FR.smooth_fragments(ob, groove=0.03)
    finally:
        FR.SPIKE = old
    co1 = np.array([v.co[:] for v in me.vertices])
    d = np.linalg.norm(co1 - co0, axis=1)
    print(f"    spots {spots}; spike tip now {(co1[i, 1] - co0[i, 1]) * 1000:+.2f} mm")
    H.check(spots, "the spike was found")
    H.check(co1[i, 1] - co0[i, 1] < -0.001, "the spike went down by more than half")
    far = np.linalg.norm(co0 - co0[i], axis=1) > 0.01
    H.check(d[far].max() < 1e-7, "nothing else moved")
    H.check(H.crossing_pairs(ob) == 0, "no crossing faces")


def test_instant_meshes_hang_is_killed_and_falls_back():
    """A remesher that never answers: killed (with what it started) after the timeout, tried once more, then
    QuadriFlow does the job and the result says so."""
    _fresh()
    import shutil
    import subprocess
    import tempfile
    d = tempfile.mkdtemp(prefix="nighty-im-hang-")   # its own folder: suites running side by side never share it
    pidfile = os.path.join(d, "pids.txt")
    script = os.path.join(d, "hang.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write("import os, sys, time\nopen(sys.argv[1], 'a').write(str(os.getpid()) + chr(10))\ntime.sleep(600)\n")
    if sys.platform == "win32":
        wrapper = os.path.join(d, "hang.cmd")
        with open(wrapper, "w", encoding="utf-8") as f:
            f.write(f'@"{sys.executable}" "{script}" "{pidfile}"\n')
    else:
        wrapper = os.path.join(d, "hang.sh")
        with open(wrapper, "w", encoding="utf-8") as f:
            f.write(f'#!/bin/sh\n"{sys.executable}" "{script}" "{pidfile}"\n')
        os.chmod(wrapper, 0o755)
    old = {k: os.environ.get(k) for k in ("NIGHTY_INSTANT_MESHES", "NIGHTY_REMESH_TIMEOUT")}
    os.environ["NIGHTY_INSTANT_MESHES"] = wrapper
    os.environ["NIGHTY_REMESH_TIMEOUT"] = "3"
    try:
        ob = H.noisy_sphere(floaters=0, holes=0)
        nm.cleanup(ob)
        t0 = time.monotonic()
        rep = nm.retopo(ob, mode="quads", faces=1500, engine="instant_meshes")
        dt = time.monotonic() - t0
        print(f"    hang -> {rep['engine']} in {dt:.1f} s: {rep['steps'][:2]}")
        H.check(rep["engine"] == "quadriflow" and any("stopped answering" in x for x in rep["steps"]), rep)
        H.check(nm.analyze(ob)["quad_ratio"] > 0.9, "QuadriFlow made the quads")
        H.check(dt < 90, f"took {dt:.0f} s")
        pids = [int(x) for x in open(pidfile).read().split()]
        H.check(len(pids) == 2, f"tried twice: {pids}")
        for pid in pids:
            if sys.platform == "win32":
                out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
                H.check(str(pid) not in out, f"process {pid} still running")
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------- the tools (through the background worker)

class FakeCtx:
    """Like the addon's Ctx: start_job(step_fn, label) gets a generator job; here it is stepped to the end at once
    (the addon steps it from its timer)."""

    def __init__(self):
        self.jobs = []
        self.undo_label = None

    def start_job(self, step_fn, label, **kw):
        import types
        job = types.SimpleNamespace(cancelled=False)
        gen = step_fn(job)
        seen = []
        while True:
            try:
                seen.append(next(gen))
            except StopIteration as stop:
                res = stop.value
                break
            time.sleep(0.02)
        H.check(seen and all(0.0 <= p <= 1.0 for p, _m in seen), "progress as (fraction, message)")
        self.jobs.append((label, res))
        return {"job": f"j{len(self.jobs)}"}


def _tool(name):
    import importlib
    importlib.import_module("nighty_blender.tools.topology")
    from nighty_blender.tools import ACTIONS
    return ACTIONS[name]


def test_tools_registered():
    from nighty_blender.tools import ACTIONS
    _tool("retopo")
    for n in ("cleanup_mesh", "retopo", "decimate", "split_parts", "uv_unwrap", "make_lods"):
        t = ACTIONS[n]
        H.check(t.slow and t.changes and t.level == "tools", n)
        json.dumps(t.spec())
        H.check(len(t.description) < 420, f"{n}: keep descriptions short")
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "addon", "nighty_blender", "tools.json"),
              encoding="utf-8") as f:
        on_disk = {t["name"]: t for t in json.load(f)}
    for n in ("mesh",):          # the public router built from these steps
        from nighty_blender.tools import TOOLS
        H.check(on_disk.get(n) == TOOLS[n].spec(), f"tools.json is out of date for {n}: run scripts/gen_tools_json.py")


def test_tool_cleanup_and_retopo_via_worker():
    _fresh()
    ob = H.noisy_sphere()
    mat = bpy.data.materials.new("Skin")
    ob.data.materials.append(mat)
    ob.select_set(True)
    ctx = FakeCtx()
    _timed("tool cleanup_mesh (worker)", lambda: _tool("cleanup_mesh").fn(ctx, {"objects": ["Blob"], "size": 0.5}))
    st = nm.analyze(ob)
    H.check(st["manifold"] and st["parts"] == 1, st)
    H.near(max(st["size"]), 0.5, 1e-3, "size")
    H.check(ob.data.materials[0] == mat and "Skin.001" not in bpy.data.materials, "own material kept, no copies")
    mesh_name = ob.data.name
    res = _timed("tool retopo quads (worker)", lambda: _tool("retopo").fn(ctx, {"objects": ["Blob"], "mode": "quads",
                                                                               "faces": 1200}))
    H.check(res == {"job": "j2"}, res)
    rep = ctx.jobs[-1][1]["objects"][0]
    st = nm.analyze(ob)
    H.check(st["quad_ratio"] > 0.95 and abs(st["faces"] - 1200) <= 200, st)
    src = nm.bake_source(ob)
    H.check(src is not None and len(src.data.polygons) > 60000 and src.hide_get(), "dense original kept hidden")
    H.check(ob.data.name == mesh_name and rep["object"] == "Blob" and rep["bake_source"] == src.name, rep)
    H.check(ob.data.materials[0] == mat and src.data.materials[0] == mat, "materials on both")
    # again with another count: starts from the dense original, still one source
    _tool("retopo").fn(ctx, {"objects": ["Blob"], "mode": "triangles", "faces": 900})
    H.check(abs(len(ob.data.polygons) - 900) <= 4, len(ob.data.polygons))
    H.check(nm.bake_source(ob) == src and len(src.data.polygons) > 60000, "same dense source")
    H.check(all(o.users_collection for o in bpy.data.objects), "no leftover objects from the worker")
    H.check(not any(m.use_fake_user or m.users == 0 for m in bpy.data.meshes), "no leftover meshes")
    H.check(ob.get("nighty_high") == src.name, "bake code finds the high poly by name")


def test_tool_split_uv_lods_via_worker():
    _fresh()
    H.rifle_parts()
    ctx = FakeCtx()
    _tool("split_parts").fn(ctx, {"objects": ["Kit"], "names": ["receiver", "barrel", "scope"]})
    rep = ctx.jobs[-1][1]["objects"][0]
    H.check(rep["count"] == 3 and "Kit" not in bpy.data.objects, rep)
    parts = [bpy.data.objects[r["name"]] for r in rep["parts"]]
    H.check(sorted(p.name for p in parts) == ["Kit_barrel", "Kit_receiver", "Kit_scope"], [p.name for p in parts])
    H.check(all(p.data.materials[0] is not None and p.data.materials[0].name == "Polymer" for p in parts),
            "materials restored")
    _tool("uv_unwrap").fn(ctx, {"objects": [p.name for p in parts], "texture_size": "1K"})
    r = ctx.jobs[-1][1]["report"]
    H.check(r["overlap_px"] == 0 and r["texel_spread"] <= 1.15, r)
    _tool("make_lods").fn(ctx, {"objects": ["Kit_receiver"], "ratios": [0.5, 0.25]})
    rows = ctx.jobs[-1][1]["objects"][0]["lods"]
    H.check([x["name"] for x in rows] == ["Kit_receiver", "Kit_receiver_LOD1", "Kit_receiver_LOD2"], rows)
    lod1 = bpy.data.objects["Kit_receiver_LOD1"]
    H.check(lod1.hide_get() and lod1.get("nighty_lod_of") == "Kit_receiver", "LOD hidden and linked")
    H.check(len(lod1.data.uv_layers) == 1, "LOD keeps UVs")


def test_tool_errors():
    _fresh()
    ctx = FakeCtx()
    try:
        _tool("retopo").fn(ctx, {"objects": ["Nope"]})
        raise AssertionError("missing object should be refused")
    except Exception as e:  # noqa: BLE001
        H.check(type(e).__name__ == "ToolError" and "Nope" in str(e), repr(e))
    bpy.ops.mesh.primitive_cube_add()
    try:
        _tool("decimate").fn(ctx, {"objects": ["Cube"]})
        raise AssertionError("decimate without a target should be refused")
    except Exception as e:  # noqa: BLE001
        H.check(type(e).__name__ == "ToolError", repr(e))
    try:
        _tool("split_parts").fn(ctx, {"objects": ["Cube"], "method": "ai"})
        raise AssertionError("ai split without a segmenter should be refused")
    except Exception as e:  # noqa: BLE001
        H.check("engine" in str(e), str(e))


def test_tool_cancel_stops_the_worker():
    _fresh()
    ob = H.noisy_sphere()
    n = len(ob.data.polygons)

    class Ctx:
        def start_job(self, step_fn, label, **kw):
            import types
            self.job = types.SimpleNamespace(cancelled=False)
            self.gen = step_fn(self.job)
            return {"job": "j1"}
    ctx = Ctx()
    _tool("cleanup_mesh").fn(ctx, {"objects": ["Blob"]})
    next(ctx.gen)  # the background Blender is running now
    ctx.job.cancelled = True
    try:
        next(ctx.gen)
        raise AssertionError("a cancelled job must end")
    except StopIteration as stop:
        H.check(stop.value is None, "no result after cancel")
    H.check(len(ob.data.polygons) == n, "nothing changed")


def test_worker_reports_failures():
    _fresh()
    bpy.ops.mesh.primitive_cube_add()
    run = W.Run([bpy.data.objects["Cube"]], [{"op": "no_such_step", "args": {}}])
    try:
        code = run.run_blocking(timeout=300)
        H.check(code == 0, f"worker exit {code}")
        try:
            run.collect()
            raise AssertionError("an unknown step must fail")
        except RuntimeError as e:
            H.check("no_such_step" in str(e), str(e))
    finally:
        run.close()


# ---------------------------------------------------------------- timing on a denser mesh

def test_timing_dense_blob():
    _fresh()
    ob = H.noisy_sphere(voxel=0.006)
    n = len(ob.data.polygons)
    _timed(f"cleanup {n // 1000}k tris", lambda: nm.cleanup(ob))
    _timed("quads medium (6k) from dense", lambda: nm.retopo(ob, mode="quads", detail="medium"))
    st = nm.analyze(ob)
    H.check(st["manifold"] and st["quad_ratio"] > 0.95, st)
    print("    timings:", json.dumps(TIMES))
