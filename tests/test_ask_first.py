# SPDX-License-Identifier: GPL-3.0-or-later
# Ask first: before make_game_ready runs on the person's model, the AI sends the person ONE question with the picks
# filled in (the exact triangle count among them) and waits. make_game_ready refuses to start without
# `confirmed: true`, and the refusal is that same question; run_python filling an empty scene with new meshes gets a
# short reminder that models come from the person (import). No generation, no quality / views / versions lines.

import bpy

from nighty_blender.nighty import presets
from nighty_blender.tools import ACTIONS, TOOLS, ToolError

FRESH_SCENE = True

ROBLOX_QUESTION = ("Mesh: Triangles · Triangles: 15,000 (Roblox default; type any number) · Textures: PBR, baked · "
                   "Size: 1K · Made for: Roblox · Colors: Auto (sharp borders). OK, or change something?")


class Ctx:
    level = "safe"
    undo_label = None


def _refusal(args):
    try:
        ACTIONS["make_game_ready"].fn(Ctx(), args)
    except ToolError as err:
        return str(err)
    raise AssertionError(f"make_game_ready started without the person's answer: {args}")


def test_the_question_has_every_pick_and_the_count():
    q = presets.question(presets.resolve({"made_for": "roblox"}))
    assert q == ROBLOX_QUESTION, q
    q = presets.question(presets.resolve({"made_for": "unity", "mesh": "quads", "faces": 8000}))
    assert "Mesh: Quads · Faces: 8,000 (type any number)" in q and "Made for: Unity" in q, q
    for word in ("Quality", "Versions", "Views", "AI"):
        assert word not in q, (word, q)
    q = presets.question(presets.resolve({"textures": "none", "made_for": "blender"}))
    assert "Textures: None" in q and "Size" not in q and "Colors" not in q and "Made for: just Blender" in q, q


def test_smart_defaults_roblox_count_and_size_and_the_exact_count_wins():
    o = presets.resolve({"made_for": "roblox"})
    assert o["faces"] == 15000 and o["size"] == "1K" and o["mesh"] == "triangles" and not o["faces_exact"]
    o = presets.resolve({"made_for": "roblox", "size": "2K", "detail": "low"})
    assert o["size"] == "2K" and o["faces"] == presets.FACES["low"], "the person's own picks win"
    o = presets.resolve({"made_for": "roblox", "detail": "high", "faces": "9,500"})
    assert o["faces"] == 9500 and o["faces_exact"], "an exact count wins over the detail level"
    ok = presets.on_ok(presets.resolve({"made_for": "roblox"}))
    assert ok["confirmed"] is True and ok["options"]["faces"] == 15000, ok
    assert set(ok["options"]) <= {"mesh", "textures", "texture_type", "size", "made_for", "colors", "faces"}, ok
    again = presets.resolve(ok["options"])
    assert again["faces"] == 15000 and again["faces_exact"] and again["size"] == "1K", "OK gives the same picks"


def test_asset_options_gives_the_one_question():
    res = ACTIONS["asset_options"].fn(Ctx(), {"ask": True, "choice": {"made_for": "roblox"}})
    assert res["question"] == ROBLOX_QUESTION, res
    assert res["on_ok"]["confirmed"] is True and res["on_ok"]["options"]["made_for"] == "roblox"
    assert "make_game_ready" in res["next"]
    assert bpy.context.scene.get(presets.KEY) is None, "ask: true stores nothing"
    menu = ACTIONS["asset_options"].fn(Ctx(), {})
    assert menu["question"].endswith("OK, or change something?") and menu["questions"] and menu["presets"]
    # the public tool gives the same question with ask: true
    res = TOOLS["make_game_ready"].fn(Ctx(), {"ask": True, "options": {"made_for": "roblox"}})
    assert res["question"] == ROBLOX_QUESTION, res


def test_the_pick_list_form_has_every_option_with_the_defaults():
    f = presets.form(presets.resolve({"made_for": "roblox"}))
    keys = [x["key"] for x in f["fields"]]
    assert keys == ["mesh", "faces", "textures", "size", "made_for", "colors"], keys
    faces = next(x for x in f["fields"] if x["key"] == "faces")
    assert faces["default"] == 15000 and faces["type"] == "integer"


def test_make_game_ready_refuses_without_confirmation_and_the_refusal_is_the_question():
    bpy.ops.mesh.primitive_cube_add()
    before = len(bpy.data.objects)
    text = _refusal({"object": "Cube", "options": {"made_for": "roblox"}})
    lines = text.split("\n")
    assert lines[0].startswith("Not started: ask the person first"), text
    assert lines[1] == ROBLOX_QUESTION, lines
    assert '"confirmed": true' in lines[2] and '"faces": 15000' in lines[2], lines[2]
    text = _refusal({"object": "Cube"})
    assert text.split("\n")[1] == presets.question(presets.resolve()), text
    text = _refusal({"object": "Cube", "confirmed": True})
    assert text.startswith("Not started: confirmed needs the picks"), text
    assert len(bpy.data.objects) == before, "nothing ran"
    ok = presets.on_ok(presets.resolve({"made_for": "roblox"}))
    try:
        ACTIONS["make_game_ready"].fn(Ctx(), {"object": "Cube", **ok})
        raise AssertionError("no job runner here")
    except ToolError as err:
        assert "job runner" in str(err), str(err)
    for args, part in (({}, "Give the model"),
                       ({"file": "C:/nope/model.glb"}, "There is no file"),
                       ({"file": "relative.glb"}, "full path"),
                       ({"object": "Nope"}, "No mesh object"),
                       ({"object": "Cube", "file": "C:/x.glb"}, "only one"),
                       ({"object": "Cube", "options": {"colour": "red"}}, "unknown"),
                       ({"prompt": "a sci-fi gun"}, "Give the model")):
        try:
            ACTIONS["make_game_ready"].fn(Ctx(), dict(args, confirmed=True))
            raise AssertionError(f"accepted {args}")
        except ToolError as err:
            assert part in str(err), (args, str(err))


def test_no_generation_anywhere():
    names = set(ACTIONS) | set(TOOLS)
    for gone in ("generate_3d", "generate_image", "generate_views", "engine_check", "engine_setup", "engine_status",
                 "make_asset", "instant_meshes_setup"):
        assert gone not in names, gone
    for t in TOOLS.values():
        for word in ("generate_3d", "local AI", "engine_setup"):
            assert word not in t.description, (t.name, word)


def test_run_python_reminds_when_it_fills_an_empty_scene():
    code = "import nighty as n\nfor i in range(6):\n    n.box(0.1, at=(i * 0.2, 0, 0.05), name=f'B{i}')"
    blocks = ACTIONS["run_python"].fn(Ctx(), {"code": code})
    note = blocks[-1]["text"]
    assert note.startswith("Note: models come from the person's file"), note
    assert "only when the person asked" in note, note
    # a small fix in a scene that has a model already: no note
    blocks = ACTIONS["run_python"].fn(Ctx(), {"code": "result = 1"})
    assert not any(b["text"].startswith("Note:") for b in blocks), blocks
