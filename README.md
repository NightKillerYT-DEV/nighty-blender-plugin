# Nighty Blender

Your Blender, for the AI in [Nighty Vault](https://github.com/NightKillerYT/nighty-vault). Import a model and make it
game-ready: the exact triangle count, UVs, textures, checks, and an export for Roblox, Unity, Unreal, Godot or glTF.

**There is no AI model inside, and it never generates one.** Models come from your file, an import, or code only
when you ask for it.

## Install (from Nighty Vault)

1. In Nighty Vault: **Settings → Plugins → Install from GitHub…** and paste `NightKillerYT-DEV/nighty-blender-plugin`.
   Read the review screen (it lists all 15 tools) and tick *full access*: the plugin talks to Blender and installs
   its add-on.
2. Open the **Nighty Blender** card in the Night Panel and press **Install / update add-on**. It downloads the
   add-on, checks its SHA-256 against the one pinned in the plugin, and installs it into your newest Blender (4.2 or
   newer). If that doesn't work, drag `nighty_blender-2.0.0.zip` (from the release) into Blender.
3. In Blender press **N**, open the **Nighty** tab and press **Connect to Nighty Vault**.
4. In the card press **Pair** and type the 6-digit code into Blender's Nighty tab. Done: Blender reconnects by itself
   from now on.
5. Any AI app connected to Nighty Vault (Claude, Codex, Cursor…) gets the `blender_*` tools in new chats.

Optional, in the card: **Get Instant Meshes** (a better quad remesher, hash-checked), **Install AI skills** (the four
skills below, for Claude Code and other agents), and
**Move from Nighty Blender 1.x** (removes the old add-on; cleaning the old AI-app entries and sending the old engine
folder to the Recycle Bin each need your second click, and the config files are backed up first).

## The tools

| Tool | What it does |
|---|---|
| `blender_status` | Pairing, versions, the safety level, running jobs |
| `blender_scene` | Objects, materials, bounds |
| `blender_look` | Pictures from fixed views or a 3/4 view: solid, matcap, material, silhouette, wireframe |
| `blender_measure` | Sizes, gaps, against a reference |
| `blender_check` | mesh, textures, source (drift from the original), roundtrip, roblox, final |
| `blender_reference` | Load reference pictures, score the silhouette |
| `blender_import` | GLB, glTF, FBX, OBJ; a locked `_SOURCE` copy; a triage report |
| `blender_mesh` | cleanup, decimate, retopo, uv_unwrap, lods, split_parts, fix_shading |
| `blender_texture` | bake, clean_colors, stylize, decal, assign_materials, fix_seams |
| `blender_make_game_ready` | The whole pipeline as one job (after one options question to you) |
| `blender_export` | Roblox, Unity, Unreal, Godot, glTF, Blender |
| `blender_run_python` | Python at the safety level you set |
| `blender_undo` | Takes back only the AI's own steps; checkpoints |
| `blender_job` | Wait (45 s at a time), cancel, list |
| `blender_guide` | Guides, 40 verified examples, Blender API lookup |

## Safety

- Blender listens on 127.0.0.1 only, refuses web pages, and does nothing before pairing. Both sides prove they know
  the code (or, later, the token) with HMAC; Blender proves it first, so a fake listener is caught. 5 wrong codes
  lock pairing until you press Unlock in Blender.
- The token stays in the plugin's own folder outside your vault, and in the add-on's user folder.
- How much the AI may do (tools only / safe Python / full Python) is set in Blender's Nighty tab only.
- Every change is one undo step named "AI: …".

Details: [docs/PROTOCOL.md](docs/PROTOCOL.md).

## This repository

| Folder | What |
|---|---|
| `addon/nighty_blender/` | The Blender add-on (Blender 4.2+): the listener, pairing, the tools, the `nighty` helper library |
| `plugin/` | The Nighty Vault plugin: `plugin.json`, one `main.js`, `icon.svg` |
| `skills/` | AI skills (installed by the plugin's *Install AI skills*, or by hand from `skills.zip`): `nighty-blender-modeling`, `nighty-blender-fix-model`, `nighty-blender-procedural` (Geometry Nodes props), `nighty-blender-rigging` (R15, dynamic heads, weights) |
| `guides/`, `examples/` | The guides and the 40 verified example scripts (shipped inside the add-on) |
| `tests/` | Headless Blender tests, the plugin's Node tests |
| `scripts/` | Generators, the test launcher, the release build |
| `docs/` | The protocol and third-party licenses |

Tests (headless, in a sandbox: they never touch your own Blender settings):

```
python scripts/run_tests.py                      # the add-on, on Blender 5.2 and 4.2 when found
node tests/plugin/unit.mjs                       # the plugin's own parts
node tests/plugin/e2e.mjs "<path to blender>"    # the plugin and the real add-on together
```

Releases: pushing a tag `vX.Y.Z` runs `.github/workflows/release.yml`, which builds the add-on zip, pins its SHA-256
into the plugin, builds the `.nightyplugin`, `skills.zip` and `SHA256SUMS`, and attests them (`scripts/build_release.py`
does the same locally).

## License

GPL-3.0-or-later (see `LICENSE` and `LICENSES/`; REUSE information in `REUSE.toml`). Third-party pieces:
[docs/THIRD-PARTY.md](docs/THIRD-PARTY.md).
