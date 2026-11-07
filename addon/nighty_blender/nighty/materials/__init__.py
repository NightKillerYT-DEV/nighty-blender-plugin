# SPDX-License-Identifier: GPL-3.0-or-later
"""Smart materials per part (nighty.materials).

    from nighty import materials
    materials.assign({"Barrel": "gunmetal", "Grip": {"material": "polymer"}, "Stock": "wood"}, wear=0.35)
    materials.library.describe()        # what exists

Each part (object) gets its own material "NB <Label> · <part>", rebuilt in place when assigned again, so a recolor or
a material swap is instant. Wear and dirt come from the real geometry (edges, cavities); metallic is 0 or 1.
"""

import json

import bpy

from . import build, compat, library

STYLES = ("pbr", "stylized")


def _material_for(obj, slot_index=None):
    """The object's own Nighty material (reused when assigning again), else a new one."""
    label = f"NB · {obj.name}" if slot_index is None else f"NB · {obj.name} · {slot_index}"
    want = -1 if slot_index is None else slot_index
    for slot in obj.material_slots:
        m = slot.material
        if m is not None and m.get("nighty") and m.get("nighty_part") == obj.name and m.get("nighty_slot", -1) == want:
            if _used_elsewhere(m, obj):
                m = m.copy()   # a duplicated object shares it: change only this part
            return m
    m = compat.new_material(label)
    m["nighty_part"] = obj.name
    m["nighty_slot"] = -1 if slot_index is None else slot_index
    return m


def _used_elsewhere(mat, obj):
    for o in bpy.data.objects:
        if o is not obj and o.type == "MESH" and any(s.material is mat for s in o.material_slots):
            return True
    return False


def _set_slots(obj, mat, slot_index=None):
    if obj.type != "MESH":
        return
    if not obj.material_slots:
        obj.data.materials.append(mat)
        return
    for i, slot in enumerate(obj.material_slots):
        if slot_index is None or i == slot_index:
            slot.material = mat


def _entry(value):
    """'gunmetal' or {'material': 'painted_metal', 'color': '#556b2f', 'wear': 0.5, ...} -> dict."""
    if isinstance(value, str):
        return {"material": value}
    if isinstance(value, dict):
        return dict(value)
    raise ValueError("each part needs a material name or {material, color?, wear?, dirt?, roughness?, slot?}")


def assign(parts, style="pbr", wear=0.3, dirt=0.25, cc0_sets=None, stylize_opts=None):
    """parts: {object name: material or {material, color, force_tint, wear, dirt, roughness, slot}}. Returns a
    summary per part. force_tint: the color tints natural materials too (wood, leather); metals stay real.
    Unknown objects or materials raise ValueError with what exists."""
    if style not in STYLES:
        raise ValueError(f"style must be one of {STYLES}")
    objs = [bpy.data.objects.get(n) for n in parts]
    asset_size = asset_extent([o for o in objs if o is not None and o.type == "MESH"])
    out = []
    for name, value in parts.items():
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            raise ValueError(f"no mesh object named {name!r}")
        e = _entry(value)
        key = library.resolve(e.get("material"))
        if key is None:
            raise ValueError(f"unknown material {e.get('material')!r}; known: {', '.join(library.names())}")
        slot = e.get("slot")
        from ..bake.apply import restore_sources
        restore_sources(obj)          # after a bake: edit the procedural source again
        mat = _material_for(obj, slot)
        w = e.get("wear", wear)
        d = e.get("dirt", dirt)
        cc0 = (cc0_sets or {}).get(key)
        if style == "stylized":
            from . import stylize
            params = stylize.build_stylized(mat, key, obj, tint=e.get("color"), wear=w, dirt=d,
                                            options=e.get("stylize") or stylize_opts, asset_size=asset_size,
                                            force_tint=bool(e.get("force_tint")))
        else:
            params = build.build(mat, key, obj, wear=w, dirt=d, tint=e.get("color"), cc0_set=cc0,
                                 roughness=e.get("roughness"), asset_size=asset_size,
                                 force_tint=bool(e.get("force_tint")))
        mat.name = f"NB {library.MATERIALS[key]['label']} · {obj.name}"
        _set_slots(obj, mat, slot)
        obj["nighty_material"] = key
        out.append({"part": obj.name, "material": key, "metallic": library.MATERIALS[key]["metallic"],
                    "wear": params.get("wear"), "dirt": params.get("dirt"), "style": params.get("style"),
                    "name": mat.name})
    return out


def asset_extent(objects):
    """The diagonal of the world bounding box around all objects, in meters (1.0 when there are none)."""
    from mathutils import Vector
    pts = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    if not pts:
        return 1.0
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return max(0.01, (hi - lo).length)


def part_materials(objects):
    """{object: [Nighty material params]} for objects that have Nighty materials."""
    res = {}
    for obj in objects:
        rows = []
        for slot in obj.material_slots:
            if slot.material is not None and slot.material.get("nighty"):
                try:
                    rows.append(json.loads(slot.material["nighty"]))
                except ValueError:
                    pass
        res[obj.name] = rows
    return res
