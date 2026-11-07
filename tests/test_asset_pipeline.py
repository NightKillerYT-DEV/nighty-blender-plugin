# SPDX-License-Identifier: GPL-3.0-or-later
# The whole asset pipeline: tool chains (one tool waiting on another's job, cancel reaching the child),
# make_game_ready end to end on a textured dense mesh (its own textures: colors carried from the high poly onto the
# low poly)
# and with materials per part (split, joined bake of parts sharing one high poly), the decimate fin repair, and
# verify_mesh telling split-part seams from holes.

import os
import shutil
import tempfile
import time

import bmesh
import bpy

from nighty_blender.jobs import JobManager
from nighty_blender.tools import ACTIONS, ToolError, action, text
from nighty_blender.tools._chain import StepFailed, run_tool

FRESH_SCENE = True


class Ctx:
    level = "tools"
    undo_label = None

    def __init__(self):
        self.jobs = JobManager(lambda obj: None)

    def start_job(self, step_fn, label, **kw):
        return {"job": self.jobs.start_gen(step_fn, label, label, "test")}

    def run(self, res, timeout=300):
        job = self.jobs.get(res["job"])
        end = time.monotonic() + timeout
        while job.state == "running" and time.monotonic() < end:
            self.jobs.pump(budget=0.05)
            time.sleep(0.01)
        return job


def _fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _textured_sphere(name="Ball", segments=64, rings=32):
    """A dense UV sphere whose texture is red on one half of its UVs and blue on the other."""
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=rings, radius=0.25, location=(0, 0, 0.25))
    ob = bpy.context.active_object
    ob.name = name
    img = bpy.data.images.new("halves", 64, 64)
    px = []
    for y in range(64):
        for x in range(64):
            px += [0.9, 0.05, 0.05, 1.0] if x < 32 else [0.05, 0.1, 0.9, 1.0]
    img.pixels.foreach_set(px)
    img.pack()
    mat = bpy.data.materials.new("AI look")
    mat.use_nodes = True
    tree = mat.node_tree
    bsdf = next(n for n in tree.nodes if n.type == "BSDF_PRINCIPLED")
    tex = tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tree.links.new(tex.outputs[0], bsdf.inputs["Base Color"])
    ob.data.materials.append(mat)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    return ob


def test_chain_waits_and_cancel_reaches_the_child():
    name = "test_slow_child"

    @action(name, "A slow test tool.", {"type": "object", "properties": {}}, slow=True, changes=False)
    def _slow(ctx, args):
        def step(job):
            for i in range(10000):
                if job.cancelled:
                    return None
                yield i / 10000, "working"
            return {"done": True}
        return ctx.start_job(step, "slow child")

    try:
        ctx = Ctx()

        def parent_step(job):
            res = yield from run_tool(ctx, name, {}, 0.0, 1.0, parent=job)
            return [text(res)]

        pid = ctx.start_job(parent_step, "parent")["job"]
        for _ in range(5):
            ctx.jobs.pump(budget=0.02)
        children = ctx.jobs.children.get(pid, [])
        assert len(children) == 1, ctx.jobs.children
        assert ctx.jobs.get(children[0]).state == "running"
        assert ctx.jobs.cancel(pid)
        ctx.jobs.pump(budget=0.02)
        assert ctx.jobs.get(pid).state == "cancelled"
        assert ctx.jobs.get(children[0]).state == "cancelled", "the child stopped with its parent"
    finally:
        ACTIONS.pop(name, None)


def test_chain_reports_failures_plainly():
    name = "test_failing_child"

    @action(name, "A failing test tool.", {"type": "object", "properties": {}}, slow=True, changes=False)
    def _fail(ctx, args):
        def step(job):
            yield 0.5, "half"
            raise ToolError("the mesh has no faces")
        return ctx.start_job(step, "failing child")

    try:
        ctx = Ctx()
        gen = run_tool(ctx, name, {})
        err = None
        try:
            while True:
                next(gen)
                ctx.jobs.pump(budget=0.02)
        except StepFailed as e:
            err = e
        assert err is not None and err.message == "the mesh has no faces", err
        try:
            list(run_tool(ctx, "no_such_tool", {}))
            raise AssertionError("ran a missing tool")
        except StepFailed as e:
            assert "isn't installed" in e.message
    finally:
        ACTIONS.pop(name, None)


def test_make_game_ready_refuses_bad_requests():
    _fresh()
    bpy.ops.mesh.primitive_cube_add()
    ctx = Ctx()
    for args, part in (({}, "Give the model"), ({"object": "Cube", "file": "C:/a.glb"}, "only one"),
                       ({"object": "Nope"}, "No mesh"), ({"object": "Cube", "texture_source": "magic"}, "texture_source"),
                       ({"object": "Cube", "options": {"colour": "red"}}, "unknown"),
                       ({"object": "Cube", "options": {"made_for": "playstation"}}, "made_for")):
        try:
            ACTIONS["make_game_ready"].fn(ctx, args)
            raise AssertionError(f"accepted {args}")
        except ToolError as err:
            assert part in str(err), (args, str(err))


def test_roblox_gets_triangles_unless_the_person_picks():
    from nighty_blender.nighty import presets
    from nighty_blender.tools.asset import _mesh_line
    o = presets.resolve({"made_for": "roblox"})
    assert o["mesh"] == "triangles" and "Roblox uses triangles" in o["mesh_note"] and not o["mesh_chosen"]
    for name in ("Realistic weapon", "Stylized weapon"):
        assert presets.resolve({"made_for": "roblox"}, preset=name)["mesh"] == "triangles", name
        assert presets.resolve({"made_for": "unity"}, preset=name)["mesh"] == "quads", name
        assert presets.resolve(preset=name)["mesh"] == "quads", name
    o = presets.resolve({"made_for": "roblox", "mesh": "quads"}, preset="Realistic weapon")
    assert o["mesh"] == "quads" and "mesh_note" not in o and o["mesh_chosen"], "the person's pick wins"
    assert presets.resolve({"made_for": "roblox", "mesh": "auto"})["mesh"] == "triangles", "auto is no pick"
    assert any(q.get("note") for q in presets.menu()["questions"] if q["key"] == "mesh")
    note = presets.resolve({"made_for": "roblox"})["mesh_note"]
    line = _mesh_line({"result": "triangles", "faces": 12000, "triangles": 12000}, note)
    assert line == f"Triangles, 12,000 - {note}", line
    assert _mesh_line({"result": "quads", "faces": 7400, "triangles": 14800}) ==         "Quads, 7,400 (14,800 triangles in a game)"


def test_make_game_ready_own_textures_route():
    _fresh()
    ball = _textured_sphere()
    out = tempfile.mkdtemp(prefix="nighty-make-")
    try:
        ctx = Ctx()
        job = ctx.run(ACTIONS["make_game_ready"].fn(ctx, {
            "object": ball.name, "name": "Ball", "path": out,
            "options": {"mesh": "triangles", "faces": 600, "textures": "pbr", "size": "1K", "made_for": "gltf"},
            "confirmed": True}))
        assert job.state == "done", job.error
        import json
        rep = json.loads(job.result[0]["text"])
        steps = [s["step"] for s in rep["steps"]]
        assert steps == ["asset_options", "clean_colors", "retopo", "uv_unwrap", "bake", "verify_textures",
                         "export_asset", "verify_mesh", "finish_asset"], steps
        assert rep["texture_source"] == "own" and rep["finished"] is True, rep
        assert rep["mesh"].startswith("Triangles, "), rep["mesh"]
        assert rep["retopo"]["triangles"] <= 610
        assert rep["texture_check"]["passed"], rep["texture_check"]
        assert any(f.endswith(".glb") for f in rep["export"]["files"])
        assert len(job.result) == 2 and job.result[1]["type"] == "image"
        low = bpy.data.objects["Ball"]
        assert len(low.data.polygons) <= 610
        # the AI colors came over: the baked base color holds both the red and the blue half
        folder = rep["maps"]["folder"]
        img = bpy.data.images.load(os.path.join(folder, rep["maps"]["maps"]["base_color"]))
        import numpy as np
        px = np.empty(img.size[0] * img.size[1] * 4, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(-1, 4)
        red = ((px[:, 0] > 0.5) & (px[:, 2] < 0.3)).mean()
        blue = ((px[:, 2] > 0.5) & (px[:, 0] < 0.3)).mean()
        assert red > 0.05 and blue > 0.05, (red, blue)
        assert low.get("nighty_bake_transfer") is True
        assert json.loads(low["nighty_asset"])["verified"] is True
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_make_game_ready_materials_route_with_parts():
    _fresh()
    # one dense mesh made of two pieces: split_parts finds them; both share one bake source
    bpy.ops.mesh.primitive_cube_add(size=0.4, location=(0, 0, 0.2))
    a = bpy.context.active_object
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.12, location=(0, 0, 0.44))
    b = bpy.context.active_object
    for o in (a, b):
        o.select_set(True)
    bpy.context.view_layer.objects.active = a
    bpy.ops.object.join()
    a.name = "Thing"
    sub = a.modifiers.new("s", "SUBSURF")
    sub.levels = 2
    bpy.ops.object.modifier_apply(modifier=sub.name)
    out = tempfile.mkdtemp(prefix="nighty-make-")
    try:
        ctx = Ctx()
        job = ctx.run(ACTIONS["make_game_ready"].fn(ctx, {
            "object": "Thing", "path": out, "materials": ["wood", "brass"],
            "options": {"mesh": "triangles", "faces": 900, "textures": "color", "size": "1K", "made_for": "gltf"},
            "confirmed": True}))
        assert job.state == "done", job.error
        import json
        rep = json.loads(job.result[0]["text"])
        steps = [s["step"] for s in rep["steps"]]
        assert "split_parts" in steps and "assign_materials" in steps and "bake" in steps, steps
        assert len(rep["parts"]) == 2, rep["parts"]
        assert rep["texture_source"] == "materials"
        assert rep["mesh_check"]["pass"], rep["mesh_check"]
        mats = {bpy.data.objects[p].material_slots[0].material.name for p in rep["parts"]}
        assert len(mats) == 1 and "Baked" in mats.pop(), "one baked texture set for both parts"
        assert rep["finished"] is True
    finally:
        shutil.rmtree(out, ignore_errors=True)


def _two_tone_thing():
    """A dense box (brown, not metal) with a ball on top (gold, metal) in one mesh with one AI-like material."""
    import numpy as np
    bpy.ops.mesh.primitive_cube_add(size=0.4, location=(0, 0, 0.2))
    a = bpy.context.active_object
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.12, location=(0, 0, 0.44))
    b = bpy.context.active_object
    for o in (a, b):
        o.select_set(True)
    bpy.context.view_layer.objects.active = a
    bpy.ops.object.join()
    a.name = "Thing"
    sub = a.modifiers.new("s", "SUBSURF")
    sub.levels = 2
    bpy.ops.object.modifier_apply(modifier=sub.name)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    # the box's faces use the left half of the texture, the ball's the right half
    me = a.data
    uv = me.uv_layers.active.data
    for poly in me.polygons:
        ball = (a.matrix_world @ poly.center).z > 0.405
        for li in poly.loop_indices:
            u, v = uv[li].uv
            uv[li].uv = ((0.5 + u * 0.5) if ball else (u * 0.5), v)
    base = bpy.data.images.new("base", 64, 64)
    px = np.zeros((64, 64, 4), np.float32)
    px[..., 3] = 1
    px[:, :32, :3] = (0.42, 0.24, 0.11)
    px[:, 32:, :3] = (0.8, 0.64, 0.3)
    base.pixels.foreach_set(px.ravel())
    base.pack()
    orm = bpy.data.images.new("orm", 64, 64)
    q = np.zeros((64, 64, 4), np.float32)
    q[..., 3] = 1
    q[:, 32:, 2] = 1.0
    orm.pixels.foreach_set(q.ravel())
    orm.pack()
    mat = bpy.data.materials.new("AI look")
    mat.use_nodes = True
    t = mat.node_tree
    bsdf = next(n for n in t.nodes if n.type == "BSDF_PRINCIPLED")
    tb = t.nodes.new("ShaderNodeTexImage")
    tb.image = base
    tm = t.nodes.new("ShaderNodeTexImage")
    tm.image = orm
    sep = t.nodes.new("ShaderNodeSeparateColor")
    t.links.new(tb.outputs[0], bsdf.inputs["Base Color"])
    t.links.new(tm.outputs[0], sep.inputs[0])
    t.links.new(sep.outputs[2], bsdf.inputs["Metallic"])
    me.materials.append(mat)
    return a


def test_make_game_ready_picks_each_parts_material_from_its_own_color():
    _fresh()
    _two_tone_thing()
    out = tempfile.mkdtemp(prefix="nighty-make-")
    try:
        ctx = Ctx()
        # the list is given "wrong way round" (ball first): each part still gets the material of its own color
        job = ctx.run(ACTIONS["make_game_ready"].fn(ctx, {
            "object": "Thing", "path": out, "materials": ["brass", "wood"],
            "options": {"mesh": "triangles", "faces": 900, "textures": "pbr", "size": "1K", "made_for": "gltf"},
            "confirmed": True}))
        assert job.state == "done", job.error
        import json
        rep = json.loads(job.result[0]["text"])
        assert len(rep["parts"]) == 2, rep["parts"]
        got = {}
        for p in rep["parts"]:
            ob = bpy.data.objects[p]
            top = max((ob.matrix_world @ v.co).z for v in ob.data.vertices)
            got["ball" if top > 0.5 else "box"] = rep["materials"][p]["material"]
        assert got == {"box": "wood", "ball": "brass"}, (got, rep["materials"])
        assert rep["finished"] is True
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_parts_material_picked_from_the_library_without_a_list():
    _fresh()
    _two_tone_thing()
    from nighty_blender.tools.asset import _choose_materials, _part_looks
    from nighty_blender.nighty.mesh import topo
    ob = bpy.data.objects["Thing"]
    topo.keep_bake_source(ob)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.separate(type="LOOSE")
    bpy.ops.object.mode_set(mode="OBJECT")
    parts = [o.name for o in bpy.data.objects if o.type == "MESH" and o.get("nighty_role") != "bake_source"]
    for p in parts:
        bpy.data.objects[p]["nighty_high"] = ob["nighty_high"]
    looks_ = _part_looks(parts)
    plan, why = _choose_materials(parts, None, looks_)
    names = sorted(r["material"] for r in why.values())
    assert names == ["brass", "wood"], why


def test_decimate_repairs_fins():
    _fresh()
    from nighty_blender.nighty.mesh import topo
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=0.3)
    ob = bpy.context.active_object
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.edges.ensure_lookup_table()
    e = bm.edges[0]
    v = bm.verts.new((0.0, 0.0, 0.9))
    bm.faces.new((e.verts[0], e.verts[1], v))          # a fin: a third face on one edge
    bm.to_mesh(ob.data)
    bm.free()
    n = topo._repair_fins(ob)
    assert n >= 1
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    assert all(len(ed.link_faces) <= 2 for ed in bm.edges)
    assert all(len(f.verts) == 3 for f in bm.faces)
    assert not [ed for ed in bm.edges if ed.is_boundary], "closed again"
    bm.free()


def test_fin_repair_closes_a_hole_through_one_vertex_twice():
    _fresh()
    from nighty_blender.nighty.mesh import topo
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=0.3)
    ob = bpy.context.active_object
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    v = bm.verts[0]
    fan = list(v.link_faces)
    a = fan[0]
    b = next(f for f in fan[1:] if not set(a.edges) & set(f.edges))     # touches `a` only at v: a bowtie hole
    far = max(bm.edges, key=lambda e: (e.verts[0].co - v.co).length)
    w = bm.verts.new(far.verts[0].co * 1.6)
    bm.faces.new((far.verts[0], far.verts[1], w))                          # and a fin somewhere else
    bmesh.ops.delete(bm, geom=[a, b], context='FACES_ONLY')
    bm.to_mesh(ob.data)
    bm.free()
    assert topo._repair_fins(ob) >= 1
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    assert not [e for e in bm.edges if e.is_boundary or len(e.link_faces) > 2], "closed and manifold again"
    assert all(len(f.verts) == 3 for f in bm.faces)
    bm.free()


def test_fin_repair_keeps_a_clean_dense_mesh_and_drops_crumbs():
    _fresh()
    from nighty_blender.nighty.mesh import topo
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=5, radius=0.3)     # 20,480 closed triangles
    ob = bpy.context.active_object
    n0 = len(ob.data.polygons)
    assert topo._repair_fins(ob) == 0, "a clean closed mesh is left alone"
    assert len(ob.data.polygons) == n0
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    a, b, c, d = (bm.verts.new(p) for p in ((1, 0, 0), (1.1, 0, 0), (1, 0.1, 0), (1.1, 0.1, 0)))
    bm.faces.new((a, b, c))
    bm.faces.new((b, d, c))                                              # a two-triangle crumb
    bm.to_mesh(ob.data)
    bm.free()
    assert topo._repair_fins(ob) == 2
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    assert len(bm.faces) == n0
    assert not [e for e in bm.edges if e.is_boundary or not e.link_faces], "no holes, no wire edges"
    bm.free()


def test_unsaved_files_bake_into_their_own_folders():
    _fresh()
    from nighty_blender.nighty import bake
    a = bake.asset_folder("Chest")
    assert a == bake.asset_folder("Chest"), "the same file keeps its folder"
    assert os.path.basename(a).startswith("Chest-")
    _fresh()                                   # another (unsaved) file making a 'Chest' too
    assert bake.asset_folder("Chest") != a


def test_verify_mesh_split_seams_are_not_holes():
    _fresh()
    from nighty_blender.nighty import check
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.5))
    cube = bpy.context.active_object
    bpy.ops.object.duplicate()
    other = bpy.context.active_object
    # cut each copy in half along z: keep the bottom of one, the top of the other (they meet on one ring)
    for ob, keep_top in ((cube, False), (other, True)):
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        res = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, 0, 0),
                                     plane_no=(0, 0, 1), clear_inner=keep_top, clear_outer=not keep_top)
        bm.to_mesh(ob.data)
        bm.free()
    rep = check.verify([cube, other])
    for name in (cube.name, other.name):
        r = rep["objects"][name]
        assert r["boundary_edges"] == 4 and r.get("seam_edges") == 4, r
    assert not any("open edges" in e for e in rep["errors"]), rep["errors"]
    alone = check.verify([cube])
    assert any("open edges" in e for e in alone["errors"]), "alone it is a real hole"
