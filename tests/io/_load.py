# SPDX-License-Identifier: GPL-3.0-or-later
# Loads the io package (addon/nighty_blender/nighty/io) as "nighty_io", without bpy and without the nighty library
# around it, so these tests run in plain Python and inside Blender alike.

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
IO_DIR = os.path.join(REPO, "addon", "nighty_blender", "nighty", "io")
FIXTURE = os.path.join(HERE, "fixtures", "libarchive_bcj2_lzma2.7z")


def io():
    if "nighty_io" in sys.modules:
        return sys.modules["nighty_io"]
    spec = importlib.util.spec_from_file_location("nighty_io", os.path.join(IO_DIR, "__init__.py"),
                                                  submodule_search_locations=[IO_DIR])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nighty_io"] = mod
    spec.loader.exec_module(mod)
    return mod
