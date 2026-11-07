# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender 4.2 / 4.5 / 5.x differences in one place. Use these where the raw API drifted.

    n.compat.set_engine(scene, "eevee")         # BLENDER_EEVEE_NEXT (4.x) or BLENDER_EEVEE (5.x)
    n.compat.boolean_solver("fast")              # FAST (4.x) or FLOAT (5.x)
    tree = n.compat.compositor_tree(scene)       # scene.node_tree (4.x) or scene.compositing_node_group (5.x)
    for fc in n.compat.fcurves(obj): ...         # action.fcurves (4.x) or the slot's channelbag (4.4+ / 5.x)
"""

import bpy

VERSION = tuple(bpy.app.version)

__all__ = []  # reached as nighty.compat.<name>


def at_least(major, minor=0, patch=0):
    """True when this Blender is at least that version. at_least(5) -> 5.0 or newer."""
    return VERSION >= (major, minor, patch)


def enum_items(struct, prop):
    """The identifiers of a static enum, e.g. enum_items(bpy.types.BooleanModifier, "solver")."""
    try:
        return [i.identifier for i in struct.bl_rna.properties[prop].enum_items]
    except (KeyError, AttributeError):
        return []


# ---------- render engines ----------

def eevee_id():
    """The EEVEE engine id of this Blender: BLENDER_EEVEE_NEXT before 5.0, BLENDER_EEVEE from 5.0."""
    return "BLENDER_EEVEE" if at_least(5) else "BLENDER_EEVEE_NEXT"


_ENGINE_NAMES = {
    "eevee": ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"),
    "cycles": ("CYCLES",),
    "workbench": ("BLENDER_WORKBENCH",),
}


def set_engine(scene, name):
    """Sets the render engine by a plain name ("eevee", "cycles", "workbench") or an id. Returns the id set."""
    tries = _ENGINE_NAMES.get(str(name).lower(), (name,))
    if str(name).lower() == "eevee":
        tries = (eevee_id(),) + tuple(t for t in tries if t != eevee_id())
    last = None
    for engine in tries:
        try:
            scene.render.engine = engine
            return engine
        except TypeError as error:  # the message lists the valid engines
            last = error
    raise ValueError(f"render engine {name!r} not available: {last}")


# ---------- booleans ----------

def boolean_solvers():
    """The boolean solvers this Blender has: 4.2: FAST, EXACT; 5.x: FLOAT, EXACT, MANIFOLD."""
    return enum_items(bpy.types.BooleanModifier, "solver")


def boolean_solver(name="exact"):
    """A solver id for a plain name: "exact", "fast" / "float" (renamed in 5.0), "manifold" (5.x; else EXACT)."""
    have = boolean_solvers()
    key = str(name).upper()
    if key in ("FAST", "FLOAT"):
        for solver in ("FLOAT", "FAST"):
            if solver in have:
                return solver
    if key == "MANIFOLD" and "MANIFOLD" in have:
        return "MANIFOLD"
    return "EXACT"


# ---------- compositor ----------

def compositor_tree(scene, create=True):
    """The scene's compositor node tree (4.x: scene.node_tree with use_nodes; 5.x: compositing_node_group)."""
    if hasattr(scene, "compositing_node_group"):
        tree = scene.compositing_node_group
        if tree is None and create:
            tree = bpy.data.node_groups.new(f"{scene.name} Compositor", "CompositorNodeTree")
            scene.compositing_node_group = tree
        return tree
    if create and not scene.use_nodes:
        scene.use_nodes = True
    return scene.node_tree


# ---------- animation ----------

def fcurves(target):
    """F-curves of an action, or of an object's / ID's current action (legacy and layered actions)."""
    action = target if isinstance(target, bpy.types.Action) else None
    slot = None
    if action is None:
        anim = getattr(target, "animation_data", None)
        if anim is None or anim.action is None:
            return []
        action = anim.action
        slot = getattr(anim, "action_slot", None)
    if hasattr(action, "fcurves") and not getattr(action, "is_action_layered", False):
        return list(action.fcurves)
    try:
        from bpy_extras import anim_utils
        if slot is None and len(action.slots):
            slot = action.slots[0]
        bag = anim_utils.action_get_channelbag_for_slot(action, slot)
        return list(bag.fcurves) if bag else []
    except (ImportError, AttributeError):
        return list(getattr(action, "fcurves", []))


def find_fcurve(target, data_path, index=0):
    """One F-curve by data path and index, or None."""
    for fc in fcurves(target):
        if fc.data_path == data_path and fc.array_index == index:
            return fc
    return None


def keyframe(obj, data_path, frame, value=None, index=-1):
    """Sets (when value is given) and keys a property: keyframe(obj, "location", 10, (0, 0, 1))."""
    if value is not None:
        prop = obj.path_resolve(data_path)
        if index >= 0:
            prop[index] = value
        elif hasattr(prop, "__len__"):
            for i, v in enumerate(value):
                prop[i] = v
        else:
            setattr(obj, data_path, value)
    return obj.keyframe_insert(data_path, index=index, frame=frame)


# ---------- nodes and materials ----------

def ensure_nodes(idblock):
    """Turns nodes on for a material / world / light where that is still a switch (always on in 5.x)."""
    if hasattr(idblock, "use_nodes") and not idblock.use_nodes:
        try:
            idblock.use_nodes = True
        except (AttributeError, TypeError):
            pass
    return idblock.node_tree


def node(tree, node_type):
    """The first node of a type (types are not translated, names are): node(tree, "BSDF_PRINCIPLED")."""
    return next((n for n in tree.nodes if n.type == node_type), None)


def principled(material):
    """The Principled BSDF of a material (nodes turned on first)."""
    return node(ensure_nodes(material), "BSDF_PRINCIPLED")


# Old Principled socket names (3.x) -> 4.x / 5.x names.
SOCKET_ALIASES = {
    "Emission": "Emission Color", "Specular": "Specular IOR Level", "Subsurface": "Subsurface Weight",
    "Transmission": "Transmission Weight", "Clearcoat": "Coat Weight", "Clearcoat Roughness": "Coat Roughness",
    "Sheen": "Sheen Weight", "Sheen Tint": "Sheen Tint", "Subsurface Color": "Base Color",
}


def socket(node_, name):
    """An input socket by name, accepting old names (Emission -> Emission Color, Specular -> Specular IOR Level...)."""
    if node_ is None:
        return None
    sock = node_.inputs.get(name)
    if sock is None and name in SOCKET_ALIASES:
        sock = node_.inputs.get(SOCKET_ALIASES[name])
    return sock


def set_input(node_, name, value):
    """Sets an input's default value if the socket exists (old names accepted). Returns True when set."""
    sock = socket(node_, name)
    if sock is None or not hasattr(sock, "default_value"):
        return False
    current = sock.default_value
    if hasattr(current, "__len__") and not isinstance(value, (int, float)) and len(value) < len(current):
        value = tuple(value) + tuple(current)[len(value):]  # RGB -> RGBA
    sock.default_value = value
    return True


def set_transparent(material, blended=True):
    """Transparency for EEVEE: surface_render_method (4.2+) or blend_method (older)."""
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "BLENDED" if blended else "DITHERED"
    elif hasattr(material, "blend_method"):
        material.blend_method = "BLEND" if blended else "HASHED"


# ---------- meshes ----------

def shade_smooth(mesh, angle=None):
    """Smooth shading; with an angle (degrees) edges sharper than it are marked sharp (4.1+ "smooth by angle")."""
    import math
    if hasattr(mesh, "shade_smooth"):
        mesh.shade_smooth()
    else:
        mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    if angle is not None:
        if hasattr(mesh, "set_sharp_from_angle"):
            mesh.set_sharp_from_angle(angle=math.radians(angle))
    mesh.update()


def shade_flat(mesh):
    """Flat shading."""
    if hasattr(mesh, "shade_flat"):
        mesh.shade_flat()
    else:
        mesh.polygons.foreach_set("use_smooth", [False] * len(mesh.polygons))
    mesh.update()


def sculpt_brush_type_attr():
    """The brush attribute naming the sculpt tool: sculpt_tool (4.x) or sculpt_brush_type (5.x)."""
    return "sculpt_brush_type" if "sculpt_brush_type" in bpy.types.Brush.bl_rna.properties else "sculpt_tool"


# ---------- scene, view ----------

def set_view_transform(scene, name="Standard"):
    """Sets the color view transform when it exists (Standard, AgX, Filmic...). Returns True when set."""
    try:
        scene.view_settings.view_transform = name
        return True
    except TypeError:
        return False


def studio_light(kind, prefer):
    """A studio light file name of a kind ("matcap", "world", "studio") that exists here, from a preference list."""
    import os
    folder = os.path.join(bpy.utils.system_resource("DATAFILES", path="studiolights"), kind)
    try:
        have = sorted(os.listdir(folder))
    except OSError:
        return None
    for name in prefer:
        if name in have:
            return name
    files = [f for f in have if f.endswith((".exr", ".sl"))]
    return files[0] if files else None


def studio_light_path(kind, name):
    """The full path of a studio light file (e.g. kind "world", name "forest.exr")."""
    import os
    folder = bpy.utils.system_resource("DATAFILES", path="studiolights")
    return os.path.join(folder, kind, name)


def temp_override(**kwargs):
    """bpy.context.temp_override (4.0+), for the few operators that need a context."""
    return bpy.context.temp_override(**kwargs)
