# SPDX-License-Identifier: GPL-3.0-or-later
# Generate addon/nighty_blender/tools.json from the tool registry. Run it inside Blender so the tool modules (which
# import bpy) load:
#
#     blender -b --factory-startup --python scripts/gen_tools_json.py [-- --check]
#
# tools.json is the single list the MCP program embeds, so the AI sees the tools before Blender connects. Never edit
# it by hand; regenerate it after adding or changing a tool (a test checks it is up to date). --check writes nothing
# and exits 1 when tools.json is stale.

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.join(os.path.dirname(HERE), "addon")


def main(argv):
    if ADDON_DIR not in sys.path:
        sys.path.insert(0, ADDON_DIR)
    import nighty_blender
    loaded = nighty_blender.load_tools()
    from nighty_blender import _tools_json
    from nighty_blender.tools import TOOLS
    text = _tools_json.render()
    if "--check" in argv:
        current = open(_tools_json.path(), encoding="utf-8").read() if os.path.isfile(_tools_json.path()) else ""
        print("Nighty Blender: tools.json is %s." % ("up to date" if current == text else "OUT OF DATE"))
        return 0 if current == text else 1
    with open(_tools_json.path(), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print("Nighty Blender: wrote tools.json with %d tools (modules: %s)."
          % (len(TOOLS), ", ".join(sorted(loaded))))
    return 0


if __name__ == "__main__":
    code = main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    sys.stdout.flush()
    sys.exit(code)
