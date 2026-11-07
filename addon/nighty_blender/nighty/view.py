# SPDX-License-Identifier: GPL-3.0-or-later
"""Off-screen pictures of the model (behind the look tool): fixed views, solid / matcap / material / silhouette,
wireframe on top. A temporary camera renders into its own Render Result slot; every scene setting it touches is
put back, so the person's viewport, camera, renders and settings stay as they were."""

import math

import bpy
from mathutils import Euler, Vector

from . import compat, core

__all__ = []

# Ortho views look along a world axis; the 3/4 views are perspective (azimuth from the front, elevation).
VIEWS = {
    "front": {"rot": (90, 0, 0)}, "back": {"rot": (90, 0, 180)}, "right": {"rot": (90, 0, 90)},
    "left": {"rot": (90, 0, -90)}, "top": {"rot": (0, 0, 0)}, "bottom": {"rot": (180, 0, 0)},
    "three_quarter": {"az": 35, "el": 22}, "three_quarter_left": {"az": -35, "el": 22},
    "three_quarter_back": {"az": 215, "el": 22}, "three_quarter_low": {"az": 35, "el": -12},
    "hero": {"auto": True},  # a 3/4 view picked from the shape: long things are seen more from the side
}
MODES = ("solid", "matcap", "material", "silhouette")
LABELS = {"hero": "HERO", "front": "FRONT", "back": "BACK", "right": "RIGHT", "left": "LEFT", "top": "TOP", "bottom": "BOTTOM",
          "three_quarter": "3/4", "three_quarter_left": "3/4 L", "three_quarter_back": "3/4 BACK",
          "three_quarter_low": "3/4 LOW"}
BACKGROUND = ((0.44, 0.46, 0.50), (0.25, 0.26, 0.29))  # top, bottom (display colors)
STUDIO_BACKGROUND = ((0.70, 0.71, 0.73), (0.47, 0.48, 0.50))  # the material / studio backdrop
WIRE_COLOR = (0.06, 0.07, 0.09)


def _np():
    import numpy as np
    return np


class _Restore:
    """Remembers attributes and puts them back (newest first)."""

    def __init__(self):
        self.items = []

    def set(self, owner, attr, value):
        try:
            old = getattr(owner, attr)
            if hasattr(old, "copy") and not isinstance(old, (bpy.types.ID, str)):
                old = old.copy()
            elif hasattr(old, "__len__") and not isinstance(old, (str, bpy.types.ID)):
                old = tuple(old)
        except AttributeError:
            return False
        try:
            setattr(owner, attr, value)
        except (TypeError, AttributeError, ValueError):
            return False
        self.items.append((owner, attr, old))
        return True

    def restore(self):
        for owner, attr, old in reversed(self.items):
            try:
                setattr(owner, attr, old)
            except (TypeError, AttributeError, ValueError, ReferenceError):
                pass
        self.items.clear()


def hero_angles(size):
    """Azimuth / elevation (degrees) that show an object's shape best: side-on for long things, 3/4 otherwise."""
    sx, sy, sz = (max(float(c), 1e-6) for c in size)
    if sx >= 2.2 * max(sy, sz * 0.7):
        return 27.0, 10.0
    if sy >= 2.2 * max(sx, sz * 0.7):
        return 63.0, 10.0
    if sz < 0.35 * max(sx, sy):
        return 32.0, 34.0
    return 34.0, 18.0


def _view_rotation(view, center, radius, size=None):
    spec = VIEWS[view]
    if spec.get("auto"):
        az, el = hero_angles(size or (1, 1, 1))
        spec = {"az": az, "el": el}
    if "rot" in spec:
        return Euler([math.radians(a) for a in spec["rot"]], "XYZ"), True
    az, el = math.radians(spec["az"]), math.radians(spec["el"])
    d = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
    return (-d).to_track_quat("-Z", "Y").to_euler(), False


def _fit(x, y, z, tan_half, aspect, diag):
    """Camera distance so every point is inside a view whose longer side spans the lens' 36 mm."""
    np = _np()
    if aspect >= 1.0:
        half_x, half_y = tan_half, tan_half / aspect
    else:
        half_x, half_y = tan_half * aspect, tan_half
    need = np.maximum(np.abs(x) / half_x, np.abs(y) / half_y) - z
    return max(float(np.max(need)), diag * 0.3)


def _frame(cam, view, corners, center, diag, persp_override=None, points=None, lens=50.0, size=None):
    """Points the camera at the model (its points when given, else the box corners): returns a pose dict."""
    rot, ortho = _view_rotation(view, center, diag / 2.0, size)
    if persp_override is not None:
        ortho = not persp_override
    cam.rotation_euler = rot
    cam.data.type = "ORTHO" if ortho else "PERSP"
    cam.data.lens = float(lens)
    cam.data.sensor_fit = "AUTO"
    mat = rot.to_matrix()
    right, up, fwd = mat.col[0], mat.col[1], -mat.col[2]
    pts = points if points is not None and len(points) else [tuple(c) for c in corners]
    if ortho:
        us = [c.dot(right) for c in corners]
        vs = [c.dot(up) for c in corners]
        w, h = max(us) - min(us), max(vs) - min(vs)
        mid = right * ((max(us) + min(us)) / 2) + up * ((max(vs) + min(vs)) / 2)
        depth = sum((c.dot(fwd) for c in corners)) / len(corners)
        aspect = cam.get("nighty_aspect", 1.0)
        scale = max(w, h * aspect, diag * 0.02) * 1.08 if aspect >= 1 else max(w / aspect, h, diag * 0.02) * 1.08
        cam.data.ortho_scale = scale
        loc = mid + fwd * depth - fwd * (diag * 2.0 + 1.0)
    else:
        np = _np()
        P = np.asarray(pts, dtype=np.float64)
        tan_half = 18.0 / float(lens)
        aspect = cam.get("nighty_aspect", 1.0)  # wider than tall: the long side gets the 36 mm
        R, U, F = np.array(right), np.array(up), np.array(fwd)
        aim = np.array(center)
        for _ in range(3):  # fit, then slide the aim to the middle of what the camera sees, fit again
            off = P - aim
            x, y, z = off @ R, off @ U, off @ F
            dist = _fit(x, y, z, tan_half, aspect, diag)
            depth = dist + z
            px, py = x / depth, y / depth
            shift_x = (px.max() + px.min()) / 2.0 * dist
            shift_y = (py.max() + py.min()) / 2.0 * dist
            aim = aim + R * shift_x + U * shift_y
        off = P - aim
        x, y, z = off @ R, off @ U, off @ F
        dist = _fit(x, y, z, tan_half, aspect, diag) * 1.05
        loc = Vector(aim) - fwd * dist
        scale = None
    cam.location = loc
    cam.data.clip_start = max(1e-4, diag * 1e-3)
    cam.data.clip_end = (loc - center).length + diag * 4.0 + 10.0
    pose = {"view": view, "projection": "ortho" if ortho else "perspective",
            "location": [round(float(v), 4) for v in loc],
            "rotation_deg": [round(math.degrees(a), 2) for a in rot],
            "looking": [round(float(v), 3) for v in fwd]}
    if ortho:
        pose["ortho_scale"] = round(float(scale), 4)
        pose["meters_per_pixel"] = None
    else:
        pose["lens_mm"] = float(lens)
    return pose


class Renderer:
    """with Renderer(objects) as r: img = r.shot("front", "solid", wire=True, size=320) -> float RGBA (h, w, 4)."""

    def __init__(self, objects, scene=None, show=None):
        self.scene = scene or bpy.context.scene
        self.objects = [o for o in objects]
        self.show = show or []
        self.keep = _Restore()
        self.temp_objects, self.temp_data, self.temp_images = [], [], []
        self.dir = None
        self.world = None
        self.wires = []
        self.lens = 50.0
        self.rig = []       # studio lights and the shadow-catcher ground
        self.gpu = "auto"   # "auto": the GPU only when the person already set one up; "cuda": set it up (builds)

    # ----- setup / teardown -----
    def __enter__(self):
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="nighty_look_")
        sc = self.scene
        k = self.keep
        cam_data = bpy.data.cameras.new("NightyLookCam")
        cam = bpy.data.objects.new("NightyLookCam", cam_data)
        sc.collection.objects.link(cam)
        self.temp_objects.append(cam)
        self.temp_data.append(cam_data)
        self.cam = cam
        k.set(sc, "camera", cam)
        r = sc.render
        for attr, val in (("resolution_percentage", 100), ("pixel_aspect_x", 1.0), ("pixel_aspect_y", 1.0),
                          ("film_transparent", True), ("use_border", False), ("use_compositing", False),
                          ("use_sequencer", False), ("use_freestyle", False), ("use_motion_blur", False),
                          ("use_simplify", False), ("dither_intensity", 0.0), ("use_stamp", False)):
            k.set(r, attr, val)
        im = r.image_settings
        k.set(im, "file_format", "PNG")
        k.set(im, "color_mode", "RGBA")
        k.set(im, "color_depth", "8")
        k.set(im, "compression", 15)
        vs = sc.view_settings
        k.set(vs, "view_transform", "Standard")
        k.set(vs, "look", "None")
        k.set(vs, "exposure", 0.0)
        k.set(vs, "gamma", 1.0)
        k.set(vs, "use_curve_mapping", False)
        # only the asked objects (and nighty helpers never) show up
        wanted = set(o.name for o in self.objects) | set(o.name for o in self.show)
        for o in self.objects:  # cartoon outlines render with their object
            wanted |= {c.name for c in o.children_recursive if c.get("nighty_role") == "outline"}
        for o in sc.objects:
            if o.name in wanted or o is cam:
                continue
            if not o.hide_render:
                k.set(o, "hide_render", True)
        for o in self.objects:
            if o.hide_render:
                k.set(o, "hide_render", False)
        img = bpy.data.images.get("Render Result")
        if img is not None and len(img.render_slots):
            slots = img.render_slots
            slot = next((i for i, s in enumerate(slots) if s.name == "Nighty look"), None)
            if slot is None:
                try:
                    slots.new(name="Nighty look")
                    slot = len(slots) - 1
                except (RuntimeError, AttributeError):
                    slot = None
            if slot is not None:
                k.set(slots, "active_index", slot)
        return self

    def __exit__(self, *exc):
        self.keep.restore()
        for o in self.temp_objects:
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except ReferenceError:
                pass
        for d in self.temp_data:
            try:
                if isinstance(d, bpy.types.Camera):
                    bpy.data.cameras.remove(d)
                elif isinstance(d, bpy.types.Light):
                    bpy.data.lights.remove(d)
                elif isinstance(d, bpy.types.Mesh):
                    bpy.data.meshes.remove(d)
                elif isinstance(d, bpy.types.World):
                    bpy.data.worlds.remove(d)
            except ReferenceError:
                pass
        for i in self.temp_images:
            try:
                bpy.data.images.remove(i)
            except ReferenceError:
                pass
        if self.dir:
            import shutil
            shutil.rmtree(self.dir, ignore_errors=True)
        return False

    def _points(self, most=6000):
        if getattr(self, "_pts", None) is None:
            np = _np()
            dg = bpy.context.evaluated_depsgraph_get()
            pts = [core.world_points(o, True, dg) for o in self.objects]
            pts = [p for p in pts if len(p)]
            allp = np.concatenate(pts) if pts else np.zeros((0, 3))
            if len(allp) > most:
                allp = allp[np.linspace(0, len(allp) - 1, most).astype(int)]
            self._pts = allp
        return self._pts

    # ----- modes -----
    def _workbench(self, light, color_type="MATERIAL", single=(0.8, 0.8, 0.8), cavity=False):
        sc, k = self.scene, self.keep
        k.set(sc.render, "engine", "BLENDER_WORKBENCH")
        sh = sc.display.shading
        k.set(sh, "light", light)
        if light == "MATCAP":
            name = compat.studio_light("matcap", ["clay_studio.exr", "basic_1.exr", "basic_grey.exr"])
            if name:
                k.set(sh, "studio_light", name)
        elif light == "STUDIO":
            k.set(sh, "studio_light", "Default")
        k.set(sh, "color_type", color_type)
        k.set(sh, "single_color", single)
        k.set(sh, "show_cavity", cavity)
        if cavity:
            k.set(sh, "cavity_type", "BOTH")
            k.set(sh, "curvature_ridge_factor", 1.0)
            k.set(sh, "curvature_valley_factor", 1.0)
        k.set(sh, "show_shadows", False)
        k.set(sh, "show_xray", False)
        k.set(sh, "show_backface_culling", False)
        k.set(sh, "show_object_outline", False)
        k.set(sh, "show_specular_highlight", True)
        k.set(sc.display, "render_aa", "8")

    def _gpu(self):
        """Cycles on the GPU when it is ready: the person's own compute device, or CUDA for example builds."""
        try:
            prefs = bpy.context.preferences.addons["cycles"].preferences
        except (KeyError, AttributeError):
            return False
        if self.gpu == "cuda":
            k = self.keep
            for kind in ("CUDA", "HIP", "ONEAPI"):
                try:
                    k.set(prefs, "compute_device_type", kind)
                    prefs.get_devices()
                except (TypeError, ValueError):
                    continue
                devices = [d for d in prefs.devices if d.type == kind]
                if devices:
                    for d in prefs.devices:
                        k.set(d, "use", d.type == kind)
                    return True
            return False
        if self.gpu == "auto":
            return prefs.compute_device_type != "NONE" and any(d.use and d.type != "CPU" for d in prefs.devices)
        return False

    def _studio(self, b, diag, samples):
        """Product-shot lighting: soft key, fill and rim area lights, a dim studio HDRI for reflections, a
        shadow-catcher ground under the model, AgX color. Cycles with denoising."""
        sc, k = self.scene, self.keep
        k.set(sc.render, "engine", "CYCLES")
        cy = sc.cycles
        k.set(cy, "device", "GPU" if self._gpu() else "CPU")
        k.set(cy, "samples", int(samples))
        k.set(cy, "use_adaptive_sampling", True)
        k.set(cy, "adaptive_threshold", 0.03)
        k.set(cy, "use_denoising", True)
        k.set(cy, "denoiser", "OPENIMAGEDENOISE")
        k.set(cy, "max_bounces", 8)
        k.set(cy, "transparent_max_bounces", 12)
        k.set(cy, "transmission_bounces", 8)
        k.set(cy, "film_transparent_glass", False)
        if compat.set_view_transform(sc, "AgX"):
            for look in ("AgX - Medium High Contrast", "Medium High Contrast", "None"):
                if k.set(sc.view_settings, "look", look):
                    break
        if self.world is None:
            w = bpy.data.worlds.new("NightyLookWorld")
            self.temp_data.append(w)
            compat.ensure_nodes(w)
            nt = w.node_tree
            bg = compat.node(nt, "BACKGROUND") or nt.nodes.new("ShaderNodeBackground")
            out = compat.node(nt, "OUTPUT_WORLD") or nt.nodes.new("ShaderNodeOutputWorld")
            nt.links.new(bg.outputs[0], out.inputs["Surface"])
            name = compat.studio_light("world", ["studio.exr", "interior.exr", "forest.exr"])
            if name:
                env = nt.nodes.new("ShaderNodeTexEnvironment")
                image = bpy.data.images.load(compat.studio_light_path("world", name), check_existing=True)
                if image.users == 0:
                    self.temp_images.append(image)
                env.image = image
                nt.links.new(env.outputs["Color"], bg.inputs["Color"])
            bg.inputs["Strength"].default_value = 0.3
            self.world = w
        k.set(sc, "world", self.world)
        for o in sc.objects:
            if o.type == "LIGHT" and not o.hide_render and o not in self.rig:
                k.set(o, "hide_render", True)
        if not self.rig:
            self._make_rig(b, diag)
        for r in self.rig:
            r.hide_render = False

    def _make_rig(self, b, diag):
        c = b.center
        dist = diag * 2.4

        def light(name, az, el, power, size, color):
            data = bpy.data.lights.new(name, "AREA")
            data.shape = "DISK"
            data.size = size
            data.energy = power
            data.color = color
            obj = bpy.data.objects.new(name, data)
            a, e = math.radians(az), math.radians(el)
            d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
            obj.location = c + d * dist
            obj.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
            self.scene.collection.objects.link(obj)
            self.temp_objects.append(obj)
            self.temp_data.append(data)
            self.rig.append(obj)
        p = 9.0 * dist * dist
        light("NightyKey", -40, 42, p, diag * 1.4, (1.0, 0.96, 0.9))
        light("NightyFill", 55, 12, p * 0.35, diag * 2.0, (0.88, 0.93, 1.0))
        light("NightyRim", 165, 35, p * 1.6, diag * 0.7, (1.0, 1.0, 1.0))   # bright and small: a crisp outline
        me = bpy.data.meshes.new("NightyGround")
        s = diag * 30
        me.from_pydata([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)], [], [(0, 1, 2, 3)])
        ground = bpy.data.objects.new("NightyGround", me)
        ground.location = (c.x, c.y, b.min.z)
        ground.is_shadow_catcher = True
        self.scene.collection.objects.link(ground)
        self.temp_objects.append(ground)
        self.temp_data.append(me)
        self.rig.append(ground)

    # ----- wireframe helpers -----
    def _make_wires(self):
        if self.wires:
            return
        dg = bpy.context.evaluated_depsgraph_get()
        for o in self.objects:
            if o.type not in ("MESH", "CURVE", "SURFACE", "FONT", "META"):
                continue
            try:
                me = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
            except RuntimeError:
                continue
            if len(me.edges) > 150000:
                bpy.data.meshes.remove(me)
                continue
            w = bpy.data.objects.new("NightyLookWire", me)
            w.matrix_world = o.matrix_world.copy()
            self.scene.collection.objects.link(w)
            weld = w.modifiers.new("Weld", "WELD")  # doubled points make spikes in the wire
            weld.merge_threshold = 1e-6
            mod = w.modifiers.new("Wire", "WIREFRAME")
            mod.use_replace = True
            mod.use_even_offset = False
            mod.use_relative_offset = False
            mod.offset = 0.0
            mod.use_boundary = True
            w.color = (0.0, 0.0, 0.0, 1.0)  # black in the line pass; drawn as WIRE_COLOR
            w.hide_render = True
            self.temp_objects.append(w)
            self.temp_data.append(me)
            self.wires.append(w)

    # ----- one picture -----
    def _render(self, w, h):
        sc = self.scene
        sc.render.resolution_x = int(w)
        sc.render.resolution_y = int(h)
        bpy.ops.render.render()
        import os
        path = os.path.join(self.dir, "shot.png")
        bpy.data.images["Render Result"].save_render(path)
        return read_png_pixels(path)

    def shot(self, view, mode="solid", wire=False, size=320, height=None, pose_only=False, camera=None,
             persp=None):
        """One rendered view as float RGBA (rows bottom to top) and its camera pose."""
        np = _np()
        if view not in VIEWS:
            raise ValueError(f"view must be one of {sorted(VIEWS)}")
        sc, k = self.scene, self.keep
        h = int(height or size)
        w = int(size)
        k.set(sc.render, "resolution_x", w)
        k.set(sc.render, "resolution_y", h)
        b = core.bounds(self.objects)
        corners = b.corners()
        diag = max(b.size.length, 1e-4)
        if camera:  # an exact ortho camera (reference sheets)
            self.cam.rotation_euler = _view_rotation(view, b.center, diag, b.size)[0]
            self.cam.data.type = "ORTHO"
            self.cam.data.ortho_scale = camera["ortho_scale"]
            mat = self.cam.rotation_euler.to_matrix()
            right, up, fwd = mat.col[0], mat.col[1], -mat.col[2]
            c = Vector(camera["center"])
            self.cam.location = right * c.dot(right) + up * c.dot(up) + fwd * b.center.dot(fwd) - fwd * (diag * 2 + 1.0)
            self.cam.data.clip_start = max(1e-4, diag * 1e-3)
            self.cam.data.clip_end = diag * 6 + 10
            pose = {"view": view, "projection": "ortho", "ortho_scale": camera["ortho_scale"]}
        else:
            lens = 70.0 if mode == "material" and not (persp is False) and \
                (view.startswith("three") or view == "hero") else 50.0
            self.lens = lens
            self.cam["nighty_aspect"] = w / float(h)
            pose = _frame(self.cam, view, corners, b.center, diag, persp, self._points(), lens=lens, size=b.size)
        if pose.get("projection") == "ortho" and pose.get("ortho_scale"):
            pose["meters_per_pixel"] = round(pose["ortho_scale"] / max(w, h), 6)
        core.update()
        if pose_only:
            return None, pose
        # pass A: the look
        for wo in self.wires:
            wo.hide_render = True
        for r in self.rig:
            r.hide_render = mode != "material"
        if mode == "material":
            self._studio(b, diag, 24 if max(w, h) <= 400 else 48 if max(w, h) <= 700 else 80)
        elif mode == "matcap":
            self._workbench("MATCAP", "SINGLE", (0.85, 0.85, 0.85))
        elif mode == "silhouette":
            self._workbench("FLAT", "SINGLE", (1.0, 1.0, 1.0))
        else:
            self._workbench("STUDIO", "MATERIAL", cavity=True)
        img = self._render(w, h)
        if wire and mode != "silhouette":
            self._make_wires()
            if self.wires:
                img = self._wire_pass(img, pose, w, h, diag)
        return img, pose

    def _wire_pass(self, base, pose, w, h, diag):
        np = _np()
        sc, k = self.scene, self.keep
        if pose["projection"] == "ortho":
            px = pose["ortho_scale"] / max(w, h)
        else:
            dist = (Vector(pose["location"]) - core.bounds(self.objects).center).length
            px = 2 * dist * (18.0 / self.lens) / max(w, h)
        for wo in self.wires:
            wo.modifiers["Wire"].thickness = px * 0.9
            wo.hide_render = False
        self._workbench("FLAT", "OBJECT")
        for r in self.rig:
            r.hide_render = True
        colors = []
        for o in self.objects:
            colors.append((o, tuple(o.color)))
            o.color = (1.0, 1.0, 1.0, 1.0)
        try:
            mask = self._render(w, h)
        finally:
            for o, c in colors:
                o.color = c
            for wo in self.wires:
                wo.hide_render = True
        lum = mask[..., :3].mean(axis=-1, keepdims=True)
        a = mask[..., 3:4]
        line = (1.0 - lum) * a * 0.85
        out = base.copy()
        out[..., :3] = out[..., :3] * (1 - line) + np.array(WIRE_COLOR) * line
        out[..., 3:4] = np.maximum(out[..., 3:4], a)
        return out


# ---------- pictures as arrays ----------

def read_png_pixels(path):
    """Loads a picture into float RGBA numpy (h, w, 4), rows bottom to top (Blender's order)."""
    np = _np()
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = img.size
        px = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(img)
    return px.reshape(h, w, 4)


def over_background(img, colors=BACKGROUND):
    """Composites RGBA over a soft vertical gradient; returns RGB."""
    np = _np()
    h = img.shape[0]
    t = np.linspace(0.0, 1.0, h)[:, None, None]  # bottom 0 -> top 1
    top, bottom = np.array(colors[0]), np.array(colors[1])
    bg = bottom * (1 - t) + top * t
    a = img[..., 3:4]
    return img[..., :3] * a + bg * (1 - a)


# a tiny 3x5 pixel font for the view labels
_FONT = {
    "A": "010101111101101", "B": "110101110101110", "C": "011100100100011", "D": "110101101101110",
    "E": "111100110100111", "F": "111100110100100", "G": "011100101101011", "H": "101101111101101",
    "I": "111010010010111", "K": "101101110101101", "L": "100100100100111", "M": "101111111101101",
    "N": "110101101101101", "O": "010101101101010", "P": "110101110100100", "R": "110101110101101",
    "S": "011100010001110", "T": "111010010010010", "U": "101101101101111", "W": "101101111111101",
    "0": "111101101101111", "1": "010110010010111", "2": "110001010100111", "3": "110001010001110",
    "4": "101101111001001", "/": "001001010100100", " ": "000000000000000", "-": "000000111000000",
    "J": "001001001101010", "Q": "010101101110011", "V": "101101101101010", "X": "101101010101101",
    "Y": "101101010010010", "Z": "111001010100111", "5": "111100110001110", "6": "011100111101111",
    "7": "111001010010010", "8": "111101111101111", "9": "111101111001110", ".": "000000000000010",
    ":": "000010000010000", "+": "000010111010000", "(": "010100100100010", ")": "010001001001010",
    "%": "101001010100101", "=": "000111000111000", "_": "000000000000111", ",": "000000000010100",
}


def _label(rgb, text, scale=2):
    """Draws text into the top-left corner of an RGB image (rows bottom to top)."""
    np = _np()
    h, w = rgb.shape[:2]
    x = 4
    for ch in text.upper():
        bits = _FONT.get(ch)
        if bits is None:
            x += 4 * scale
            continue
        for r in range(5):
            for c in range(3):
                if bits[r * 3 + c] == "1":
                    y0 = h - 4 - (r + 1) * scale
                    x0 = x + c * scale
                    rgb[max(0, y0 - 1):y0 + scale + 1, max(0, x0 - 1):x0 + scale + 1] = (0.05, 0.05, 0.05)
        for r in range(5):
            for c in range(3):
                if bits[r * 3 + c] == "1":
                    y0 = h - 4 - (r + 1) * scale
                    x0 = x + c * scale
                    rgb[y0:y0 + scale, x0:x0 + scale] = (0.95, 0.95, 0.95)
        x += 4 * scale
    return rgb


def grid(images, labels=None, cols=None, gap=2):
    """Lays RGB images of equal size out in a grid (rows bottom to top). Returns RGB."""
    np = _np()
    n = len(images)
    cols = cols or (1 if n == 1 else 2 if n <= 4 else 3)
    rows = int(math.ceil(n / float(cols)))
    h, w = images[0].shape[:2]
    out = np.full((rows * h + (rows - 1) * gap, cols * w + (cols - 1) * gap, 3), 0.12)
    for i, im in enumerate(images):
        r, c = divmod(i, cols)
        y = (rows - 1 - r) * (h + gap)
        x = c * (w + gap)
        cell = im.copy()
        if labels:
            cell = _label(cell, labels[i])
        out[y:y + h, x:x + w] = cell
    return out


def png_bytes(rgb):
    """Encodes an RGB(A) float array (rows bottom to top) as PNG bytes (sRGB values as they are)."""
    np = _np()
    import struct
    import zlib
    arr = np.clip(rgb, 0.0, 1.0)
    arr = (arr[::-1] * 255.0 + 0.5).astype(np.uint8)
    h, w, ch = arr.shape
    raw = np.concatenate([np.zeros((h, 1), np.uint8), arr.reshape(h, w * ch)], axis=1).tobytes()

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    color_type = 6 if ch == 4 else 2
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, color_type, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


_REF_CACHE = {}


def reference_pixels(img, max_side=1024):
    """A reference picture as float RGBA (rows bottom to top), at most max_side pixels (cached)."""
    np = _np()
    key = (img.name, img.size[0], img.size[1], max_side)
    if key in _REF_CACHE:
        return _REF_CACHE[key]
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    step = max(1, int(math.ceil(max(w, h) / float(max_side))))
    px = px[::step, ::step]
    if len(_REF_CACHE) > 8:
        _REF_CACHE.clear()
    _REF_CACHE[key] = (px, step)
    return px, step


def reference_frame(ref):
    """Where a reference picture sits: its view, world center, meters per source pixel, source size."""
    core.update()  # a new object's matrix_world is stale until the depsgraph runs
    img = ref.data
    w, h = img.size
    size = ref.empty_display_size * max(ref.scale[0], ref.scale[1])
    return {"view": ref.get("nighty_view"), "center": ref.matrix_world.translation.copy(),
            "m_per_px": size / float(max(w, h)), "w": w, "h": h}


def overlay_references(img, pose, refs, size_wh, opacity=0.6):
    """The shot over the reference pictures that match this ortho view (model a bit see-through) -> RGB, or None."""
    np = _np()
    if pose.get("projection") != "ortho":
        return None
    w, h = size_wh
    rot = Euler([math.radians(a) for a in pose["rotation_deg"]], "XYZ").to_matrix()
    right, up = rot.col[0], rot.col[1]
    loc = Vector(pose["location"])
    scale = pose["ortho_scale"]
    ow, oh = (scale, scale * h / w) if w >= h else (scale * w / h, scale)
    us = (loc.dot(right) + ((np.arange(w) + 0.5) / w - 0.5) * ow)[None, :]
    vs = (loc.dot(up) + ((np.arange(h) + 0.5) / h - 0.5) * oh)[:, None]
    bg = over_background(np.zeros((h, w, 4), np.float32))
    matched = False
    for ref in refs:
        if ref.get("nighty_view") != pose["view"] or ref.data is None:
            continue
        matched = True
        fr = reference_frame(ref)
        px, step = reference_pixels(ref.data)
        m = fr["m_per_px"] * step
        cu, cv = fr["center"].dot(right), fr["center"].dot(up)
        ph, pw = px.shape[:2]
        ix = np.broadcast_to(np.floor((us - cu) / m + pw / 2.0).astype(np.int64), (h, w))
        iy = np.broadcast_to(np.floor((vs - cv) / m + ph / 2.0).astype(np.int64), (h, w))
        ok = (ix >= 0) & (ix < pw) & (iy >= 0) & (iy < ph)
        sample = np.zeros((h, w, 4), np.float32)
        sample[ok] = px[iy[ok], ix[ok]]
        a = sample[..., 3:4] * opacity
        bg = bg * (1 - a) + sample[..., :3] * a
    if not matched:
        return None
    ma = img[..., 3:4] * 0.7
    return img[..., :3] * ma + bg * (1 - ma)


def look(objects, views=("front", "right", "top", "three_quarter"), mode="solid", wire=False, size=320,
         combine=True, persp=None, labels=True, show=None, references=(), gpu="auto", height=None):
    """Renders views of objects. Returns (list of PNG bytes, list of camera poses). combine=True: one grid picture."""
    gen = look_steps(objects, views, mode, wire, size, combine, persp, labels, show, references, gpu, height)
    while True:
        try:
            next(gen)
        except StopIteration as stop:
            return stop.value


_WARM = {"done": False}


def warm_up():
    """One tiny off-screen render. The first render of a Blender session sets up the render engine and its GPU
    shaders (1-2 s, once); the addon does this right after the AI pairs, so the AI's first look never blocks Blender
    for that long. Returns True when it rendered, False when it was already done or could not run."""
    if _WARM["done"]:
        return False
    _WARM["done"] = True
    me = obj = None
    try:
        me = bpy.data.meshes.new("NightyWarmUp")
        me.from_pydata([(-0.05, -0.05, 0), (0.05, -0.05, 0), (0.05, 0.05, 0), (-0.05, 0.05, 0), (0, 0, 0.08)], [],
                       [(0, 1, 2, 3), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)])
        obj = bpy.data.objects.new("NightyWarmUp", me)
        bpy.context.scene.collection.objects.link(obj)
        with Renderer([obj]) as r:
            r.shot("front", "solid", size=64)
        return True
    except Exception:  # noqa: BLE001 - a warm-up must never get in the person's way
        return False
    finally:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        if me is not None:
            bpy.data.meshes.remove(me)


def look_steps(objects, views=("front", "right", "top", "three_quarter"), mode="solid", wire=False, size=320,
               combine=True, persp=None, labels=True, show=None, references=(), gpu="auto", height=None):
    """look() as a jobs generator: the setup, then one view per step (each a fraction of a second at look sizes),
    so Blender's UI keeps running between them. Yields (progress, message); returns (pngs, poses)."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    objects = core.to_list(objects)
    if not objects:
        raise ValueError("nothing to look at")
    size = max(64, min(1024, int(size)))
    views = list(views)
    shots, poses = [], []
    with Renderer(objects, show=show) as r:
        r.gpu = gpu
        if wire and mode != "material":
            r._make_wires()                       # the wire copies: their own step
        yield (0.1, "Set up")
        for i, v in enumerate(views):
            img, pose = r.shot(v, mode, wire=wire, size=size, height=height,
                               persp=persp if not (v.startswith("three_quarter") or v == "hero") else None)
            over = overlay_references(img, pose, references, (size, height or size)) if references else None
            if over is not None:
                shots.append(over)
            else:
                bg = STUDIO_BACKGROUND if mode == "material" else BACKGROUND
                shots.append(over_background(img, bg) if mode != "silhouette" else img[..., :3] * 0 + img[..., 3:4])
            poses.append(pose)
            _WARM["done"] = True
            yield (0.1 + 0.85 * (i + 1) / len(views), f"View {v}")
    if combine:
        return [png_bytes(grid(shots, [LABELS.get(v, v) for v in views] if labels else None))], poses
    return [png_bytes(s) for s in shots], poses


# ---------- studio renders in a background Blender (the look tool: never freezes the person's Blender) ----------

def material_look_steps(objects, views=("hero",), size=384, height=None, wire=False, persp=None, labels=True,
                        combine=True):
    """A jobs generator: copies the objects to a background `blender -b`, renders material views there (GPU when
    it has one), and returns {"pngs": [bytes], "poses": [...]}. Yields (progress, message) slices."""
    from .bake.job import WorkerJob, steps
    objects = core.to_list(objects)
    blocks = set(objects)
    for o in objects:
        blocks |= {c for c in o.children_recursive if c.get("nighty_role") == "outline"}
    spec = {"objects": [o.name for o in objects], "views": list(views), "size": int(size),
            "height": int(height) if height else None, "wire": bool(wire), "persp": persp, "labels": bool(labels),
            "combine": bool(combine)}
    job = WorkerJob("look", spec, blocks)

    def finish(res):
        if not res or res.get("error"):
            raise RuntimeError((res or {}).get("error") or "the render worker gave no result")
        pngs = []
        for path in res["pngs"]:
            with open(path, "rb") as f:
                pngs.append(f.read())
        return {"pngs": pngs, "poses": res["poses"]}
    return (yield from steps(job, finish))


def worker_look(spec, progress):
    """The worker side of material_look_steps (runs inside the background Blender)."""
    import os
    objs = [bpy.data.objects[n] for n in spec["objects"] if n in bpy.data.objects]
    progress(0.15, "Rendering")
    pngs, poses = look(objs, views=spec["views"], mode="material", wire=spec.get("wire", False),
                       size=spec["size"], height=spec.get("height"), combine=spec.get("combine", True),
                       persp=spec.get("persp"), labels=spec.get("labels", True), gpu="cuda")
    paths = []
    for i, data in enumerate(pngs):
        p = os.path.join(spec["job_dir"], f"look_{i}.png")
        with open(p, "wb") as f:
            f.write(data)
        paths.append(p)
    progress(1.0, "Done")
    return {"pngs": paths, "poses": poses}
