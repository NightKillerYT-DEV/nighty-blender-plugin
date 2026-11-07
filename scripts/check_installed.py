# SPDX-License-Identifier: GPL-3.0-or-later
# Inside a Blender where the built Nighty Blender extension is installed and enabled (scripts/build_extension.py
# --check-install runs it with that throwaway user folder): the installed copy's knowledge and modeling tools work.
# Prints "INSTALLED OK" and exits 0, or the problem and exits 1.
#
#     blender -b --python scripts/check_installed.py

import json
import os
import sys
import traceback

import bpy


class Ctx:
    def __init__(self, level="safe"):
        self.undo_label = None
        self.level = level


def main():
    package = next((name for name in sys.modules if name.endswith(".nighty_blender") and name.startswith("bl_ext.")),
                   None)
    assert package, "the extension is not enabled (no bl_ext.*.nighty_blender module)"
    tools = sys.modules[package + ".tools"]
    assert "nighty" not in sys.modules, "the extension added a top-level module 'nighty' (Blender policy)"
    root = os.path.dirname(sys.modules[package].__file__)
    report = {"package": package, "folder": root}

    def call(name, args, level="safe"):
        return tools.content(tools.TOOLS[name].fn(Ctx(level), args))

    listing = call("guide", {})[0]["text"]
    assert "workflow" in listing and "library" in listing, listing
    guide = call("guide", {"topic": "hard-surface"})[0]["text"]
    assert guide.startswith("# Hard-surface"), guide[:80]
    found = json.loads(call("guide", {"examples": "wooden crate", "limit": 1, "image": True})[0]["text"])
    assert found["results"] and found["results"][0]["name"] == "crate_wooden", found
    report["guides_dir"] = os.path.isdir(os.path.join(root, "guides"))
    report["examples"] = len(os.listdir(os.path.join(root, "examples")))
    out = call("run_python", {"code": "import nighty as n\nb = n.box((0.4, 0.3, 0.2), at=(0, 0, 0.1), name='Kit')\n"
                                      "n.panel_cut(b, '-Y', size=(0.2, 0.1))\nn.bevel(b)\nresult = n.verify(b)['pass']"})
    assert out[-1]["text"].strip().lower() == "true", out
    full = call("run_python", {"code": "import nighty\nresult = nighty.__name__"}, level="full")
    assert package + ".nighty" in full[-1]["text"], full
    look = call("look", {"names": ["Kit"], "wireframe": True, "size": 96})
    assert look[1]["type"] == "image", look[0]
    verify = json.loads(call("check", {"what": "mesh", "names": ["Kit"]})[0]["text"])
    assert verify["pass"], verify
    # the xatlas wheel Blender installed with the extension: found (not imported here) and working in python.exe
    xa = sys.modules.get(package + ".nighty.mesh.xa") or __import__(package + ".nighty.mesh.xa", fromlist=["xa"])
    assert xa.available(), "the xatlas wheel was not installed with the extension"
    uvs = xa.run([([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [(0, 1, 2), (0, 2, 3)])], resolution=256, padding=2)
    assert len(uvs[0]) == 1 and len(uvs[0][0][2]) >= 4, uvs
    assert "xatlas" not in sys.modules, "xatlas must not be imported inside Blender (crashes 4.2)"
    report["xatlas"] = xa.module_dir()
    assert len(tools.TOOLS) == 15, sorted(tools.TOOLS)
    report["tools"] = len(tools.TOOLS)
    print("INSTALLED OK " + json.dumps(report))


try:
    main()
except Exception:  # noqa: BLE001
    traceback.print_exc()
    print("INSTALLED FAILED")
    sys.stdout.flush()
    sys.exit(1)
sys.stdout.flush()
