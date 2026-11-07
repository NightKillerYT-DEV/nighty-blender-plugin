# SPDX-License-Identifier: GPL-3.0-or-later
# The guides: present, generated parts up to date, short, plain ASCII with nothing hidden, and every library call,
# example and tool they name exists.

FRESH_SCENE = True  # tests/run.py: an empty factory scene before each test

import importlib.util
import json
import os
import re

from _util import n, registry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDES = os.path.join(ROOT, "guides")
TOPICS = ["workflow", "library", "topology", "hard-surface", "props", "organic", "texturing", "blender-api"]


def _gen():
    spec = importlib.util.spec_from_file_location("gen_guides", os.path.join(ROOT, "scripts", "gen_guides.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _texts():
    out = {}
    for f in os.listdir(GUIDES):
        if f.endswith(".md"):
            out[f] = open(os.path.join(GUIDES, f), encoding="utf-8").read()
    return out


def test_topics_and_manifest():
    gen = _gen()
    assert open(os.path.join(GUIDES, "library.md"), encoding="utf-8").read() == gen.library_text(), \
        "library.md is stale: run scripts/gen_guides.py"
    assert open(os.path.join(GUIDES, "guides.json"), encoding="utf-8").read() == gen.manifest(), \
        "guides.json is stale: run scripts/gen_guides.py"
    man = json.load(open(os.path.join(GUIDES, "guides.json"), encoding="utf-8"))
    assert [g["topic"] for g in man["guides"]] == TOPICS
    for g in man["guides"]:
        assert g["uri"] == f"nighty-blender://guide/{g['topic']}" and g["title"] and g["description"]
    assert os.path.isfile(os.path.join(GUIDES, "ai-skill.md"))


def test_short_plain_and_nothing_hidden():
    for name, text in _texts().items():
        limit = 60000 if name == "library.md" else 9000
        assert len(text) < limit, (name, len(text))
        assert all(ord(c) < 128 for c in text), (name, [c for c in text if ord(c) >= 128][:5])
        assert "<!--" not in text and "<script" not in text.lower(), name
        assert text.startswith("# "), name


def test_named_calls_examples_and_tools_exist():
    public = set(registry().TOOLS)
    tools = public | {"blender_" + t for t in public} | set(registry().ACTIONS)
    examples = set(os.listdir(os.path.join(ROOT, "examples")))
    for name, text in _texts().items():
        for call in set(re.findall(r"\bn\.compat\.([a-z_]+)", text)):
            assert hasattr(n.compat, call), (name, "n.compat." + call)
        for call in set(re.findall(r"\bn\.([a-z_]+)\b", text)) - {"compat"}:
            assert hasattr(n, call), (name, "n." + call)
        for word in set(re.findall(r"`([a-z_]+)`", text)):
            if word in tools or hasattr(n, word) or word in examples:
                continue
            if word.startswith(("blender_", "search_", "verify_", "finish_", "scene_", "reference_", "get_", "wait_",
                                "generate_", "engine_", "make_asset")):
                raise AssertionError((name, "unknown tool " + word))
        for word in set(re.findall(r"blender_([a-z_]+)", text)):
            assert word in public, (name, "unknown public tool blender_" + word)
        if name == "library.md":
            continue  # code samples, not example names
        named = set(re.findall(r"[A-Za-z] \(([a-z]+_[a-z_]+)[,:)]", text))  # "Crate (crate_wooden): ..."
        for line in text.splitlines():
            if "xamples:" in line:
                named |= set(re.findall(r"\b([a-z]+_[a-z_]+)\b", line.split("xamples:", 1)[1]))
        for ex in named:
            if ex in tools or hasattr(n, ex) or ex in n.place._REL:
                continue
            assert ex in examples, (name, "unknown example " + ex)


def test_skill_names_every_guide():
    skill = open(os.path.join(GUIDES, "ai-skill.md"), encoding="utf-8").read()
    for topic in TOPICS:
        assert f"/{topic}" in skill or f"guide/{topic}" in skill, topic
