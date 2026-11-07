# Nighty Blender (Nighty Vault plugin)

Your Blender, for the AI in Nighty Vault. Import a model and make it game-ready: the exact triangle count, UVs,
textures, checks, and an export for Roblox, Unity, Unreal, Godot or glTF. There is no AI model inside: models come
from your file, an import, or code only when you ask for it.

- **Install the add-on:** the card's *Install / update add-on* downloads the pinned add-on, checks its SHA-256 and
  installs it into your newest Blender (4.2 or newer). If that fails, drag the zip into Blender.
- **Pair once:** in Blender press N, open the *Nighty* tab and press *Connect to Nighty Vault*. Then press *Pair* in
  the card and type the 6-digit code it shows into Blender. The pairing token stays in this plugin's own folder,
  outside your vault.
- **Use it:** any AI app connected to Nighty Vault gets the 15 `blender_*` tools in new chats.
- **Safety:** Blender listens on 127.0.0.1 only and does nothing before pairing; 5 wrong codes lock pairing. How much
  the AI may do (tools only / safe Python / full Python) is set in Blender only.
- **Extras:** *Get Instant Meshes* (a better quad remesher, BSD license, hash-checked), *Install AI skills*, and
  *Move from Nighty Blender 1.x* (removes the old add-on, offers to clean the old AI-app entries with a backup, and to
  send the old engine folder to the Recycle Bin; nothing happens without your second click).

GPL-3.0-or-later. Source: https://github.com/NightKillerYT-DEV/nighty-blender-plugin

<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
