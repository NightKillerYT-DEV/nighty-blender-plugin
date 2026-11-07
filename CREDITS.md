<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Credits and notices

Nighty Blender is Copyright 2026 NightyCode and licensed GPL-3.0-or-later (`LICENSE`,
`LICENSES/GPL-3.0-or-later.txt`). This file lists the third-party parts it ships, uses or downloads, each with its
own license. Every license text is in `LICENSES/` (REUSE style; `REUSE.toml` maps files to licenses).

## Shipped in this repository

### xatlas-python 0.0.11 and xatlas (MIT)
`addon/nighty_blender/wheels/*.whl`, unmodified wheels from PyPI.
Copyright (c) 2021 Markus Worchel (xatlas-python); Copyright (c) 2018-2020 Jonathan Young (xatlas, which builds on
thekla_atlas and NVIDIA Texture Tools, both MIT). License: `LICENSES/MIT.txt`; the upstream notice is also in
`addon/nighty_blender/wheels/LICENSE-xatlas-upstream.txt`.

### libarchive test archive (BSD-2-Clause), test data only
`tests/io/fixtures/libarchive_bcj2_lzma2.7z` (libarchive's `test_read_format_7zip_bcj2_lzma2_2.7z`, uudecoded).
Copyright (c) 2011 Michihiro NAKAJIMA. License: `LICENSES/BSD-2-Clause.txt`. Never part of the add-on or plugin.

### Guides, examples and skills
The guide texts (`guides/`), the 40 example scripts and their renders (`examples/`) and the four AI skills
(`skills/`: nighty-blender-modeling, nighty-blender-fix-model, nighty-blender-procedural, nighty-blender-rigging,
with their `references/`) are NightyCode's own work, GPL-3.0-or-later like the rest. No text, code or skill is adapted
from scenario-labs/skills (MIT, Copyright (c) 2026 Scenario Inc.) or any other third-party skill collection; the
procedural skill notes that some general techniques were learned from it, as ideas only. If that ever changes, its
notice and `LICENSES/MIT.txt` reference go here. Roblox and vendor facts in the skills (R15 names and budgets, FACS
pose names, Tripo / Meshy / Rodin plan terms) are facts read from their public documentation, not copied text.

### Oklab
Two 3x3 matrices from Bjorn Ottosson's Oklab (public domain, or MIT where that doesn't apply), written into
`addon/nighty_blender/nighty/colors/palette.py`. License: `LICENSES/MIT.txt`.

## Downloaded only when the person asks (not in this repository)

### Instant Meshes (BSD-3-Clause with an "Enhancements" clause)
The plugin's *Get Instant Meshes* button (and the add-on's own downloader) fetch the official, unmodified Windows build
from `https://instant-meshes.s3.eu-central-1.amazonaws.com/Release/instant-meshes-windows.zip` (zip SHA-256
`c9f6217e83ea90f98a8cd54cf82dac88420df20cf197e7a4ef2bef81c5ae068d`, program SHA-256
`f1fe5b5f56d1002ae61dbd76a3fd646229fc1fe15322e7a3744f8ce442c76b2d`), next to a SOURCE.txt naming its source and
license. Project: https://github.com/wjakob/instant-meshes. We don't modify or bundle it, and its authors don't
endorse Nighty Blender.

    Copyright (c) 2015 Wenzel Jakob, Daniele Panozzo, Marco Tarini, and Olga Sorkine-Hornung. All rights reserved.

    Redistribution and use in source and binary forms, with or without modification, are permitted provided that
    the following conditions are met:

    1. Redistributions of source code must retain the above copyright notice, this list of conditions and the
       following disclaimer.
    2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the
       following disclaimer in the documentation and/or other materials provided with the distribution.
    3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote
       products derived from this software without specific prior written permission.

    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED
    WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
    PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY
    DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
    PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
    CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
    OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
    DAMAGE.

    You are under no obligation whatsoever to provide any bug fixes, patches, or upgrades to the features,
    functionality or performance of the source code ("Enhancements") to anyone; however, if you choose to make your
    Enhancements available either publicly, or directly to the authors of this software, without imposing a
    separate written license agreement for such Enhancements, then you hereby grant the following license: a
    non-exclusive, royalty-free perpetual license to install, use, modify, prepare derivative works, incorporate
    into other computer software, distribute, and sublicense such enhancements or derivative works thereof, in
    binary and source code form.

(The text above follows the project's LICENSE.txt; that file is the authority. The general BSD-3-Clause text is also
in `LICENSES/BSD-3-Clause.txt`.)

### CC0 textures (Poly Haven, ambientCG)
Downloaded on demand only after the person agrees, with a license.json naming the source next to each set. CC0 1.0
(public domain dedication): no notice is required; we credit the sources anyway.

## Used, not shipped
Blender (GPL; its glTF / FBX / OBJ importers and QuadriFlow, MIT upstream) runs the add-on. Optional remeshers
(QuadWild, QRemeshify: GPL-3.0; Quad Remesher: commercial) are only used or reported when the person installed them.
Full table: `docs/THIRD-PARTY.md`.
