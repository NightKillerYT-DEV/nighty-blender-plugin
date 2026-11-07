# SPDX-License-Identifier: GPL-3.0-or-later
# Writes examples/<name>/render.jpg (512 px JPEG) from each render.png. The extension ships the JPEG, not the
# 1024 px PNG, so the addon zip stays small (the site serves files up to 25 MiB; 40 PNG renders alone were ~24 MB).
# search_examples shows render.jpg when it is there. Run it inside Blender after re-rendering examples:
#
#     blender -b --factory-startup --python scripts/example_thumbs.py [-- name ...]
#
# scripts/build_examples.py calls thumb() itself after each render.

import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(os.path.dirname(HERE), "examples")
SIZE = 512
QUALITY = 85


def thumb(png_path, jpg_path, size=SIZE):
    """A JPEG copy of png_path, at most `size` px on its long side (colors unchanged)."""
    img = bpy.data.images.load(png_path, check_existing=False)
    try:
        w, h = img.size
        k = size / max(w, h)
        if k < 1:
            img.scale(max(1, round(w * k)), max(1, round(h * k)))
        img.file_format = "JPEG"
        img.filepath_raw = jpg_path
        try:
            img.save(quality=QUALITY)
        except TypeError:  # older API without the quality argument
            img.save()
    finally:
        bpy.data.images.remove(img)


def main(names):
    done = 0
    for name in sorted(os.listdir(EXAMPLES)):
        png = os.path.join(EXAMPLES, name, "render.png")
        if (names and name not in names) or not os.path.isfile(png):
            continue
        thumb(png, os.path.join(EXAMPLES, name, "render.jpg"))
        done += 1
    print("Nighty Blender: wrote %d example thumbnails." % done)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
