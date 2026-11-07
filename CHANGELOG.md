# Changelog

## 2.0.0

Nighty Blender becomes a Nighty Vault plugin, and goes **import first**.

- **No AI model inside, and no generation.** Models come from the person's file, an import, or code only when the
  person asks. Removed: the local AI engine (its setup, downloads, ComfyUI runtime and every model it used) and the
  optional cloud 3D services (Tripo, Meshy, Rodin) with their keys. This note is the only place those names remain.
- **15 tools** (`blender_*` in Nighty Vault): status, scene, look, measure, check, reference, import, mesh, texture,
  make_game_ready, export, run_python, undo, job, guide.
- **import**: GLB, glTF, FBX and OBJ through a background Blender, a locked `_SOURCE` copy and a triage report.
- **make_game_ready**: the old make_asset pipeline, on an imported file or a scene mesh.
- **check**: mesh, textures, source (drift against the `_SOURCE` copy), roundtrip (export and read back), roblox,
  final. New mesh / texture steps: fix_shading, fix_seams.
- **The add-on listens** (127.0.0.1:47871-47873, subprotocol `nighty-blender.v2`) and pairs with the plugin: a 6-digit
  code typed in Blender, HMAC proofs both ways, a 32-hex token, 5 wrong codes lock it, 16 MB cap. Nothing works
  before pairing. See docs/PROTOCOL.md.
- **The plugin** installs and updates the add-on (pinned SHA-256), gets Instant Meshes (pinned), installs the AI
  skills, and helps moving from 1.x. The Node MCP program, its updater and the website downloads are retired.
- Guides rewritten for import first; the 40 examples are kept.

## 1.0.2

The last version with the Node program (`nighty-blender-mcp.mjs`) and the local AI engine. Frozen.
