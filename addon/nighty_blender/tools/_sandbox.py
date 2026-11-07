# SPDX-License-Identifier: GPL-3.0-or-later
# The 'safe' level's restricted views of bpy and the nighty library for run_python (tools/core.py).
#
# Safe is promised as: modelling only, no files, no other programs, no network, no running more code later. The AST
# check in core.py refuses imports, dunder attributes and a few escape attribute names; this module closes the holes
# that are left once the script holds `bpy` and `nighty`, by handing it restricted VIEWS instead of the real modules:
#
#   - bpy.ops   -> only modelling operator categories (object, mesh, curve, ... ). wm / export_* / import_* / file /
#                  render / image / script / text / preferences / extensions are all refused, so save, open, quit,
#                  url_open, export, import, run-script and render-to-file have no operator to call.
#   - bpy.data  -> usable, but `libraries` (write / load a .blend) is gone and the file-reading collections
#                  (images, fonts, sounds, movieclips, cache_files) refuse `.load`. `.new` (in memory) still works.
#   - bpy.context -> usable, but `preferences` (settings, auto-run scripts) is gone; `blend_data` routes to the safe
#                  bpy.data so it can't be used to slip past it.
#   - bpy.app   -> only read-only version / build info; `handlers`, `timers` and `driver_namespace` (code that would
#                  run later, outside this gate) are gone.
#   - bpy.utils, bpy.msgbus, bpy.path -> gone.
#   - nighty    -> the modelling API and the safe submodules only; no path to mesh / bake / export / materials /
#                  presets / engine (they write files, start programs or download), and no raw module (bpy, os, ...)
#                  reachable through a submodule's globals.
#
# The real functions these views wrap run as ordinary, trusted library code (they are compiled module code, not the
# AI's script), so the nighty library and the tools keep full access; only the AI's own run_python script is limited.

import types

from . import ToolError

# How every refusal ends: the person, in Blender, can lift the limit. Kept short (the owner dislikes long text).
SWITCH = " The person can switch to 'full' in the Nighty panel to run any Python."


def _refuse(what):
    raise ToolError("Safe scripts can't use %s.%s" % (what, SWITCH))


# ---------- bpy ----------

# Operator categories a safe script may use: modelling, nothing that touches files, settings, the window or renders.
SAFE_OPS = frozenset((
    "object", "mesh", "curve", "curves", "surface", "mball", "transform", "uv", "material", "node", "geometry",
    "armature", "pose", "lattice", "sculpt", "paint", "gpencil", "grease_pencil", "brush", "nla", "anim", "action",
))

# bpy.app attributes a safe script may read (version / build facts). Everything else (handlers, timers,
# driver_namespace, ...) is refused: those would run code later, outside this gate.
_APP_READ = frozenset((
    "version", "version_string", "version_cycle", "version_char", "version_file", "background", "binary_path",
    "debug", "factory_startup", "build_date", "build_hash", "build_platform", "build_type", "build_commit_date",
    "build_commit_time", "build_branch",
))

# bpy.data collections that can read a file with `.load`: allowed, but `.load` on them is refused (creating datablocks
# in memory with `.new` stays fine). `libraries` is removed entirely (it writes / loads .blend files).
_DATA_LOADERS = frozenset(("images", "fonts", "sounds", "movieclips", "cache_files"))


class _SafeColl:
    """A bpy data collection with its file-reading `.load` refused; everything else (new, remove, get, indexing,
    iteration) passes through."""

    def __init__(self, coll, owner):
        object.__setattr__(self, "_coll", coll)
        object.__setattr__(self, "_owner", owner)

    def __getattr__(self, name):
        if name == "load":
            _refuse("bpy.data.%s.load (that reads a file)" % object.__getattribute__(self, "_owner"))
        return getattr(object.__getattribute__(self, "_coll"), name)

    def __getitem__(self, key):
        return object.__getattribute__(self, "_coll")[key]

    def __iter__(self):
        return iter(object.__getattribute__(self, "_coll"))

    def __len__(self):
        return len(object.__getattribute__(self, "_coll"))

    def __contains__(self, key):
        return key in object.__getattribute__(self, "_coll")


class _SafeData:
    """bpy.data without `libraries` (write / load a .blend) and with file-reading collections' `.load` refused."""

    def __init__(self, data):
        object.__setattr__(self, "_data", data)

    def __getattr__(self, name):
        if name == "libraries":
            _refuse("bpy.data.libraries (that writes or loads a .blend file)")
        value = getattr(object.__getattribute__(self, "_data"), name)
        if name in _DATA_LOADERS:
            return _SafeColl(value, name)
        return value


class _SafeContext:
    """bpy.context without `preferences`; `blend_data` routes to the safe bpy.data."""

    def __init__(self, context, safe_data):
        object.__setattr__(self, "_context", context)
        object.__setattr__(self, "_safe_data", safe_data)

    def __getattr__(self, name):
        if name == "preferences":
            _refuse("bpy.context.preferences (that changes settings)")
        if name == "blend_data":
            return object.__getattribute__(self, "_safe_data")
        return getattr(object.__getattribute__(self, "_context"), name)


class _SafeApp:
    """bpy.app with only read-only version / build info (no handlers, timers or driver_namespace)."""

    def __init__(self, app):
        object.__setattr__(self, "_app", app)

    def __getattr__(self, name):
        if name in _APP_READ:
            return getattr(object.__getattribute__(self, "_app"), name)
        _refuse("bpy.app.%s" % name)


class _SafeOps:
    """bpy.ops limited to the modelling operator categories in SAFE_OPS."""

    def __init__(self, ops):
        object.__setattr__(self, "_ops", ops)

    def __getattr__(self, name):
        if name in SAFE_OPS:
            return getattr(object.__getattribute__(self, "_ops"), name)
        _refuse("bpy.ops.%s.* (only modelling operators run at the safe level)" % name)


class _SafeBpy:
    """What `bpy` means to a safe script: data and context without file or settings access, an allow-list of
    operator categories, read-only app info, and types / props. utils, msgbus, path and anything else are refused."""

    def __init__(self, bpy):
        object.__setattr__(self, "_bpy", bpy)
        object.__setattr__(self, "_data", _SafeData(bpy.data))
        object.__setattr__(self, "_ops", _SafeOps(bpy.ops))
        object.__setattr__(self, "_app", _SafeApp(bpy.app))

    @property
    def data(self):
        return object.__getattribute__(self, "_data")

    @property
    def ops(self):
        return object.__getattribute__(self, "_ops")

    @property
    def app(self):
        return object.__getattribute__(self, "_app")

    @property
    def context(self):
        # context is read live (the active object etc. change as the script runs), so wrap it fresh each time.
        bpy = object.__getattribute__(self, "_bpy")
        return _SafeContext(bpy.context, object.__getattribute__(self, "_data"))

    @property
    def types(self):
        return object.__getattribute__(self, "_bpy").types

    @property
    def props(self):
        return object.__getattribute__(self, "_bpy").props

    def __getattr__(self, name):
        _refuse("bpy.%s" % name)


def safe_bpy(bpy):
    return _SafeBpy(bpy)


# ---------- nighty ----------

# nighty submodules a safe script must never reach: they write files, start programs or download.
_UNSAFE_NIGHTY = frozenset(("mesh", "bake", "export", "materials", "presets", "engine"))


class _SafeNightyModule:
    """A nighty submodule (core, shapes, modify, ...) for a safe script: its functions, classes and constants, but
    no raw module reachable through it (so `nighty.core.bpy` and the like are refused)."""

    def __init__(self, module, name):
        object.__setattr__(self, "_module", module)
        object.__setattr__(self, "_name", name)

    def __getattr__(self, name):
        value = getattr(object.__getattribute__(self, "_module"), name)
        if isinstance(value, types.ModuleType):
            _refuse("nighty.%s.%s (that is a raw module)" % (object.__getattribute__(self, "_name"), name))
        return value


class _SafeNighty:
    """What `nighty` means to a safe script: the modelling API (box, bevel, material, verify, ...) and the safe
    submodules, with no path to the file / process / download submodules or to a raw module like bpy or os."""

    def __init__(self, pkg, safe_submodules):
        object.__setattr__(self, "_pkg", pkg)
        object.__setattr__(self, "_ok", frozenset(safe_submodules))

    def __getattr__(self, name):
        if name in _UNSAFE_NIGHTY:
            _refuse("nighty.%s (it writes files, starts a program or downloads)" % name)
        value = getattr(object.__getattribute__(self, "_pkg"), name)
        if isinstance(value, types.ModuleType):
            if name in object.__getattribute__(self, "_ok"):
                return _SafeNightyModule(value, name)
            _refuse("nighty.%s (it writes files, starts a program or downloads)" % name)
        return value


def safe_nighty(pkg, safe_submodules):
    return _SafeNighty(pkg, safe_submodules)


# ---------- the AST escape attribute names ----------

# Attribute names a safe script may not use at all, because each is a known way out of this gate even though it uses
# no dunder and no blocked bare name:
#   format / format_map  - "{0.__class__.__mro__...}".format(x) hides dunders inside the string from the AST check
#   as_module            - bpy.data.texts[...].as_module() runs the text as code
#   driver_add / driver_remove / expression - a scripted driver runs an arbitrary expression later, outside the gate
#   save / save_render   - writing an image or a render to a file
#   register_class / unregister_class / register_module / load_scripts / execfile - run code outside the gate
BLOCKED_ATTRS = frozenset((
    "format", "format_map",
    "as_module",
    "driver_add", "driver_remove", "expression",
    "save", "save_render",
    "register_class", "unregister_class", "register_module", "load_scripts", "execfile",
))
