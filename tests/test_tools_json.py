# SPDX-License-Identifier: GPL-3.0-or-later
# tools.json (and plugin/plugin.json's mcp.tools) must match the registry. If this fails, regenerate them:
#     blender -b --factory-startup --python scripts/gen_tools_json.py

from nighty_blender import _tools_json


def test_tools_json_is_up_to_date():
    with open(_tools_json.path(), encoding="utf-8") as handle:
        on_disk = handle.read()
    assert on_disk == _tools_json.render(), (
        "tools.json is out of date: run scripts/gen_tools_json.py and commit the result.")


PUBLIC = ("status", "scene", "look", "measure", "check", "reference", "import", "mesh", "texture", "make_game_ready",
          "export", "run_python", "undo", "job", "guide")


def test_exactly_the_15_public_tools():
    import json
    import re
    from nighty_blender.tools import TOOLS
    assert sorted(TOOLS) == sorted(PUBLIC), sorted(TOOLS)
    for t in TOOLS.values():
        # the Nighty Vault contract: names, description length, the prefixed name length
        assert re.fullmatch(r"[a-z][a-z0-9_]{0,39}", t.name), t.name
        assert len("blender_" + t.name) <= 56
        assert 0 < len(t.description) <= 1024, (t.name, len(t.description))
    assert len(json.dumps(_tools_json.render())) < 64 * 1024
    # every tool declares a level the gate understands
    from nighty_blender.tools import LEVELS, TOOLS
    for tool in TOOLS.values():
        assert tool.level in LEVELS


def test_plugin_json_is_up_to_date_and_follows_the_contract():
    import importlib.util
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location("gen_plugin_json", os.path.join(root, "scripts", "gen_plugin_json.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = mod.render()
    assert not mod.check(text), mod.check(text)
    with open(os.path.join(root, "plugin", "plugin.json"), encoding="utf-8") as handle:
        assert handle.read() == text, "plugin.json is out of date: run python scripts/gen_plugin_json.py"
    import json
    data = json.loads(text)
    assert data["permissions"] == ["system", "panel", "storage"] and data["mcp"]["prefix"] == "blender"
    assert "models come from the person's file, an import, or code only when the person asks" in \
        data["mcp"]["note"].lower()
