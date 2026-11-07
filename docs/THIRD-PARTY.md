# Third-party pieces and their licenses (Nighty Blender 2)

Nighty Blender itself is GPL-3.0-or-later (LICENSES/GPL-3.0-or-later.txt). It has no AI model and downloads none.

| Piece | License | Bundled? | Notes |
|---|---|---|---|
| Blender (bpy, the glTF / FBX / OBJ importers, QuadriFlow inside it) | GPL (Blender), MIT (QuadriFlow upstream) | No: the person's own Blender 4.2+ | The add-on runs inside it; imports run in a background Blender. |
| xatlas 0.0.11 (mworchel/xatlas-python, wraps jpcy/xatlas) | MIT (Copyright 2021 Markus Worchel; 2018-2020 Jonathan Young) | Yes: 8 wheels in `addon/nighty_blender/wheels/` (CPython 3.11 + 3.13 for Windows x64, macOS arm64 / x64, Linux x64), SHA-256 checked against PyPI; Blender installs the one that fits | UV charts and packing, run in Blender's own python.exe (never imported inside Blender). Upstream notice: `wheels/LICENSE-xatlas-upstream.txt`. |
| Instant Meshes (wjakob/instant-meshes) | BSD-3-Clause style + an "Enhancements" clause (Copyright 2015 Jakob, Panozzo, Tarini, Sorkine-Hornung) | No: the plugin's *Get Instant Meshes* button downloads the official Windows build on the person's click, SHA-256 pinned (zip c9f6217e..., program f1fe5b5f...), with a SOURCE.txt naming the source and license | A faster quad remesher; Blender's QuadriFlow is used without it. Not modified. |
| Poly Haven / ambientCG textures | CC0 | No: downloaded on demand only after the person agrees (`assign_materials` with `cc0`) | A license.json with the source page is kept next to each set. |
| Blender's studio light HDRIs | CC0 | No (read from the person's Blender) | Lighting for `look` material renders. |
| Oklab (Bjorn Ottosson) | Public domain / MIT | Two 3x3 matrices in our own code (nighty/colors/palette.py) | Perceptual color distances. |
| QuadWild, QRemeshify, Quad Remesher | GPL-3.0 / GPL-3.0 / commercial | No: only used or reported when the person installed them | Optional remeshers. |
| libarchive test archive (tests/io/fixtures) | BSD-2-Clause | Test data only | Checks the 7z unpacker. |

Removed in 2.0: the local AI engine and every model it downloaded, and the
optional cloud 3D services. None of their code or files remain in the add-on.
