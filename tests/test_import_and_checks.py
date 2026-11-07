# SPDX-License-Identifier: GPL-3.0-or-later
# Import first (2.0): a GLB / OBJ comes in through a background Blender as one object with a locked _SOURCE copy and
# a triage report; nothing may change the copy; check { what: source } finds drift; roundtrip reads an export back;
# the Roblox gate; fix_shading and fix_seams; make_game_ready from a file; the Blender API lookup; the 15 routers.

import json
import os
import shutil
import tempfile
import time

import bpy

from nighty_blender.jobs import JobManager
from nighty_blender.tools import ACTIONS, TOOLS, ToolError

FRESH_SCENE = True


class Ctx:
    level = "tools"
    undo_label = None

    def __init__(self):
        self.jobs = JobManager(lambda obj: None)

    def start_job(self, step_fn, label, **kw):
        return {"job": self.jobs.start_gen(step_fn, label, label, "test")}

    def job_snapshot(self, job_id):
        job = self.jobs.get(job_id)
        return job.snapshot() if job else None

    def run(self, res, timeout=300):
        job = self.jobs.get(res["job"])
        end = time.monotonic() + timeout
        while job.state == "running" and time.monotonic() < end:
            self.jobs.pump(budget=0.05)
            time.sleep(0.005)
        assert job.state == "done", job.error
        return job.result


def _export_textured_box(folder, name="Crate"):
    """A beveled, UV-mapped, textured box exported as GLB (what a person's download looks like), then cleared."""
    bpy.ops.mesh.primitive_cube_add(size=0.6, location=(0, 0, 0.3))
    ob = bpy.context.active_object
    ob.name = name
    bev = ob.modifiers.new("b", "BEVEL")
    bev.width, bev.segments = 0.03, 3
    bpy.ops.object.modifier_apply(modifier=bev.name)
    img = bpy.data.images.new("crate_color", 64, 64)
    img.pixels.foreach_set([0.6, 0.35, 0.15, 1.0] * 64 * 64)
    img.pack()
    mat = bpy.data.materials.new("Wood")
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    mat.node_tree.links.new(tex.outputs[0], bsdf.inputs["Base Color"])
    ob.data.materials.append(mat)
    path = os.path.join(folder, name.lower() + ".glb")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return path


def _import(ctx, path, **kw):
    return ctx.run(ACTIONS["import_model"].fn(ctx, dict({"file": path}, **kw)))


def test_import_keeps_a_locked_source_and_writes_a_triage_report():
    tmp = tempfile.mkdtemp(prefix="nighty-import-")
    try:
        path = _export_textured_box(tmp)
        ctx = Ctx()
        res = _import(ctx, path, name="Crate", size=1.0)
        ob = bpy.data.objects["Crate"]
        src = bpy.data.objects[res["source"]]
        assert res["source"] == "Crate_SOURCE" and src.get("nighty_source_of") == "Crate"
        assert src.name not in bpy.context.scene.objects, "the copy is kept out of the scene"
        assert src.hide_select and all(src.lock_location) and src.use_fake_user
        assert abs(max(ob.dimensions) - 1.0) < 1e-3, ob.dimensions
        assert res["facts"]["uv_layers"] >= 1 and res["facts"]["images"], res["facts"]
        assert res["triage"] and os.path.isfile(res["report_file"])
        with open(res["report_file"], encoding="utf-8") as f:
            report = json.load(f)
        assert report["object"] == "Crate" and report["facts"]["triangles"] == res["facts"]["triangles"]
        # nothing may change the _SOURCE copy through the tools
        for tool, args in (("mesh", {"op": "decimate", "objects": ["Crate_SOURCE"], "faces": 20}),
                           ("texture", {"op": "assign_materials", "parts": {"Crate_SOURCE": "steel"}})):
            try:
                TOOLS[tool].fn(ctx, args)
                raise AssertionError("changed the _SOURCE copy")
            except ToolError as err:
                assert "locked _SOURCE" in str(err), str(err)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_obj_import_and_bad_files():
    tmp = tempfile.mkdtemp(prefix="nighty-import-")
    try:
        path = os.path.join(tmp, "tri.obj")
        with open(path, "w") as f:
            f.write("v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3\nf 1 2 4\nf 2 3 4\nf 1 3 4\n")
        res = _import(Ctx(), path)
        assert res["object"] == "tri" and res["facts"]["triangles"] == 4
        assert any("No UVs" in line for line in res["triage"]), res["triage"]
        for bad, part in ((os.path.join(tmp, "nope.glb"), "no file"), ("model.glb", "full path"),
                          (path.replace(".obj", ".txt"), "")):
            if bad.endswith(".txt"):
                open(bad, "w").close()
                part = "GLB, glTF, FBX and OBJ"
            try:
                ACTIONS["import_model"].fn(Ctx(), {"file": bad})
                raise AssertionError("imported " + bad)
            except ToolError as err:
                assert part.lower() in str(err).lower(), str(err)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_compare_with_the_source_finds_drift():
    tmp = tempfile.mkdtemp(prefix="nighty-import-")
    try:
        ctx = Ctx()
        _import(ctx, _export_textured_box(tmp), name="Crate")
        ob = bpy.data.objects["Crate"]
        ob.location.x += 2.0          # moved: still the same shape
        same = ACTIONS["compare_source"].fn(ctx, {"names": ["Crate"]})
        assert same["pass"], same
        for v in ob.data.vertices:    # one side pushed out by 30 %
            if v.co.x > 0:
                v.co.x *= 1.6
        ob.data.update()
        drift = ACTIONS["compare_source"].fn(ctx, {"names": ["Crate"]})
        assert not drift["pass"] and drift["objects"][0]["drift"]["model_to_source"]["p95_pct"] > 1, drift
        try:
            ACTIONS["compare_source"].fn(ctx, {"names": [bpy.data.objects.new("Lone", bpy.data.meshes.new("m")).name]})
        except ToolError:
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_roundtrip_and_the_roblox_gate():
    bpy.ops.mesh.primitive_cube_add(size=0.5, location=(0, 0, 0.25))
    ob = bpy.context.active_object
    ob.name = "Box"
    ctx = Ctx()
    rt = ctx.run(ACTIONS["roundtrip"].fn(ctx, {"names": ["Box"]}))
    assert rt["pass"], rt
    assert rt["file_facts"]["triangles"] == rt["blender"]["triangles"] == 12
    gate = ACTIONS["roblox_ready"].fn(ctx, {"names": ["Box"]})
    assert gate["pass"], gate
    assert any("no Roblox export" in w for w in gate["warnings"])
    # too many triangles for one MeshPart
    bpy.ops.mesh.primitive_uv_sphere_add(segments=256, ring_count=128, radius=0.3)
    bpy.context.active_object.name = "Dense"
    gate = ACTIONS["roblox_ready"].fn(ctx, {"names": ["Dense"]})
    assert not gate["pass"] and any("20,000" in e for e in gate["errors"]), gate


def test_fix_shading_and_fix_seams():
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.2, depth=0.5)
    cyl = bpy.context.active_object
    res = ACTIONS["fix_shading"].fn(Ctx(), {"objects": [cyl.name], "angle": 30})
    row = res["objects"][0]
    assert row["shading"] == "smooth" and row["sharp_edges"] >= 48, row     # the two caps' rims stay sharp
    assert all(p.use_smooth for p in cyl.data.polygons)
    flat = ACTIONS["fix_shading"].fn(Ctx(), {"objects": [cyl.name], "flat": True})
    assert flat["objects"][0]["shading"] == "flat" and not any(p.use_smooth for p in cyl.data.polygons)
    # a plane whose UVs cover the middle of a texture: colors grow past the island's edge
    bpy.ops.mesh.primitive_plane_add(size=1)
    plane = bpy.context.active_object
    uv = plane.data.uv_layers.active.data
    for i, loop in enumerate(uv):
        loop.uv = ((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75))[i % 4]
    img = bpy.data.images.new("seams", 64, 64)
    px = [0.0, 0.0, 0.0, 1.0] * 64 * 64
    for y in range(16, 48):
        for x in range(16, 48):
            px[(y * 64 + x) * 4:(y * 64 + x) * 4 + 3] = [1.0, 0.2, 0.1]
    img.pixels.foreach_set(px)
    mat = bpy.data.materials.new("M")
    mat.use_nodes = True
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    plane.data.materials.append(mat)
    res = ACTIONS["fix_seams"].fn(Ctx(), {"parts": [plane.name], "margin_px": 4})
    assert res["images"][0]["pixels_filled"] > 100, res
    import numpy as np
    out = np.empty(64 * 64 * 4, np.float32)
    img.pixels.foreach_get(out)
    out = out.reshape(64, 64, 4)
    assert out[14, 30, 0] > 0.5, "a pixel just outside the island took the island's color"
    assert out[2, 2, 0] < 0.1, "far away stays as it was"


def test_make_game_ready_from_a_file():
    tmp = tempfile.mkdtemp(prefix="nighty-mgr-")
    out = tempfile.mkdtemp(prefix="nighty-mgr-out-")
    try:
        path = _export_textured_box(tmp, "Chest")
        ctx = Ctx()
        res = ctx.run(ACTIONS["make_game_ready"].fn(ctx, {
            "file": path, "name": "Chest", "path": out, "confirmed": True,
            "options": {"mesh": "triangles", "faces": 200, "textures": "none", "made_for": "gltf"}}))
        rep = json.loads(res[0]["text"])
        steps = [s["step"] for s in rep["steps"]]
        assert steps[:3] == ["asset_options", "import_model", "cleanup_mesh"], steps
        assert "export_asset" in steps and rep["finished"] is True, rep
        assert rep["imported"]["source"] == "Chest_SOURCE"
        assert any(f.endswith(".glb") for f in rep["export"]["files"]), rep["export"]
        cmp = ACTIONS["compare_source"].fn(ctx, {"names": rep["parts"], "tolerance_pct": 3})
        assert cmp["objects"][0]["triangles"]["model"] <= 200, cmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)


def test_api_lookup_and_the_routers():
    g = TOOLS["guide"].fn(Ctx(), {"api": "bpy.types.Mesh.vertices"})
    assert g["property"]["name"] == "vertices" and g["property"]["of"] == "MeshVertex", g
    op = TOOLS["guide"].fn(Ctx(), {"api": "bpy.ops.mesh.primitive_cube_add"})
    assert any(p["name"] == "size" for p in op["properties"]), op
    try:
        TOOLS["guide"].fn(Ctx(), {"api": "bpy.types.Meshh"})
        raise AssertionError("found a type that isn't there")
    except ToolError as err:
        assert "Close" in str(err)
    for tool, key in (("mesh", "op"), ("texture", "op"), ("check", "what")):
        schema = TOOLS[tool].input_schema
        assert schema["required"] == [key] and schema["properties"][key]["enum"], tool
        try:
            TOOLS[tool].fn(Ctx(), {key: "explode"})
            raise AssertionError("ran an unknown op")
        except ToolError as err:
            assert key in str(err)
    st = TOOLS["status"].fn(Ctx(), {})
    assert "models_come_from" in st and "engine" not in st
