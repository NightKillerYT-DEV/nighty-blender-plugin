# SPDX-License-Identifier: GPL-3.0-or-later
# The tool registry (the contract between the addon's link and the tools; see docs/PROTOCOL.md).
#
# Two layers:
#   ACTIONS  the working steps (cleanup_mesh, retopo, bake, export_asset...), each registered with @action in
#            addon/nighty_blender/tools/<area>.py. They call each other through tools/_chain.run_tool (a whole
#            pipeline such as make_game_ready runs them in order). They are not shown to the AI one by one.
#   TOOLS    the 15 public tools the AI sees (status, scene, look, measure, check, reference, import, mesh, texture,
#            make_game_ready, export, run_python, undo, job, guide), registered with @tool in tools/public.py. Most
#            route to an action by `op`. Nighty Vault adds the "blender_" prefix (plugin/plugin.json).
#
# A module does:
#
#     from . import action, text, image, ToolError
#
#     @action("measure", "Bounding boxes and sizes of objects, in meters.",
#             {"type": "object", "properties": {"names": {"type": "array", "items": {"type": "string"}}}})
#     def measure(ctx, args):
#         return {"objects": [...]}          # a dict / list -> one JSON text block
#         # or return [text("..."), image(png_bytes)]   # MCP content blocks
#
# The addon's dispatcher calls TOOLS[name].fn(ctx, args) on Blender's main thread, wraps a scene-changing call
# (changes=True) in ONE undo step named "AI: <tool>" (ctx.undo_label can refine it), and turns a ToolError into an
# error result the AI can read and fix. A slow step (slow=True) calls ctx.start_job(step_fn, label) and returns
# {"job": id} at once (the AI waits with job { action: "wait" }).
# tools.json (next to this folder) is GENERATED from TOOLS (scripts/gen_tools_json.py, run inside Blender): never
# edit it by hand. plugin/plugin.json's mcp.tools is generated from it too (scripts/gen_plugin_json.py).

import base64
import json

TOOLS = {}     # the public tools (what the AI sees)
ACTIONS = {}   # the working steps the public tools route to
LEVELS = ("tools", "safe", "full")  # tools only < safe Python < full Python (the person picks it in the panel)


class ToolError(Exception):
    """A refusal or a failure the AI should read (its message goes back as an error result)."""


class Tool:
    __slots__ = ("name", "description", "input_schema", "slow", "level", "changes", "fn", "annotations")

    def __init__(self, name, description, input_schema, slow, level, changes, fn):
        self.name, self.description, self.input_schema = name, description, input_schema
        self.slow, self.level, self.changes, self.fn = slow, level, changes, fn
        self.annotations = None

    def spec(self):
        out = {"name": self.name, "description": self.description, "inputSchema": self.input_schema,
               "slow": self.slow, "level": self.level, "changes": self.changes}
        if self.annotations:
            out["annotations"] = self.annotations
        return out


def _registrar(registry, kind, name, description, input_schema, slow, level, changes):
    if level not in LEVELS:
        raise ValueError(f"{kind} {name!r}: level must be one of {LEVELS}")

    def register(fn):
        if name in registry:
            raise ValueError(f"{kind} {name!r} registered twice")
        schema = input_schema or {"type": "object", "properties": {}}
        registry[name] = Tool(name, description, schema, slow, level, changes, fn)
        return fn
    return register


def tool(name, description, input_schema=None, *, slow=False, level="tools", changes=True):
    """Registers a public tool. level: the lowest safety level that may call it. changes: False for read-only."""
    return _registrar(TOOLS, "tool", name, description, input_schema, slow, level, changes)


def action(name, description, input_schema=None, *, slow=False, level="tools", changes=True):
    """Registers a working step (internal; the public tools route to it)."""
    return _registrar(ACTIONS, "action", name, description, input_schema, slow, level, changes)


def specs():
    """Every public tool's spec, sorted by name (what tools.json holds)."""
    return [TOOLS[name].spec() for name in sorted(TOOLS)]


def text(value):
    return {"type": "text", "text": value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))}


def image(png_bytes, mime="image/png"):
    return {"type": "image", "data": base64.b64encode(png_bytes).decode("ascii"), "mimeType": mime}


def content(result):
    """A tool's return value as MCP content blocks."""
    if result is None:
        return [text("done")]
    if isinstance(result, list) and all(isinstance(b, dict) and "type" in b for b in result):
        return result
    return [text(result)]
