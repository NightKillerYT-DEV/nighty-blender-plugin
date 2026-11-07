# SPDX-License-Identifier: GPL-3.0-or-later
# Writes plugin/plugin.json from the add-on: its version (blender_manifest.toml) and the `mcp` field (the 15 public
# tools from addon/nighty_blender/tools.json, as the Nighty Vault plugin contract wants them: name, description,
# inputSchema, annotations; prefix "blender"; the note). Plain Python, no Blender needed:
#
#     python scripts/gen_plugin_json.py [--check]
#
# --check writes nothing and exits 1 when plugin.json is out of date (a test runs it too).

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ADDON = os.path.join(ROOT, "addon", "nighty_blender")
PLUGIN_JSON = os.path.join(ROOT, "plugin", "plugin.json")

NOTE = ("Nighty Blender drives the person's own Blender (4.2+), paired in Nighty Vault's Blender card. Models come "
        "from the person's file, an import, or code only when the person asks: there is no AI model in it and it "
        "never generates one. Start with blender_status; read blender_guide { topic: \"workflow\" } once. New file: "
        "blender_import, then blender_make_game_ready (ask its one options question first). Slow tools "
        "answer with a job id: blender_job { action: \"wait\" }. Each change is one undo step \"AI: ...\"; "
        "blender_undo takes back only yours. The safety level is the person's, set in Blender only.")

BASE = {
    "format": 1,
    "id": "nighty-blender",
    "name": "Nighty Blender",
    "author": "NightyCode",
    "description": ("Your Blender, for the AI in Nighty Vault: import a model, make it game-ready (exact triangle "
                    "count, UVs, textures, checks, export for Roblox and other engines). No AI model inside: "
                    "models come from you."),
    "minAppVersion": "0.3.3",
    "entry": "main.js",
    "icon": "icon.svg",
    "permissions": ["system", "panel", "storage"],
    "network": ["github.com", "objects.githubusercontent.com", "instant-meshes.s3.eu-central-1.amazonaws.com"],
    "homepage": "https://github.com/NightKillerYT-DEV/nighty-blender-plugin",
    "repository": "https://github.com/NightKillerYT-DEV/nighty-blender-plugin",
    "license": "GPL-3.0-or-later",
    "tags": ["blender", "3d", "game-ready", "roblox"],
}


def addon_version():
    with open(os.path.join(ADDON, "blender_manifest.toml"), encoding="utf-8") as f:
        return re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M).group(1)


def render():
    with open(os.path.join(ADDON, "tools.json"), encoding="utf-8") as f:
        specs = json.load(f)
    tools = []
    for spec in specs:
        row = {"name": spec["name"], "description": spec["description"], "inputSchema": spec["inputSchema"]}
        if spec.get("annotations"):
            row["annotations"] = spec["annotations"]
        tools.append(row)
    data = dict(BASE)
    data["version"] = addon_version()
    data["mcp"] = {"prefix": "blender", "note": NOTE, "tools": tools}
    order = ["format", "id", "name", "author", "version", "description", "minAppVersion", "entry", "icon",
             "permissions", "network", "homepage", "repository", "license", "tags", "mcp"]
    return json.dumps({k: data[k] for k in order}, indent=2, ensure_ascii=False) + "\n"


def check(text):
    data = json.loads(text)
    m = data["mcp"]
    problems = []
    if len(m["note"]) > 600:
        problems.append("note over 600 characters (%d)" % len(m["note"]))
    if len(m["tools"]) != 15:
        problems.append("%d tools, not 15" % len(m["tools"]))
    for t in m["tools"]:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", t["name"]) or len("blender_" + t["name"]) > 56:
            problems.append("bad name " + t["name"])
        if not 0 < len(t["description"]) <= 1024:
            problems.append("description of %s is %d characters" % (t["name"], len(t["description"])))
        if t["inputSchema"].get("type") != "object":
            problems.append("inputSchema of %s is not an object" % t["name"])
    if len(json.dumps(m["tools"], ensure_ascii=False).encode("utf-8")) > 64 * 1024:
        problems.append("tool JSON over 64 KB")
    if len(data["description"]) > 300:
        problems.append("description over 300 characters")
    return problems


def main(argv):
    text = render()
    problems = check(text)
    if problems:
        print("plugin.json breaks the Nighty Vault rules: " + "; ".join(problems))
        return 1
    if "--check" in argv:
        current = open(PLUGIN_JSON, encoding="utf-8").read() if os.path.isfile(PLUGIN_JSON) else ""
        print("plugin.json is %s." % ("up to date" if current == text else "OUT OF DATE"))
        return 0 if current == text else 1
    with open(PLUGIN_JSON, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("wrote plugin/plugin.json (%d tools, note %d characters)." % (15, len(NOTE)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
