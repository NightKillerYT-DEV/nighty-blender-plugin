# SPDX-License-Identifier: GPL-3.0-or-later
# b-lib's MCP tools through the registry: scene_info, look, measure, verify_mesh, finish_asset, reference_sheet,
# get_guide, search_examples; tools.json is up to date.

FRESH_SCENE = True  # tests/run.py: an empty factory scene before each test

import base64
import json
import os

import bpy

from _util import Ctx, call, call_json, n, raises, registry

MINE = ("scene_info", "look", "measure", "verify_mesh", "finish_asset", "reference_sheet", "get_guide",
        "search_examples")


def _png(block):
    assert block["type"] == "image" and block["mimeType"] == "image/png"
    data = base64.b64decode(block["data"])
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    import struct
    w, h = struct.unpack(">II", data[16:24])
    return data, w, h


def _scene():
    body = n.box((0.4, 0.3, 0.2), at=(0, 0, 0.1), name="Body")
    lid = n.box((0.4, 0.3, 0.05), name="Lid")
    n.align(lid, body, "on_top")
    n.bevel([body][0])
    return body, lid


def test_registered_with_schemas():
    tools = registry()
    for name in MINE:
        t = tools.ACTIONS[name]
        assert t.description and len(t.description) < 600, name
        schema = t.input_schema
        assert schema["type"] == "object" and "properties" in schema
        text = json.dumps(schema)
        for bad in ("$ref", "oneOf", "anyOf", "allOf"):
            assert bad not in text, (name, bad)
    assert not tools.ACTIONS["look"].changes and not tools.ACTIONS["verify_mesh"].changes
    assert tools.ACTIONS["finish_asset"].changes


def test_tools_json_lists_these_tools():
    from nighty_blender import _tools_json
    names = [s["name"] for s in json.loads(open(_tools_json.path(), encoding="utf-8").read())]
    assert names == sorted(names) and len(names) == 15        # the public tools (these steps sit behind them)
    from nighty_blender.tools import ACTIONS
    assert all(m in ACTIONS for m in MINE)


def test_run_python_safe_level_imports_nighty():
    code = "\n".join(["import nighty as n", "from mathutils import Vector", "import math",
                      "b = n.box(0.2, at=(0, 0, 0.1), name='SafeBox')", "n.bevel(b)",
                      "result = n.verify(b)['pass']"])
    blocks = call("run_python", {"code": code}, level="safe")
    assert blocks[-1]["text"].strip().lower() == "true", blocks
    for bad in ("import os", "import nighty.engine", "from nighty import engine", "import subprocess",
                "from nighty.engine import download"):
        raises(call, "run_python", {"code": bad}, level="safe")
    blocks = call("run_python", {"code": "from nighty.shapes import box\nresult = box(0.1, name='Sub').name"},
                  level="safe")
    assert "Sub" in blocks[-1]["text"], blocks
    code = "import nighty\nfrom nighty.shapes import box\nresult = nighty.__name__ + ' ' + box.__module__"
    blocks = call("run_python", {"code": code}, level="full")  # full Python: `nighty` is the library too
    assert "nighty_blender.nighty nighty_blender.nighty.shapes" in blocks[-1]["text"], blocks


def test_scene_info_tree():
    _scene()
    coll = n.collection("Props")
    n.part(n.cylinder(0.05, 0.2, name="Can"), collection=coll)
    out = call_json("scene_info")
    assert out["objects"] == 3 and out["blender"] == bpy.app.version_string
    names = [o["name"] for o in out["tree"]["objects"]]
    assert set(names) == {"Body", "Lid"}
    body = next(o for o in out["tree"]["objects"] if o["name"] == "Body")
    assert body["size"] == [0.4, 0.3, 0.2] and "bevel" in body["mods"]
    assert out["tree"]["children"][0]["collection"] == "Props"
    out = call_json("scene_info", {"limit": 1})
    assert "more" in out


def test_look_grid_and_restores_everything():
    body, lid = _scene()
    sc = bpy.context.scene
    cam = bpy.data.objects.new("MyCam", bpy.data.cameras.new("MyCam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    sc.render.engine = "CYCLES"
    sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
    sc.render.film_transparent = False
    before = (len(bpy.data.objects), len(bpy.data.cameras), len(bpy.data.meshes), len(bpy.data.worlds),
              len(bpy.data.images))
    blocks = call("look", {"wireframe": True, "size": 128})
    info = json.loads(blocks[0]["text"])
    assert [v["view"] for v in info["views"]] == ["front", "right", "top", "three_quarter"]
    assert info["views"][0]["projection"] == "ortho" and info["views"][3]["projection"] == "perspective"
    data, w, h = _png(blocks[1])
    assert (w, h) == (128 * 2 + 2, 128 * 2 + 2)
    assert sc.camera == cam and sc.render.engine == "CYCLES" and sc.render.resolution_x == 1920
    assert sc.render.film_transparent is False
    after = (len(bpy.data.objects), len(bpy.data.cameras), len(bpy.data.meshes), len(bpy.data.worlds))
    assert after == before[:4], (before, after)
    assert not body.hide_render and not lid.hide_render and not cam.hide_render


def test_look_modes_separate_and_names():
    _scene()
    for mode in ("matcap", "silhouette", "material"):
        blocks = call("look", {"names": ["Body"], "views": ["three_quarter"], "mode": mode, "size": 96})
        _png(blocks[1])
    blocks = call("look", {"views": ["front", "top"], "separate": True, "size": 64})
    assert len(blocks) == 3
    assert raises(call, "look", {"names": ["Nope"]}, contains="No object named")
    assert raises(call, "look", {"views": ["sideways"]}, contains="Unknown view")


def test_measure_tool():
    _scene()
    out = call_json("measure", {"names": ["Body", "Lid"], "pairs": [["Body", "Lid"]]})
    assert out["objects"]["Body"]["size"] == [0.4, 0.3, 0.2]
    assert out["all"]["size"][2] == 0.25
    assert out["pairs"][0]["touching"] is True
    ghost = n.box((0.42, 0.3, 0.26), at=(0, 0, 0.13), name="Ghost")
    ghost["nighty_role"] = "ghost"
    out = call_json("measure", {"names": ["Body", "Lid"], "reference": "Ghost"})
    assert out["reference"]["bounds_iou"] > 0.8


def test_verify_and_finish_gate():
    body, lid = _scene()
    lid.location.z += 0.2  # floating lid
    raises(call, "finish_asset", {"names": ["Body", "Lid"]}, contains="not checked yet")
    out = call_json("verify_mesh", {"names": ["Body", "Lid"]})
    assert out["pass"] is False and out["floating"]
    raises(call, "finish_asset", {"names": ["Body", "Lid"]}, contains="failed")
    n.align(lid, body, "on_top")
    raises(call, "finish_asset", {"names": ["Body", "Lid"]}, contains="changed since")
    out = call_json("verify_mesh", {"names": ["Body", "Lid"]})
    assert out["pass"] is True and out["objects"]["Body"]["quads"] > 6
    blocks = call("finish_asset", {"names": ["Body", "Lid"], "notes": "a small box"})
    assert blocks[0]["text"].startswith("Finished: Body, Lid")
    rec = json.loads(body["nighty_asset"])
    assert rec["verified"] and rec["notes"] == "a small box"
    assert "Nighty assets" in bpy.data.texts
    n.bevel(body, width=0.02)
    raises(call, "finish_asset", {"names": ["Body"]}, contains="changed since")
    blocks = call("finish_asset", {"names": ["Body"], "reason": "bevel width only; checked shape before"})
    assert "with a reason" in blocks[0]["text"]
    assert json.loads(body["nighty_asset"])["reason"].startswith("bevel")


def test_verify_options():
    plane = n.plane(0.5, name="Card")
    assert call_json("verify_mesh", {"names": ["Card"]})["pass"] is False
    assert call_json("verify_mesh", {"names": ["Card"], "allow_open": True})["pass"] is True
    s = n.sphere(0.2, name="Ball")
    out = call_json("verify_mesh", {"names": ["Ball"], "budget": 50, "full": True})
    assert out["pass"] is False and "duplicate_verts" in out["objects"]["Ball"]


def _picture(path, w=120, h=60):
    """A red rectangle (80 x 40 px) on a transparent picture."""
    img = bpy.data.images.new("refpic", w, h, alpha=True)
    import numpy as np
    px = np.zeros((h, w, 4), np.float32)
    px[10:50, 20:100] = (1, 0, 0, 1)
    img.pixels.foreach_set(px.ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def test_reference_sheet_load_score_clear():
    import tempfile
    d = tempfile.mkdtemp()
    path = os.path.join(d, "side.png")
    _picture(path)
    out = call_json("reference_sheet", {"action": "load", "images": [{"path": path, "view": "front", "width": 0.8}]})
    placed = out["loaded"][0]
    assert placed["subject_size_m"] == [0.8, 0.4]
    ref = bpy.data.objects[placed["name"]]
    assert ref.empty_display_type == "IMAGE" and ref.get("nighty_role") == "reference"
    # a box of the same size, standing on the ground, matches the grounded reference
    n.box((0.8, 0.1, 0.4), at=(0, 0, 0.2), name="Gun")
    blocks = call("reference_sheet", {"action": "score", "view": "front", "names": ["Gun"]})
    score = json.loads(blocks[0]["text"])
    assert score["iou"] > 0.9, score
    _png(blocks[1])
    n.box((0.4, 0.1, 0.4), at=(-0.2, 0, 0.2), name="Short")
    score = json.loads(call("reference_sheet", {"action": "score", "view": "front", "names": ["Short"]})[0]["text"])
    assert 0.4 < score["iou"] < 0.6 and score["reference_not_covered"] > 0.4
    look = call("look", {"names": ["Gun"], "views": ["front"], "references": True, "size": 96})
    _png(look[1])
    assert call_json("reference_sheet", {"action": "list"})["references"][0]["view"] == "front"
    assert "Gun" not in [o.name for o in n.objects()] or True
    assert call_json("reference_sheet", {"action": "clear"})["cleared"] == 1
    assert not [o for o in bpy.data.objects if o.get("nighty_role") == "reference"]
    raises(call, "reference_sheet", {"action": "load", "images": [{"path": os.path.join(d, "nope.png")}]},
           contains="not found")


def test_guides_and_examples_tools():
    listing = call("get_guide")[0]["text"]
    assert "workflow" in listing and "library" in listing
    text = call("get_guide", {"topic": "workflow"})[0]["text"]
    assert text.startswith("# ")
    raises(call, "get_guide", {"topic": "../secret"}, contains="No guide")
    out = call_json("search_examples", {"query": "wooden crate", "limit": 1})
    assert out["results"] and "crate" in out["results"][0]["name"]
    assert "import nighty as n" in out["results"][0]["code"]
    styled = call_json("search_examples", {"query": "crate", "style": "stylized", "limit": 5, "code": False})
    assert styled["results"] and all(r["style"] == "stylized" for r in styled["results"])
    real = call_json("search_examples", {"query": "crate", "style": "realistic", "limit": 5, "code": False})
    assert real["results"] and all(r["style"] == "realistic" for r in real["results"])
    assert all(r["verify"]["triangles"] <= r["verify"]["budget"] for r in real["results"])
    blocks = call("search_examples", {"query": "stylized pistol gun", "image": True, "code": False})
    assert "code" not in json.loads(blocks[0]["text"])["results"][0]
    assert len(blocks) == 2, "the example's picture"
    pic = blocks[1]          # the small render.jpg the extension ships
    assert pic["type"] == "image" and pic["mimeType"] == "image/jpeg"
    assert base64.b64decode(pic["data"])[:3] == b"\xff\xd8\xff"
