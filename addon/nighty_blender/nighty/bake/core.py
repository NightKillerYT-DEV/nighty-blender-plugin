# SPDX-License-Identifier: GPL-3.0-or-later
"""The bake itself. Runs in a Blender that holds the asset: normally the `blender -b` worker (so the person's Blender
never freezes), or a test. It works on throw-away copies of the materials.

What it does, in order:
1. UVs: parts whose layouts overlap (each part in its own 0..1) are packed into ONE shared atlas ("NB_Atlas"), with
   even texel density; the packed UVs go back to the person's file.
2. Every map is baked per object at full size with no margin (so coverage is exact), using Cycles:
   base color / roughness / metallic / emission / opacity through the emission-rewire trick, the tangent-space
   normal (selected-to-active from a high poly when there is one), ambient occlusion.
3. The objects are combined into one texture set; metallic is snapped to exactly 0 / 1; AO sampling noise is
   smoothed inside the islands; a margin is grown and the rest filled smoothly (no seams in mipmaps).
4. Maps are written as PNG (8-bit; data maps as true grayscale, base color / emission in sRGB) with a manifest.
"""

import json
import math
import os
import time
import zlib

import bpy
import numpy as np

from ..materials import compat
from ..materials.build import TEXEL_NODE
from . import channels, maps, png, uvraster

ATLAS = "NB_Atlas"
TRANSFER = ("base_color", "roughness", "metallic", "emission", "opacity")   # channels "transfer" takes from the high


def log(*a):
    print("[nighty bake]", *a, flush=True)


# ----------------------------------------------------------------------------------------------- scene setup

def setup_cycles(scene, device="CPU", threads=0, size=1024):
    """Cycles for baking. device: CPU | GPU | auto. Returns the device used. 'auto' takes the GPU only for 4K maps:
    each bake call costs the GPU ~15 s of setup, so up to 2K the CPU finishes first (checked on an RTX 3060)."""
    try:
        scene.render.engine = "CYCLES"
    except TypeError:
        pass
    used = "CPU"
    if device == "GPU" or (device == "auto" and size >= 4096):
        try:
            prefs = bpy.context.preferences.addons["cycles"].preferences
            for kind in ("CUDA", "OPTIX", "HIP", "ONEAPI", "METAL"):
                try:
                    prefs.compute_device_type = kind
                except TypeError:
                    continue
                prefs.get_devices()
                devs = [d for d in prefs.devices if d.type == kind]
                if devs:
                    for d in prefs.devices:
                        d.use = d.type == kind
                    used = "GPU"
                    break
        except Exception as e:  # no cycles prefs in this build: CPU it is
            log("GPU check failed:", e)
    scene.cycles.device = used
    if threads:
        scene.render.threads_mode = "FIXED"
        scene.render.threads = threads
    try:
        scene.cycles.use_denoising = False
    except AttributeError:
        pass
    return used


def _select_only(objs, active=None):
    vl = bpy.context.view_layer
    for o in vl.objects:
        if o is not None:
            o.select_set(False)
    for o in objs:
        o.select_set(True)
    vl.objects.active = active or (objs[0] if objs else None)


def _edit_mode(objs, fn):
    _select_only(objs)
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        bpy.ops.mesh.select_all(action="SELECT")
        try:
            bpy.ops.uv.select_all(action="SELECT")
        except RuntimeError:
            pass
        fn()
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")


# ----------------------------------------------------------------------------------------------- UVs

def ensure_uvs(objs):
    """Objects without UVs get a Smart UV Project (the topology helper makes better ones; this is a fallback)."""
    bare = [o for o in objs if not o.data.uv_layers]
    if bare:
        _edit_mode(bare, lambda: bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.01))
    return [o.name for o in bare]


def needs_atlas(objs):
    rep = uvraster.layout_report(objs, n=256)
    return (rep["overlap"] > 0.002 or rep["outside"] > 0), rep


def make_atlas(objs, size, margin_px):
    """Copies each object's active UVs into NB_Atlas and packs all islands of all objects together."""
    for o in objs:
        me = o.data
        src = me.uv_layers.active
        lay = me.uv_layers.get(ATLAS)
        if lay is None:
            lay = me.uv_layers.new(name=ATLAS)
        if src is not None and src != lay:
            buf = np.empty(len(me.loops) * 2, np.float32)
            src.data.foreach_get("uv", buf)
            lay.data.foreach_set("uv", buf)
        me.uv_layers.active = lay

    def pack():
        bpy.ops.uv.average_islands_scale()
        kw = dict(rotate=True, margin=float(margin_px) / size)   # the gap between islands, in pixels
        props = bpy.ops.uv.pack_islands.get_rna_type().properties.keys()
        if "margin_method" in props:
            kw["margin_method"] = "FRACTION"
        if "shape_method" in props:
            kw["shape_method"] = "AABB"    # the exact shapes take 20-40 s for the same result on hard-surface
        bpy.ops.uv.pack_islands(**kw)

    _edit_mode(objs, pack)
    return ATLAS


def uv_layer_name(obj):
    lay = obj.data.uv_layers.get(ATLAS) or obj.data.uv_layers.active
    return lay.name if lay else None


def texel_size(objs, layer_of, size):
    """Meters per texel over the whole atlas (surface area against UV area)."""
    area3, areauv = 0.0, 0.0
    for o in objs:
        me = o.data
        arr = uvraster.mesh_arrays(me, layer_of(o))
        if arr is None:
            continue
        uv, tl, _, _ = arr
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        lv = np.empty(len(me.loops), np.int64)
        me.loops.foreach_get("vertex_index", lv)
        mw = np.array(o.matrix_world, np.float64)
        p = co[lv[tl]] @ mw[:3, :3].T
        area3 += 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1).sum()
        t = uv[tl]
        areauv += 0.5 * np.abs((t[:, 1, 0] - t[:, 0, 0]) * (t[:, 2, 1] - t[:, 0, 1]) -
                               (t[:, 1, 1] - t[:, 0, 1]) * (t[:, 2, 0] - t[:, 0, 0])).sum()
    if areauv <= 0:
        return 0.001
    return math.sqrt(area3 / areauv) / size


# ----------------------------------------------------------------------------------------------- images

def _new_image(name, size):
    img = bpy.data.images.new(name, size, size, alpha=True, float_buffer=True)
    img.generated_color = (0.0, 0.0, 0.0, 0.0)
    try:
        img.colorspace_settings.name = "Non-Color"
    except TypeError:
        pass
    return img


def _pixels(img):
    w, h = img.size
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(h, w, 4)[::-1]   # row 0 = top


def _clear(img):
    w, h = img.size
    img.pixels.foreach_set(np.zeros(w * h * 4, np.float32))


def _attach(mat, img):
    """An unconnected, active image node: where Cycles writes the bake for this material."""
    tree = mat.node_tree
    n = tree.nodes.new("ShaderNodeTexImage")
    n.name = "NB Bake Target"
    n.image = img
    for other in tree.nodes:
        other.select = False
    n.select = True
    tree.nodes.active = n
    return n


def _default_material():
    m = bpy.data.materials.get("NB Default Gray") or compat.new_material("NB Default Gray")
    p = compat.principled_of(m)
    if p is not None:
        compat.socket(p.inputs, "Base Color").default_value = (0.5, 0.5, 0.5, 1.0)
        compat.socket(p.inputs, "Roughness").default_value = 0.6
    return m


# ----------------------------------------------------------------------------------------------- the bake

class Baker:
    def __init__(self, spec, progress=None):
        self.spec = spec
        self.size = maps.size_of(spec.get("size", 1024))
        self.progress = progress or (lambda p, m: None)
        self.scene = bpy.context.scene
        self.objs = [bpy.data.objects[n] for n in spec["objects"]]
        self.high = {k: bpy.data.objects[v] for k, v in (spec.get("high") or {}).items()
                     if v in bpy.data.objects and k in spec["objects"]}
        self.warnings = []

    def run(self):
        t0 = time.time()
        spec, size = self.spec, self.size
        out_dir = spec["out_dir"]
        os.makedirs(out_dir, exist_ok=True)
        name = spec.get("name") or "Asset"
        sc = self.scene
        if sc.world is None:
            sc.world = bpy.data.worlds.new("NB Bake World")
        used = setup_cycles(sc, spec.get("device", "CPU"), spec.get("threads", 0), size)
        log("device", used, "size", size)

        # sources: the procedural materials (a baked material in the slots is swapped back first)
        for o in self.objs:
            srcs = (spec.get("sources") or {}).get(o.name)
            if srcs:
                for i, mname in enumerate(srcs):
                    m = bpy.data.materials.get(mname)
                    if m is not None and i < len(o.material_slots):
                        o.material_slots[i].material = m
            if not o.material_slots:
                o.data.materials.append(_default_material())
            for slot in o.material_slots:
                if slot.material is None:
                    slot.material = _default_material()

        # 1. UVs
        self.progress(0.03, "UVs")
        made = ensure_uvs(self.objs)
        if made:
            self.warnings.append(f"no UVs on {', '.join(made)}: made quick ones (unwrap first for better maps)")
        margin_px = int(spec.get("margin") or max(4, size // 128))
        atlas, rep = needs_atlas(self.objs)
        if spec.get("uv") == "keep":
            atlas = False
        if atlas:
            make_atlas(self.objs, size, margin_px)
            rep2 = uvraster.layout_report(self.objs, n=256, layer_of=lambda o: ATLAS)
            if rep2["overlap"] > 0.002:
                self.warnings.append("some UV islands still overlap after packing (mirrored or stacked faces)")
        layer_of = (lambda o: ATLAS) if atlas else (lambda o: o.data.uv_layers.active.name)
        texel = texel_size(self.objs, layer_of, size)

        # triangulate the same way the export does, so normal maps match the game mesh exactly
        added = []
        if spec.get("triangulate", True):
            for o in self.objs:
                if add_triangulate(o):
                    added.append(o)

        # single-user material copies per object (each object writes into its own images)
        originals = {o: [slot.material for slot in o.material_slots] for o in self.objs}
        pristine = {}
        try:
            return self._bake_all(t0, spec, size, out_dir, name, used, rep, atlas, layer_of, texel, margin_px,
                                  pristine)
        finally:
            for o, mats in originals.items():
                for slot, m in zip(o.material_slots, mats):
                    slot.material = m
            for ms in pristine.values():
                for m in ms:
                    if m.users == 0:
                        bpy.data.materials.remove(m)
            for o in added:
                mod = o.modifiers.get("NB Triangulate")
                if mod is not None:
                    o.modifiers.remove(mod)

    def _bake_all(self, t0, spec, size, out_dir, name, used, rep, atlas, layer_of, texel, margin_px, pristine):
        for o in self.objs:
            pristine[o] = []
            for slot in o.material_slots:
                m = slot.material.copy()
                m.name = f"NBB {o.name} {slot.material.name}"[:60]
                for n in m.node_tree.nodes:
                    if n.name == TEXEL_NODE:
                        n.outputs[0].default_value = texel
                slot.material = m
                pristine[o].append(m)
        all_src = [m for ms in pristine.values() for m in ms]
        strength = channels.emission_strength(all_src)
        alpha = channels.has_alpha(all_src)

        wanted = [k for k in maps.ORDER if k in spec.get("maps", maps.ORDER)]
        if "emission" in wanted and strength <= 0:
            wanted.remove("emission")
        if "opacity" in wanted and not alpha:
            wanted.remove("opacity")
        samples = spec.get("samples") or {}
        self.progress(0.06, "Baking wear and dirt masks")
        t = time.time()
        if self._bake_masks(pristine, layer_of, samples, margin_px):
            log("masks", f"{time.time() - t:.1f}s")
        steps = ["coverage"] + wanted
        results = {}
        cover = None
        for i, key in enumerate(steps):
            self.progress(0.08 + 0.8 * i / len(steps), f"Baking {key.replace('_', ' ')}")
            t = time.time()
            arr, written = self._bake_map(key, pristine, layer_of, samples)
            log(key, f"{time.time() - t:.1f}s")
            if key == "coverage":
                cover = written
            else:
                results[key] = (arr, written)
        # 3. combine, clean, margin
        self.progress(0.9, "Margins")
        manifest_maps, unbaked = {}, {}
        os.makedirs(out_dir, exist_ok=True)
        for key, (arr, written) in results.items():
            miss = cover & ~written
            unbaked[key] = int(miss.sum())
            arr = self._finish(key, arr, written & cover, cover, margin_px)
            fname = f"{name}_{maps.MAPS[key][0]}.png"
            png.write(os.path.join(out_dir, fname), self._encode(key, arr))
            manifest_maps[key] = fname
        # UVs for the person's file
        uv_files = {}
        if atlas:
            for o in self.objs:
                buf = np.empty(len(o.data.loops) * 2, np.float32)
                o.data.uv_layers[ATLAS].data.foreach_get("uv", buf)
                f = os.path.join(out_dir, f".uv_{zlib.crc32(o.name.encode('utf-8')):08x}.npy")
                np.save(f, buf)
                uv_files[o.name] = {"file": os.path.basename(f), "loops": len(o.data.loops)}
        manifest = {
            "name": name, "size": size, "maps": manifest_maps, "normal_format": "opengl",
            "uv_layer": ATLAS if atlas else None, "atlas": atlas, "uv_files": uv_files,
            "objects": [o.name for o in self.objs], "high": {k: v.name for k, v in self.high.items()},
            "unbaked_pixels": unbaked, "coverage": float(cover.mean()), "texel_m": texel,
            "emission_strength": strength, "has_alpha": alpha, "margin_px": margin_px,
            "metallic_binary": True, "device": used, "seconds": round(time.time() - t0, 1),
            "blender": bpy.app.version_string, "uv_layout": rep, "warnings": self.warnings,
            "style": spec.get("style", "pbr"),
        }
        with open(os.path.join(out_dir, "bake.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=1)
        self.progress(1.0, "Done")
        return manifest

    # -- one map
    def _bake_map(self, key, pristine, layer_of, samples):
        size = self.size
        sc = self.scene
        imgs, temp_mats = {}, []
        for o in self.objs:
            img = _new_image(f"NBB {key} {o.name}", size)
            _clear(img)
            imgs[o] = img
            for slot, base in zip(o.material_slots, pristine[o]):
                m = base.copy()
                channels.rewire(m.node_tree, {"coverage": "white", "ao": "plain"}.get(key, key))
                temp_mats.append(m)
                slot.material = m
                _attach(m, img)
        n_default = {"coverage": 1, "normal": 4, "ao": 64 if size <= 1024 else (48 if size <= 2048 else 32)}
        if self.spec.get("style") == "stylized":
            n_default["base_color"] = 16 if size <= 2048 else 8   # AO and light live in the albedo
        sc.cycles.samples = int(samples.get(key, n_default.get(key, 4 if size <= 2048 else 2)))
        btype = {"normal": "NORMAL", "ao": "AO"}.get(key, "EMIT")
        if key == "ao":
            sc.world.light_settings.distance = float(self.spec.get("ao_distance") or self._ao_distance())
        kw = dict(type=btype, margin=0, use_clear=False, target="IMAGE_TEXTURES")
        if btype == "NORMAL":
            kw.update(normal_space="TANGENT", normal_r="POS_X", normal_g="POS_Y", normal_b="POS_Z")
        # objects with a high poly: normal + AO from it (selected to active), one at a time; with "transfer" also
        # the colors, roughness and metallic from the high poly's own material (e.g. an AI model's textures)
        transfer = bool(self.spec.get("transfer")) and key in TRANSFER
        from_high = key in ("normal", "ao") or transfer
        plain = [o for o in self.objs if not (o.name in self.high and from_high)]
        highs = list({h.name: h for h in self.high.values()}.values())
        hi_saved = {}
        try:
            for h in highs:   # high polys never shade or occlude the plain bake
                h.hide_render = True
            if plain:
                # one call for all: each object writes its own image
                self._bake_many(plain, layer_of, kw)
            if from_high and self.high:
                if transfer:      # the high's materials emit this channel (throw-away copies)
                    for h in highs:
                        hi_saved[h] = [slot.material for slot in h.material_slots]
                        for slot in h.material_slots:
                            if slot.material is not None and slot.material.node_tree is not None:
                                m = slot.material.copy()
                                channels.rewire(m.node_tree, key)
                                temp_mats.append(m)
                                slot.material = m
                # parts that share one high poly (split from one model, one shared atlas) bake in ONE call onto a
                # joined copy: Cycles loads the dense high poly once instead of once per part
                groups = {}
                for low_name, hi in self.high.items():
                    groups.setdefault(hi.name, (hi, []))[1].append(bpy.data.objects[low_name])
                for hi, lows in groups.values():
                    hi.hide_render = False
                    joined = self._joined(lows, layer_of, imgs[lows[0]]) if len(lows) > 1 else None
                    try:
                        targets = [(joined, layer_of(lows[0]))] if joined is not None else                             [(lo, layer_of(lo)) for lo in lows]
                        for target, layer in targets:
                            _select_only([hi, target], target)
                            ext, ray = cage_distances(target, hi)
                            bpy.ops.object.bake(use_selected_to_active=True, cage_extrusion=ext,
                                                max_ray_distance=ray, uv_layer=layer, **kw)
                    finally:
                        if joined is not None:
                            me, mats = joined.data, list(joined.data.materials)
                            bpy.data.objects.remove(joined)
                            bpy.data.meshes.remove(me)
                            for m in mats:
                                if m is not None and m.users == 0:
                                    bpy.data.materials.remove(m)
                    hi.hide_render = True
            # combine
            arr = np.zeros((size, size, 4), np.float32)
            written = np.zeros((size, size), bool)
            for o in self.objs:
                px = _pixels(imgs[o])
                w = (px[..., 3] > 0.5) & ~written
                arr[w] = px[w]
                written |= w
            return arr, written
        finally:
            for h, mats in hi_saved.items():
                for slot, m in zip(h.material_slots, mats):
                    slot.material = m
            for o in self.objs:
                for slot, base in zip(o.material_slots, pristine[o]):
                    slot.material = base
                    for n in [n for n in base.node_tree.nodes if n.name.startswith("NB Bake Target")]:
                        base.node_tree.nodes.remove(n)
            for m in temp_mats:
                bpy.data.materials.remove(m)
            for img in imgs.values():
                bpy.data.images.remove(img)

    def _bake_masks(self, pristine, layer_of, samples, margin_px):
        """Bakes the geometry masks (edge wear 'Mask', cavity 'Dirt') once, with many samples, smooths their sampling
        noise, and swaps the live mask groups for the baked copy: every map then uses exactly the same wear and
        dirt (no speckle that differs between color and metallic), and the channel bakes get much faster."""
        found = {}
        for o, mats in pristine.items():
            for m in mats:
                nodes = [n for n in m.node_tree.nodes if n.type == "GROUP" and n.node_tree is not None and
                         n.node_tree.name.startswith(("NB Edge Wear", "NB Cavity Dirt"))]
                if nodes:
                    found[m] = nodes
        if not found:
            return False
        size = self.size
        imgs, temp = {}, []
        sc = self.scene
        try:
            for o in self.objs:
                img = _new_image(f"NBB masks {o.name}", size)
                _clear(img)
                imgs[o] = img
                for slot, base in zip(o.material_slots, pristine[o]):
                    m = base.copy()
                    temp.append(m)
                    tree = m.node_tree
                    out = compat.output_node(tree)
                    em = tree.nodes.new("ShaderNodeEmission")
                    comb = tree.nodes.new("ShaderNodeCombineColor")
                    for n in tree.nodes:
                        if n.type == "GROUP" and n.node_tree is not None:
                            if n.node_tree.name.startswith("NB Edge Wear"):
                                tree.links.new(compat.socket(n.outputs, "Mask"), comb.inputs[0])
                            elif n.node_tree.name.startswith("NB Cavity Dirt"):
                                tree.links.new(compat.socket(n.outputs, "Dirt"), comb.inputs[1])
                    tree.links.new(comb.outputs[0], compat.socket(em.inputs, "Color"))
                    for link in list(compat.socket(out.inputs, "Surface").links):
                        tree.links.remove(link)
                    tree.links.new(em.outputs[0], compat.socket(out.inputs, "Surface"))
                    slot.material = m
                    _attach(m, img)
            sc.cycles.samples = int(samples.get("masks", 16))
            self._bake_many(self.objs, layer_of, dict(type="EMIT", margin=0, use_clear=False,
                                                      target="IMAGE_TEXTURES"))
            arr = np.zeros((size, size, 4), np.float32)
            written = np.zeros((size, size), bool)
            for o in self.objs:
                px = _pixels(imgs[o])
                w = (px[..., 3] > 0.5) & ~written
                arr[w] = px[w]
                written |= w
        finally:
            for o in self.objs:
                for slot, base in zip(o.material_slots, pristine[o]):
                    slot.material = base
            for m in temp:
                bpy.data.materials.remove(m)
            for img in imgs.values():
                bpy.data.images.remove(img)
        rgb = maps.blur_masked(arr[..., :3], written, passes=1)
        rgb, filled = maps.dilate(rgb, written, margin_px + 2)
        rgb = maps.fill_rest(rgb, filled)
        mask_img = bpy.data.images.new("NBB Masks", size, size, alpha=True, float_buffer=True)
        try:
            mask_img.colorspace_settings.name = "Non-Color"
        except TypeError:
            pass
        flat = np.dstack([rgb, np.ones((size, size), np.float32)])[::-1].reshape(-1)
        mask_img.pixels.foreach_set(flat.astype(np.float32))
        # swap the live groups for the baked masks
        for o in self.objs:
            for base in pristine[o]:
                nodes = found.get(base)
                if not nodes:
                    continue
                tree = base.node_tree
                uvn = tree.nodes.new("ShaderNodeUVMap")
                uvn.uv_map = layer_of(o)
                tex = tree.nodes.new("ShaderNodeTexImage")
                tex.image = mask_img
                tex.interpolation = "Linear"
                tex.extension = "EXTEND"
                tree.links.new(uvn.outputs[0], compat.socket(tex.inputs, "Vector"))
                sep = tree.nodes.new("ShaderNodeSeparateColor")
                tree.links.new(tex.outputs[0], sep.inputs[0])
                for n in nodes:
                    name = "Mask" if n.node_tree.name.startswith("NB Edge Wear") else "Dirt"
                    src = sep.outputs[0] if name == "Mask" else sep.outputs[1]
                    for link in list(compat.socket(n.outputs, name).links):
                        tree.links.new(src, link.to_socket)
        return True

    def _joined(self, lows, layer_of, img):
        """One throw-away object made of all `lows` (world space, as triangulated for the bake) that writes into
        `img`; None when their bake UV layers differ (then each part bakes on its own)."""
        import bmesh
        layers = {layer_of(o) for o in lows}
        if len(layers) != 1:
            return None
        layer = layers.pop()
        dg = bpy.context.evaluated_depsgraph_get()
        bm = bmesh.new()
        try:
            for o in lows:
                me = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
                try:
                    if me.uv_layers.get(layer) is None:
                        return None
                    for lay in [lay for lay in me.uv_layers if lay.name != layer]:
                        me.uv_layers.remove(lay)
                    me.transform(o.matrix_world)
                    bm.from_mesh(me)
                finally:
                    bpy.data.meshes.remove(me)
            me = bpy.data.meshes.new("NBB joined")
            bm.to_mesh(me)
        finally:
            bm.free()
        if me.uv_layers.get(layer) is not None:
            me.uv_layers.active = me.uv_layers[layer]
        mat = compat.new_material("NBB joined target")
        _attach(mat, img)
        me.materials.append(mat)
        ob = bpy.data.objects.new("NBB joined", me)
        self.scene.collection.objects.link(ob)
        bpy.context.view_layer.update()
        return ob

    def _bake_many(self, objs, layer_of, kw):
        layers = {layer_of(o) for o in objs}
        if len(layers) == 1:
            _select_only(objs)
            bpy.ops.object.bake(uv_layer=layers.pop(), **kw)
        else:  # different active layers: one call per object (all write their own images)
            for o in objs:
                _select_only([o])
                bpy.ops.object.bake(uv_layer=layer_of(o), **kw)

    def _ao_distance(self):
        from mathutils import Vector
        pts = [o.matrix_world @ Vector(c) for o in self.objs for c in o.bound_box]
        lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
        hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
        return max(0.01, min(2.0, (hi - lo).length * 0.08))

    # -- after the bake
    def _finish(self, key, arr, good, cover, margin_px):
        if key == "metallic":
            arr[..., :3] = maps.snap_binary(arr[..., :1])
        elif key in ("roughness", "opacity", "ao"):
            arr[..., :3] = np.clip(arr[..., :1], 0.0, 1.0)
        if key == "ao":
            arr[..., :3] = maps.blur_masked(arr[..., :3], good, passes=1)
        rgb = arr[..., :3]
        rgb, filled = maps.dilate(rgb, good, margin_px)
        rgb = maps.fill_rest(rgb, filled)
        if key == "metallic":
            rgb = maps.snap_binary(rgb)
        if key == "normal":
            # re-normalize (filtering and dilation shorten the vectors); vectors that point into the surface (a ray
            # from a decimated low poly that hit a groove's far wall) are folded back into the outer half
            v = rgb * 2.0 - 1.0
            v[..., 2] = np.maximum(v[..., 2], 0.08)
            ln = np.linalg.norm(v, axis=-1, keepdims=True)
            v = np.where(ln > 1e-6, v / np.maximum(ln, 1e-6), np.array([0, 0, 1], np.float32))
            rgb = (v * 0.5 + 0.5).astype(np.float32)
        return rgb

    def _encode(self, key, rgb):
        bits = 16 if (key == "normal" and self.spec.get("normal_16bit")) else 8
        if key in ("base_color", "emission"):
            return png.to_uint(maps.linear_to_srgb(rgb), bits)
        if maps.MAPS[key][1] == 1:
            return png.to_uint(rgb[..., 0], bits)
        return png.to_uint(rgb, bits)


def cage_distances(low, high):
    """How far rays start outside the low poly and how far they may go, so they reach the high poly everywhere.
    Measured both ways: how far the high poly's surface lies outside the low (a decimated low poly cuts inside the
    high poly most where its triangles are biggest: the boxes don't show that) and how far the low lies outside the
    high (the collapse moves vertices out). When one dense original is shared by several split parts (its box much
    bigger than this part's), only the surface near this part counts and the cage stays short, so rays never start
    inside a neighbouring part."""
    from mathutils import Vector

    def box(o):
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
        return (Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))),
                Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))))

    (l0, l1), (h0, h1) = box(low), box(high)
    d = max((l1 - l0).length, 1e-4)
    out = max(0.0, max(l0[i] - h0[i] for i in range(3)), max(h1[i] - l1[i] for i in range(3)))
    shared = out > 0.1 * d
    gap_out, gap_in = _gaps(low, high, 0.08 * d if shared else max(0.08 * d, out * 1.2))
    if shared:
        ext = min(max(gap_out * 1.3, 0.002 * d), 0.06 * d)
        return ext, ext + min(gap_in * 1.3, 0.06 * d) + 0.01 * d
    ext = max(out * 1.15, gap_out * 1.3) + 0.005 * d
    return ext, ext + max(gap_in * 1.3, ext) + 0.02 * d


def _gaps(low, high, pad):
    """(how far the high poly's surface lies outside the low poly, how far the low lies outside the high), in
    meters, near the low (within its box + pad): the largest distances of each one's vertices to the other's
    surface, signed by the low / high surface normals."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get()
    corners = np.array([tuple(c) for c in low.bound_box])
    lb0, lb1 = corners.min(axis=0), corners.max(axis=0)

    def verts(o, to_low):
        n = len(o.data.vertices)
        if n == 0:
            return np.zeros((0, 3))
        co = np.empty(n * 3, np.float32)
        o.data.vertices.foreach_get("co", co)
        m = np.array(low.matrix_world.inverted() @ o.matrix_world, np.float64) if to_low else np.eye(4)
        return co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]

    def gap(pts, tree, flip):
        pts = pts[np.all((pts >= lb0 - pad) & (pts <= lb1 + pad), axis=1)]
        if len(pts) > 20000:
            pts = pts[np.random.default_rng(0).choice(len(pts), 20000, replace=False)]
        best = 0.0
        for p in pts:
            loc, nrm, _i, dist = tree.find_nearest(Vector(p), pad)
            if loc is not None and (Vector(p) - loc).dot(nrm) * flip > 0:
                best = max(best, dist)
        return best

    if len(low.data.polygons) == 0 or len(high.data.polygons) == 0:
        return 0.0, 0.0
    low_tree = BVHTree.FromObject(low, dg)
    gap_out = gap(verts(high, True), low_tree, 1.0)          # high outside the low
    # the low's vertices against the high (both in the low's object space)
    hco = verts(high, True)
    hi_tree = BVHTree.FromPolygons(hco.tolist(), [tuple(p.vertices) for p in high.data.polygons])
    gap_in = gap(verts(low, False), hi_tree, 1.0)            # low outside the high
    return gap_out, gap_in


def add_triangulate(obj):
    """The NB Triangulate modifier (last in the stack), the same for bakes and exports. False if it was there."""
    if obj.modifiers.get("NB Triangulate") is not None:
        return False
    mod = obj.modifiers.new("NB Triangulate", "TRIANGULATE")
    mod.quad_method = "SHORTEST_DIAGONAL"
    mod.ngon_method = "BEAUTY"
    try:
        mod.keep_custom_normals = True
    except AttributeError:
        pass
    return True


def bake_asset(spec, progress=None):
    return Baker(spec, progress).run()
