# SPDX-License-Identifier: GPL-3.0-or-later
# Every example script runs in a fresh scene, passes verify_mesh, and its stored verify.json / render.png match.

FRESH_SCENE = True  # tests/run.py: an empty factory scene before each test

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples")


def _builder():
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_examples", os.path.join(ROOT, "scripts", "build_examples.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _names():
    return sorted(x for x in os.listdir(EXAMPLES) if os.path.isfile(os.path.join(EXAMPLES, x, "script.py")))


def test_examples_have_files_and_docs():
    names = _names()
    assert len(names) >= 30
    import re
    styles = {"realistic": 0, "stylized": 0}
    for name in names:
        d = os.path.join(EXAMPLES, name)
        for f in ("script.py", "render.png", "render.jpg", "wire.png", "verify.json"):
            assert os.path.isfile(os.path.join(d, f)), (name, f)
        script = open(os.path.join(d, "script.py"), encoding="utf-8").read()
        assert script.startswith("# SPDX-License-Identifier: GPL-3.0-or-later\n"), name
        script = script.split("\n", 1)[1]
        assert script.startswith('"""'), name
        doc = script.split('"""')[1]
        assert "\ntags:" in doc, name
        tags = [t.strip() for t in doc.split("\ntags:")[1].split("\n")[0].split(",")]
        style = [s for s in styles if s in tags]
        assert len(style) == 1, (name, "tags need exactly one of realistic / stylized")
        styles[style[0]] += 1
        assert "\nbudget:" in doc, (name, "a game triangle budget line")
        assert "import nighty as n" in script, name
        for bad in ("import os", "import sys", "subprocess", "open(", "__import__", "exec(", "eval("):
            assert bad not in script, (name, bad)
        imports = re.findall(r"^\s*(?:import|from)\s+(\w+)", script, re.M)
        assert set(imports) <= {"nighty", "math", "random", "bpy", "bmesh", "mathutils"}, (name, imports)
        rep = json.load(open(os.path.join(d, "verify.json"), encoding="utf-8"))
        assert rep["pass"] is True and not rep["errors"], name
        assert rep.get("budget") and rep["triangles"] <= rep["budget"] <= 20000, (name, rep.get("budget"))
        assert open(os.path.join(d, "render.png"), "rb").read(8) == b"\x89PNG\r\n\x1a\n"
        jpg = open(os.path.join(d, "render.jpg"), "rb").read()
        assert jpg[:3] == b"\xff\xd8\xff" and len(jpg) < 200_000, (name, "render.jpg: run scripts/example_thumbs.py")
    assert min(styles.values()) >= 12, styles     # about half realistic, half stylized


def test_every_example_builds_and_passes():
    b = _builder()
    failed = []
    for name in _names():
        objs = b.run_example(name)
        rep = b.n.verify(objs, **b.options(name))
        if not rep["pass"]:
            failed.append((name, rep["errors"][:2]))
        stored = json.load(open(os.path.join(EXAMPLES, name, "verify.json"), encoding="utf-8"))
        if rep["triangles"] > stored["budget"]:
            failed.append((name, f"triangles {rep['triangles']} over the budget {stored['budget']}"))
        if abs(stored["triangles"] - rep["triangles"]) > max(50, stored["triangles"] * 0.02):
            failed.append((name, f"triangles {rep['triangles']} vs stored {stored['triangles']} (rebuild it)"))
    assert not failed, failed


def test_examples_run_at_the_safe_level():
    """The AI runs these through run_python at the default 'safe' level: every script must pass its checks."""
    import ast
    from nighty_blender.tools import core
    for name in _names():
        script = open(os.path.join(EXAMPLES, name, "script.py"), encoding="utf-8").read()
        core._check_safe(ast.parse(script))
    from _util import call
    script = open(os.path.join(EXAMPLES, "crate_wooden", "script.py"), encoding="utf-8").read()
    call("run_python", {"code": script}, level="safe")
    import bpy
    assert "Frame" in bpy.data.objects and "Boards" in bpy.data.objects
