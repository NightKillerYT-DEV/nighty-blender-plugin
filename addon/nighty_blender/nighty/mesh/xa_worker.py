# SPDX-License-Identifier: GPL-3.0-or-later
# Runs xatlas (MIT) in a plain Python process (Blender's own python.exe, no bpy): charts + packing for one or more
# triangle meshes into ONE atlas. Started by xa.py:  python -I xa_worker.py <in.npz> <out.npz> <options.json> <dir>
# <dir> is the folder that holds the xatlas module (the extension's installed wheel). Nothing else is imported.

import json
import sys
import time

import numpy as np


def main():
    inp, out, opts_path, mod_dir = sys.argv[1:5]
    sys.path.insert(0, mod_dir)
    import xatlas
    with open(opts_path, encoding="utf-8") as f:
        opts = json.load(f)
    data = np.load(inp)
    t0 = time.monotonic()
    tpu = 0.0
    for attempt in range(6):
        atlas = xatlas.Atlas()
        for i in range(opts["count"]):
            uvs = data[f"u{i}"] if f"u{i}" in data.files else None  # pack-only: keep these islands, just pack
            atlas.add_mesh(np.ascontiguousarray(data[f"v{i}"], dtype=np.float32),
                           np.ascontiguousarray(data[f"f{i}"], dtype=np.uint32),
                           uvs=None if uvs is None else np.ascontiguousarray(uvs, dtype=np.float32))
        co = xatlas.ChartOptions()
        for k, v in opts.get("chart", {}).items():
            setattr(co, k, v)
        po = xatlas.PackOptions()
        for k, v in opts.get("pack", {}).items():
            setattr(po, k, v)
        if tpu:
            po.texels_per_unit = tpu
        atlas.generate(chart_options=co, pack_options=po)
        if atlas.atlas_count <= 1:
            break
        # it spilled onto a second page: a little less texel density and try again (one texture set)
        tpu = (atlas.texels_per_unit or 1.0) * 0.85
    result = {}
    for i in range(atlas.mesh_count):
        vm, ix, uv = atlas[i]
        result[f"vm{i}"], result[f"ix{i}"], result[f"uv{i}"] = vm, ix, uv
        result[f"charts{i}"] = np.array([atlas.get_mesh_chart_count(i)])
    np.savez(out, **result)
    info = {"width": atlas.width, "height": atlas.height, "utilization": float(atlas.utilization),
            "atlas_count": atlas.atlas_count, "chart_count": atlas.chart_count,
            "texels_per_unit": float(atlas.texels_per_unit), "seconds": round(time.monotonic() - t0, 2)}
    with open(out + ".json", "w", encoding="utf-8") as f:
        json.dump(info, f)


if __name__ == "__main__":
    main()
