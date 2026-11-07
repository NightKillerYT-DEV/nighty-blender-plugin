# SPDX-License-Identifier: GPL-3.0-or-later
# run_python's safety gate. At the 'safe' level (the default) a script may only model: imports, dunder attributes and
# a few escape attribute names are refused by the AST check, and bpy / nighty are restricted VIEWS so the ways out
# (running more code, files, settings, network) have nothing to call. At 'full' any Python runs. Normal modelling
# code and the provided modules keep working at safe.
#
# Each refusal is checked at attribute ACCESS (or at the AST check), before anything runs, so these tests never
# save, open, quit, export or download: a refused escape has no side effect.

from nighty_blender.tools import ToolError
from nighty_blender.tools.core import run_python


class _Ctx:
    def __init__(self, level):
        self.level = level


def _run(level, code):
    return run_python(_Ctx(level), {"code": code})


def _refused(level, code):
    try:
        _run(level, code)
    except ToolError:
        return True
    return False


def _ok_text(level, code):
    """Runs and returns the joined text blocks (raises if the gate refused)."""
    blocks = _run(level, code)
    return " ".join(b.get("text", "") for b in blocks)


# ---- the table of escape attempts: each MUST be refused at the safe level ----

ESCAPES = {
    # running other Python
    "import a module": "import os\nresult = 1",
    "import bpy gets the real module": "import bpy as b\nx = b.ops.wm",
    "from-import a module": "from os import system\nresult = 1",
    "run a text block as code": "t = bpy.data.texts.new('x')\nm = t.as_module",
    "text.run_script operator": "x = bpy.ops.text.run_script",
    "script.python_file_run operator": "x = bpy.ops.script.python_file_run",
    "register a class": "x = bpy.utils.register_class",
    "a timer that runs later": "x = bpy.app.timers",
    "a handler that runs later": "x = bpy.app.handlers",
    "driver_namespace": "x = bpy.app.driver_namespace",
    "a scripted driver": "x = bpy.data.objects.driver_add",
    "a driver expression": "d = some.driver\nd.expression = 'x'",
    "msgbus subscribe": "x = bpy.msgbus",
    # files
    "save the .blend": "x = bpy.ops.wm.save_mainfile",
    "open a .blend": "x = bpy.ops.wm.open_mainfile",
    "read the home file": "x = bpy.ops.wm.read_homefile",
    "append from a .blend": "x = bpy.ops.wm.append",
    "link from a .blend": "x = bpy.ops.wm.link",
    "export operator": "x = bpy.ops.export_scene",
    "import operator": "x = bpy.ops.import_scene",
    "a file operator": "x = bpy.ops.file",
    "libraries.write / load": "x = bpy.data.libraries",
    "load an image from a file": "x = bpy.data.images.load",
    "load a font from a file": "x = bpy.data.fonts.load",
    "save an image": "img = bpy.data.images.new('t', 4, 4)\nimg.save",
    "save_render": "img = bpy.data.images.new('t', 4, 4)\nimg.save_render",
    "render to a file": "x = bpy.ops.render.render",
    "save-image operator": "x = bpy.ops.image.save",
    "open a url": "x = bpy.ops.wm.url_open",
    "open a path": "x = bpy.ops.wm.path_open",
    "quit Blender": "x = bpy.ops.wm.quit_blender",
    "blend_data routes back to real data": "x = bpy.context.blend_data.libraries",
    # settings
    "preferences": "x = bpy.context.preferences",
    "preferences operator": "x = bpy.ops.preferences",
    "extensions operator": "x = bpy.ops.extensions",
    # string / type tricks that dodge the dunder check
    "str.format with a dunder inside": "result = '{0.__class__}'.format(1)",
    "format_map with a dunder inside": "result = '{x.__class__}'.format_map({'x': 1})",
    "a dunder attribute": "result = (1).__class__",
    # reaching around through the nighty library
    "nighty.bake": "m = nighty.bake",
    "nighty.export": "m = nighty.export",
    "nighty.mesh": "m = nighty.mesh",
    "nighty.presets": "m = nighty.presets",
    "import nighty.bake": "import nighty.bake",
    "from nighty import bake": "from nighty import bake",
    "a raw module through a nighty submodule": "b = nighty.core.bpy\nx = b.ops.wm",
    "the real bpy through nighty.compat": "b = nighty.compat.bpy\nx = b.utils",
    # blocked bare names
    "open()": "result = open('x')",
    "eval()": "result = eval('1+1')",
    "exec()": "exec('x = 1')",
    "getattr()": "result = getattr(bpy, 'ops')",
    "__import__": "result = __import__('os')",
}


def test_every_escape_is_refused_at_safe():
    leaked = [name for name, code in ESCAPES.items() if not _refused("safe", code)]
    assert not leaked, "these escapes were NOT refused at the safe level: %s" % leaked


# ---- normal modelling code must keep working at the safe level ----

def test_safe_runs_normal_code():
    assert "10" in _ok_text("safe", "result = sum(range(5))")


def test_safe_f_string_with_normal_content():
    assert "2" in _ok_text("safe", "result = f'{1 + 1}'")


def test_safe_format_builtin_still_works():
    # the `format` BUILTIN (not the .format METHOD) stays available
    assert "3.14" in _ok_text("safe", "result = format(3.14159, '.2f')")


def test_safe_can_read_bpy_app():
    assert _ok_text("safe", "result = bpy.app.version_string")


def test_safe_can_use_the_data_api():
    code = ("m = bpy.data.meshes.new('SandboxMesh')\n"
            "o = bpy.data.objects.new('SandboxObj', m)\n"
            "bpy.context.scene.collection.objects.link(o)\n"
            "o.location = (1.0, 2.0, 3.0)\n"
            "result = o.name")
    assert "SandboxObj" in _ok_text("safe", code)


def test_safe_can_create_an_image_in_memory():
    assert _ok_text("safe", "img = bpy.data.images.new('MemImage', 4, 4)\nresult = list(img.size)")


def test_safe_can_run_a_modelling_operator():
    import bpy
    before = len(bpy.data.objects)
    _run("safe", "bpy.ops.mesh.primitive_cube_add(size=1.0)")
    assert len(bpy.data.objects) == before + 1


def test_safe_can_reach_modelling_op_categories():
    for cat in ("object", "mesh", "curve", "transform", "uv", "material", "node"):
        assert _ok_text("safe", "result = str(type(bpy.ops.%s))" % cat)


def test_safe_can_use_mathutils():
    assert "2.0" in _ok_text("safe", "from mathutils import Vector\nv = Vector((2.0, 0.0, 0.0))\nresult = v.x")


def test_safe_can_use_bmesh():
    assert _ok_text("safe", "bm = bmesh.new()\nbm.verts.new((0, 0, 0))\nn = len(bm.verts)\nbm.free()\nresult = n")


def test_safe_can_use_the_nighty_library():
    import bpy
    code = ("import nighty as n\n"
            "n.settings(detail='low', size=1.0)\n"
            "b = n.box((0.4, 0.3, 0.2), name='SafeKitBox')\n"
            "result = b.name")
    assert "SafeKitBox" in _ok_text("safe", code)
    assert "SafeKitBox" in bpy.data.objects


def test_safe_can_reach_a_nighty_submodule_function():
    # n.core.axis_vector is used by some example scripts; the submodule view must hand back its functions
    assert _ok_text("safe", "v = nighty.core.axis_vector('X')\nresult = [round(c, 3) for c in v]")


def test_safe_from_nighty_import_function():
    assert _ok_text("safe", "from nighty import box\nresult = callable(box)")


# ---- the full level lifts the limits (non-destructive probes only) ----

def test_full_allows_import():
    assert _ok_text("full", "import os\nresult = os.name")


def test_full_sees_the_real_bpy():
    # at full, the escape surfaces are reachable (we only check they are THERE, never call a destructive op)
    assert "True" in _ok_text("full", "result = str(callable(bpy.ops.wm.save_mainfile))")
    assert "True" in _ok_text("full", "result = str(callable(bpy.utils.register_class))")


def test_full_format_method_works():
    assert "1" in _ok_text("full", "result = '{0}'.format(1)")


def test_full_nighty_bake_is_reachable():
    assert "True" in _ok_text("full", "import nighty\nresult = str(hasattr(nighty, 'bake'))")


# ---- the error message points the person to the panel ----

def test_refusal_mentions_the_panel():
    try:
        _run("safe", "import os")
    except ToolError as exc:
        assert "panel" in str(exc).lower()
        return
    raise AssertionError("expected a ToolError")


def test_syntax_error_is_a_toolerror():
    try:
        _run("safe", "def (")
    except ToolError as exc:
        assert "syntax" in str(exc).lower()
        return
    raise AssertionError("expected a ToolError for a syntax error")
