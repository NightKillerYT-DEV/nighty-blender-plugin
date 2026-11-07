# SPDX-License-Identifier: GPL-3.0-or-later
# Writes guides/library.md (the nighty library reference, from its docstrings) and guides/guides.json (the guide
# list the MCP program serves as resources nighty-blender://guide/<topic>). Inside Blender:
#   blender -b --factory-startup --python scripts/gen_guides.py [-- --check]

import importlib
import inspect
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDES = os.path.join(ROOT, "guides")
sys.path.insert(0, os.path.join(ROOT, "addon"))

ORDER = [("core", "Settings, sides, objects, bounds"), ("shapes", "Shapes"), ("modify", "Finishing and editing"),
         ("place", "Placing parts"), ("assemble", "Parts and merging"), ("details", "Ready-made details"),
         ("kit", "Detail kit (secondary and tertiary detail)"), ("surface", "Surfaces (procedural materials)"),
         ("paint", "Quick materials"), ("check", "Checks and measurements"), ("compat", "Version shims (n.compat)")]
URI = "nighty-blender://guide/{}"

INTRO = """# The nighty library
Every function of `import nighty as n` (inside run_python), with its arguments and an example.

Meters, Z up, front is -Y, right is +X. Shapes are centered on `at`, keep scale 1 and get enough sides for their
size (`n.settings(detail, size)` sets how fine). Most functions take objects or their names, alone or in a list.
`n.help()` lists everything inside Blender; `n.help("cylinder")` shows one.
"""


def library_text():
    import nighty_blender.nighty as n
    out = [INTRO]
    for mod_name, title in ORDER:
        mod = importlib.import_module(n.__name__ + "." + mod_name)  # (n.surface is a function)
        names = list(getattr(mod, "__all__", []))
        if mod_name == "compat":
            names = [k for k, v in vars(mod).items() if inspect.isfunction(v) and not k.startswith("_")
                     and v.__module__ == mod.__name__]
        if not names:
            continue
        out.append(f"\n## {title}\n")
        prefix = "n.compat." if mod_name == "compat" else "n."
        for name in names:
            fn = getattr(mod, name)
            if inspect.isclass(fn):
                doc = inspect.getdoc(fn) or ""
                out.append(f"### {prefix}{name}\n{doc}\n")
                continue
            if not callable(fn):
                continue
            try:
                sig = str(inspect.signature(fn))
            except (TypeError, ValueError):
                sig = "(...)"
            doc = inspect.getdoc(fn) or ""
            out.append(f"### {prefix}{name}{sig}\n{doc}\n")
    return "\n".join(out).rstrip() + "\n"


def manifest():
    rows = []
    for f in sorted(os.listdir(GUIDES)):
        if not f.endswith(".md") or f == "ai-skill.md":
            continue
        text = library_text() if f == "library.md" else open(os.path.join(GUIDES, f), encoding="utf-8").read()
        lines = text.splitlines()
        title = lines[0].lstrip("# ").strip()
        desc = next((l.strip() for l in lines[1:] if l.strip() and not l.startswith("#")), "")
        topic = f[:-3]
        rows.append({"topic": topic, "uri": URI.format(topic), "title": title, "description": desc,
                     "file": "guides/" + f, "mimeType": "text/markdown"})
    order = ["workflow", "library", "topology", "hard-surface", "props", "organic", "texturing", "blender-api"]
    rows.sort(key=lambda r: order.index(r["topic"]) if r["topic"] in order else 99)
    return json.dumps({"guides": rows, "skill": "guides/ai-skill.md"}, indent=1) + "\n"


def main(argv):
    check = "--check" in argv
    stale = []
    for name, render in (("library.md", library_text), ("guides.json", manifest)):
        path = os.path.join(GUIDES, name)
        text = render()
        current = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
        if current != text:
            stale.append(name)
            if not check:
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
    if check:
        print("out of date: " + ", ".join(stale) if stale else "guides are up to date")
        return 1 if stale else 0
    print("wrote " + (", ".join(stale) if stale else "nothing (up to date)"))
    return 0


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    code = main(a)
    sys.stdout.flush()
    sys.exit(code)
