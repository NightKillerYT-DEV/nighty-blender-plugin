# SPDX-License-Identifier: GPL-3.0-or-later
# reference_sheet: reference pictures as scaled, view-aligned image planes (Blender image empties: shown in ortho
# views, never rendered), and a silhouette score of the model against one of them.

import math
import os

import bpy
from mathutils import Vector

from . import ToolError, image, text, action
from ..nighty import core, view
from ..nighty.shapes import subject_mask
from .scene import NAMES, targets

COLLECTION = "Nighty References"
SIDE_VIEWS = ("front", "back", "left", "right")


def reference_objects(view_name=None):
    return [o for o in bpy.data.objects if o.get("nighty_role") == "reference" and o.type == "EMPTY"
            and (view_name is None or o.get("nighty_view") == view_name)]


def _pixels(img, max_side=1024):
    px, step = view.reference_pixels(img, max_side)
    return px, step


def _bbox(mask):
    import numpy as np
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _load(spec, models):
    path = spec.get("path")
    if not path or not os.path.isfile(path):
        raise ToolError(f"Reference picture not found: {path!r} (give a full file path on this computer).")
    v = spec.get("view") or "front"
    if v not in view.VIEWS or "rot" not in view.VIEWS[v]:
        raise ToolError("view must be front, back, left, right, top or bottom.")
    try:
        img = bpy.data.images.load(path, check_existing=True)
        w, h = img.size
    except RuntimeError as error:
        raise ToolError(f"Could not read {path}: {error}")
    if not w or not h:
        raise ToolError(f"Could not read {path} (empty picture).")
    px, step = _pixels(img)
    box = _bbox(subject_mask(px))
    if box is None:
        raise ToolError(f"No subject found in {os.path.basename(path)} (use a plain or transparent background).")
    x0, y0, x1, y1 = [c * step for c in box]
    sub_w, sub_h = (x1 - x0 + step), (y1 - y0 + step)
    rot = view._view_rotation(v, Vector(), 1.0)[0]
    mat = rot.to_matrix()
    right, up, fwd = mat.col[0], mat.col[1], -mat.col[2]
    if spec.get("width"):
        m = float(spec["width"]) / sub_w
    elif spec.get("height"):
        m = float(spec["height"]) / sub_h
    elif models:
        b = core.bounds(models)
        size_u = abs(b.size.dot(Vector([abs(c) for c in right])))
        size_v = abs(b.size.dot(Vector([abs(c) for c in up])))
        m = max(size_u / sub_w, size_v / sub_h) if size_u and size_v else 1.0 / sub_w
    else:
        m = 1.0 / sub_w
    off_u = ((x0 + x1 + step) / 2.0 - w / 2.0) * m
    off_v = ((y0 + y1 + step) / 2.0 - h / 2.0) * m
    ground = spec.get("ground", v in SIDE_VIEWS)
    if spec.get("center") is not None:
        cu, cv = [float(c) for c in spec["center"]]
    elif models:
        b = core.bounds(models)
        cu, cv = b.center.dot(right), b.center.dot(up)
        if ground and v in SIDE_VIEWS:
            cv = b.min.z + sub_h * m / 2.0
    else:
        cu, cv = 0.0, (sub_h * m / 2.0 if ground and v in SIDE_VIEWS else 0.0)
    center = right * (cu - off_u) + up * (cv - off_v)
    depth = float(spec.get("distance", 2.0))
    name = f"Ref {v}"
    old = bpy.data.objects.get(name)
    if old is not None and old.get("nighty_role") == "reference":
        bpy.data.objects.remove(old, do_unlink=True)
    obj = bpy.data.objects.new(name, None)
    core.collection(COLLECTION).objects.link(obj)
    obj.empty_display_type = "IMAGE"
    obj.data = img
    obj.empty_display_size = m * max(w, h)
    obj.empty_image_offset = (-0.5, -0.5)
    obj.rotation_euler = rot
    obj.location = center + fwd * depth
    obj.empty_image_depth = "BACK"
    obj.show_empty_image_perspective = False
    obj.show_empty_image_only_axis_aligned = True
    obj.use_empty_image_alpha = True
    obj.color[3] = float(spec.get("opacity", 0.5))
    obj.hide_select = True
    obj.hide_render = True
    obj["nighty_role"] = "reference"
    obj["nighty_view"] = v
    obj["nighty_path"] = path
    sub = [round((cu - (sub_w * m) / 2.0), 4), round(cv - (sub_h * m) / 2.0, 4),
           round(cu + (sub_w * m) / 2.0, 4), round(cv + (sub_h * m) / 2.0, 4)]
    obj["nighty_subject"] = sub
    return {"name": obj.name, "view": v, "picture": os.path.basename(path),
            "subject_size_m": [round(sub_w * m, 4), round(sub_h * m, 4)],
            "subject_box_uv": sub, "meters_per_pixel": round(m, 6),
            "plane": {"right": [round(c, 3) for c in right], "up": [round(c, 3) for c in up]}}


def _score(view_name, models):
    import numpy as np
    refs = reference_objects(view_name)
    if not refs:
        raise ToolError(f"No reference loaded for the {view_name} view (action load first).")
    ref = refs[-1]
    img = ref.data
    w, h = img.size
    longest = 256
    rw, rh = (longest, max(8, int(round(longest * h / w)))) if w >= h else (max(8, int(round(longest * w / h))), longest)
    fr = view.reference_frame(ref)
    scale = ref.empty_display_size
    center = fr["center"]
    with view.Renderer(models) as r:
        shot, pose = r.shot(view_name, "silhouette", size=rw, height=rh,
                            camera={"center": center, "ortho_scale": scale})
    model = shot[..., 3] > 0.5
    px, step = _pixels(img)
    mask = subject_mask(px)
    ph, pw = mask.shape
    ys = np.clip(((np.arange(rh) + 0.5) / rh * ph).astype(int), 0, ph - 1)
    xs = np.clip(((np.arange(rw) + 0.5) / rw * pw).astype(int), 0, pw - 1)
    refm = mask[ys][:, xs]
    inter = int((model & refm).sum())
    union = int((model | refm).sum())
    out = {"view": view_name, "reference": ref.name, "iou": round(inter / union, 3) if union else 0.0,
           "model_outside_reference": round(int((model & ~refm).sum()) / max(1, int(refm.sum())), 3),
           "reference_not_covered": round(int((refm & ~model).sum()) / max(1, int(refm.sum())), 3)}
    m_px = scale / max(rw, rh)
    for label, msk in (("model", model), ("reference", refm)):
        bb = _bbox(msk)
        if bb:
            out[label + "_size_m"] = [round((bb[2] - bb[0] + 1) * m_px, 4), round((bb[3] - bb[1] + 1) * m_px, 4)]
    if "model_size_m" in out and "reference_size_m" in out:
        ratio = [round(a / b, 3) if b else None for a, b in zip(out["model_size_m"], out["reference_size_m"])]
        out["size_ratio_wh"] = ratio
    diff = np.zeros((rh, rw, 3))
    diff[...] = (0.16, 0.17, 0.19)
    diff[model & refm] = (0.78, 0.78, 0.78)
    diff[model & ~refm] = (0.90, 0.25, 0.20)
    diff[refm & ~model] = (0.25, 0.45, 0.95)
    return out, view.png_bytes(diff)


@action("reference_sheet",
      "Reference pictures for modeling: load puts pictures as scaled image planes aligned to a view (shown in ortho "
      "views, never rendered; the subject's size in meters from width or height); score renders the model's "
      "silhouette in that view and compares (overlap IoU, sizes, a picture: red = model only, blue = reference "
      "only); list; clear.",
      {"type": "object", "properties": {
          "action": {"type": "string", "enum": ["load", "score", "list", "clear"]},
          "images": {"type": "array", "description": "For load.", "items": {"type": "object", "properties": {
              "path": {"type": "string", "description": "A picture file on this computer (PNG / JPG)."},
              "view": {"type": "string", "enum": ["front", "back", "left", "right", "top", "bottom"],
                       "description": "The view it shows (front looks from -Y: a gun along X shows its side)."},
              "width": {"type": "number", "description": "The subject's width in meters."},
              "height": {"type": "number", "description": "The subject's height in meters."},
              "center": {"type": "array", "items": {"type": "number"},
                         "description": "Subject center on the view plane (u, v) in meters."},
              "opacity": {"type": "number", "description": "0-1 (default 0.5)."}},
              "required": ["path"]}},
          "view": {"type": "string", "enum": ["front", "back", "left", "right", "top", "bottom"],
                   "description": "For score."},
          "names": NAMES}, "required": ["action"]},
      changes=True)
def reference_sheet(ctx, args):
    action = args.get("action")
    if action == "list":
        return {"references": [{"name": o.name, "view": o.get("nighty_view"),
                                "picture": os.path.basename(o.get("nighty_path", "")),
                                "subject_box_uv": list(o.get("nighty_subject", []))} for o in reference_objects()]}
    if action == "clear":
        refs = reference_objects()
        imgs = {o.data for o in refs if o.data is not None}
        for o in refs:
            bpy.data.objects.remove(o, do_unlink=True)
        for i in imgs:
            if i.users == 0:
                bpy.data.images.remove(i)
        coll = bpy.data.collections.get(COLLECTION)
        if coll is not None and not coll.all_objects:
            bpy.data.collections.remove(coll)
        return {"cleared": len(refs)}
    if action == "load":
        specs = args.get("images") or []
        if not specs:
            raise ToolError("images: give at least one {path, view, width or height}.")
        try:
            models = targets({"names": args.get("names")}) if args.get("names") else core.objects()
        except ToolError:
            models = []
        placed = [_load(s, models) for s in specs[:6]]
        return {"loaded": placed, "next": "build against them; look { references: true } and reference_sheet "
                                          "{ action: score, view } to compare"}
    if action == "score":
        v = args.get("view") or "front"
        models = targets(args)
        out, png = _score(v, models)
        return [text(out), image(png)]
    raise ToolError("action must be load, score, list or clear.")
