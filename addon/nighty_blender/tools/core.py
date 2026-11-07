# SPDX-License-Identifier: GPL-3.0-or-later
# The core steps every Nighty Blender session has: status, run_python (with the level gate), undo (the AI's own steps
# only), and wait_job / cancel_job (the addon side of the jobs framework). The public tools (tools/public.py) route
# to them; look, measure, checks, import, topology and texturing live in their own modules.

import ast
import contextlib
import io

from . import ToolError, text, action
from . import _sandbox

try:
    import bpy
except Exception:  # noqa: BLE001 - importable outside Blender (for gen_tools_json and plain unit tests)
    bpy = None


# ---------- status ----------

@action(
    "status",
    "Blender and addon versions, the safety level the person set and the open .blend file.",
    level="tools",
    changes=False,
)
def status(ctx, args):
    file_name = ""
    if bpy is not None:
        path = bpy.data.filepath
        file_name = path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] if path else ""
    import platform
    out = {
        "blender": getattr(ctx, "blender_version", None) or (bpy.app.version_string if bpy else "?"),
        "addon": getattr(ctx, "addon_version", None) or _manifest_version(),
        "python": getattr(ctx, "python_version", None) or platform.python_version(),
        "level": getattr(ctx, "level", "?"),
        "file": file_name,
    }
    jobs = getattr(ctx, "jobs", None)
    if jobs is not None and hasattr(jobs, "jobs"):
        out["jobs"] = [j.snapshot() for j in jobs.jobs.values() if j.state == "running"]
    return out


def _manifest_version():
    import os
    import re
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "blender_manifest.toml")
    try:
        with open(path, encoding="utf-8") as f:
            return re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M).group(1)
    except (OSError, AttributeError):
        return "?"


# ---------- run_python ----------

# The modules a safe script may use (already in the namespace, and `import` works for exactly these, e.g.
# `import nighty as n`, `from mathutils import Vector`). `nighty` is the helper library.
SAFE_MODULES = ("bpy", "bmesh", "mathutils", "math", "random", "nighty")
# nighty's own modules a safe script may import by name (not mesh / bake / export / materials / presets / io:
# they write files, start programs or download).
SAFE_NIGHTY = ("compat", "core", "shapes", "modify", "place", "assemble", "details", "kit", "surface", "paint",
               "check", "view")


def _import_ok(name, fromlist=()):
    top, _, rest = name.partition(".")
    if top not in SAFE_MODULES:
        return False
    if top == "nighty":
        if rest and rest.split(".")[0] not in SAFE_NIGHTY:
            return False
        # `from nighty import X`: X may be a safe submodule or a top-level function, but never an unsafe submodule.
        for f in (fromlist or ()):
            f = str(f)
            if f.startswith("_") or f in _sandbox._UNSAFE_NIGHTY:
                return False
    return True


def _nighty(rest=""):
    """The helper library (or one of its modules). Scripts say `import nighty`; the extension's real module is
    <package>.nighty, and no top-level `nighty` module is added (Blender's extension policy forbids that)."""
    import importlib
    base = __name__.rsplit(".tools.", 1)[0] + ".nighty"
    return importlib.import_module(base + ("." + rest if rest else ""))


def _lib_import(name, fromlist):
    top, _, rest = name.partition(".")
    module = _nighty(rest)
    return module if fromlist else _nighty()


def _full_import(name, globals=None, locals=None, fromlist=(), level=0):
    """Any import, with `nighty` meaning the helper library (the 'full' level)."""
    if level == 0 and (name == "nighty" or name.startswith("nighty.")):
        return _lib_import(name, fromlist)
    import builtins
    return builtins.__import__(name, globals, locals, fromlist, level)


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    """The only import a safe script gets: the provided modules, and as the SAME restricted views that are already
    in the namespace (so `import bpy` gives the safe bpy, not the real one), nothing else."""
    if level != 0 or not _import_ok(name, fromlist):
        raise ImportError("Safe scripts can import only %s. (The person can switch to the 'full' level in the "
                          "Nighty panel.)" % ", ".join(SAFE_MODULES))
    top = name.partition(".")[0]
    ns = globals or {}
    if top in ns:
        return ns[top]   # the restricted view already prepared for this run (bpy / nighty proxy, or a real module)
    return _full_import(name, globals, locals, fromlist, level)


# Builtins a safe script may call. Anything that can open files, run more code or reach around the sandbox is left
# out on purpose (open, exec, eval, compile, __import__, globals, locals, vars, getattr, setattr, delattr, input...).
def _build_safe_builtins():
    bset = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
    allow = (
        "abs", "all", "any", "bool", "bytearray", "bytes", "callable", "chr", "complex", "dict", "divmod",
        "enumerate", "filter", "float", "format", "frozenset", "hash", "hex", "int", "isinstance", "issubclass",
        "iter", "len", "list", "map", "max", "min", "next", "oct", "ord", "pow", "print", "range", "repr",
        "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple", "type", "zip",
        "True", "False", "None",
        "Exception", "ValueError", "TypeError", "KeyError", "IndexError", "RuntimeError", "AttributeError",
        "ZeroDivisionError", "StopIteration", "FloatingPointError", "OverflowError", "NotImplementedError",
    )
    return {name: bset[name] for name in allow if name in bset}


SAFE_BUILTINS = _build_safe_builtins()

# Names a safe script may not use at all (even as a bare reference), because they open the door to files, processes,
# the network or the sandbox walls. The pre-bound safe modules and builtins cover everything a modelling script needs.
_BLOCKED_NAMES = frozenset((
    "open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "input", "breakpoint", "help", "memoryview", "classmethod", "staticmethod", "super", "object", "property",
    "os", "sys", "subprocess", "socket", "shutil", "importlib", "ctypes", "builtins", "__builtins__",
))


def _check_safe(tree):
    """Raise ToolError if the parsed script uses something a safe script may not. Plain and strict: imports are off
    (the modules it needs are already provided), dunder attributes are off, and the blocked names above are off."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and all(_import_ok(a.name) for a in node.names):
            continue
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and \
                _import_ok(node.module, [a.name for a in node.names]) and all(a.name != "*" for a in node.names):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ToolError("Safe scripts can import only bpy, bmesh, mathutils, math, random and nighty (they are "
                            "also ready without importing). (The person can switch to the 'full' level in the Nighty "
                            "panel.)")
        if isinstance(node, ast.Attribute) and isinstance(node.attr, str):
            if node.attr.startswith("__"):
                raise ToolError("Safe scripts can't use %r (dunder attributes are off at this level)."
                                % ("." + node.attr))
            if node.attr in ("format", "format_map"):
                raise ToolError("Safe scripts can't use .%s(); use an f-string instead, e.g. f\"{name}: {size:.2f}\"."
                                % node.attr)
            if node.attr in _sandbox.BLOCKED_ATTRS:
                raise ToolError("Safe scripts can't use the %r attribute (it is a way to run more code or touch "
                                "files).%s" % (node.attr, _sandbox.SWITCH))
        if isinstance(node, ast.Name) and node.id in _BLOCKED_NAMES:
            raise ToolError("Safe scripts can't use %r. (The person can switch to the 'full' level in the Nighty "
                            "panel to run any Python.)" % node.id)
        if isinstance(node, ast.Global) or isinstance(node, ast.Nonlocal):
            # harmless but pointless in a one-shot script; keep the surface small
            raise ToolError("Safe scripts can't use global/nonlocal.")


def _namespace(safe):
    """The names a run_python script starts with. At the safe level bpy and nighty are restricted VIEWS (see
    _sandbox); bmesh, mathutils, math and random are pure-compute, so they are handed over as is."""
    ns = {}
    if bpy is not None:
        import bmesh  # noqa: F401 - part of the provided set
        import math
        import random
        import mathutils
        ns.update(bpy=_sandbox.safe_bpy(bpy) if safe else bpy,
                  bmesh=bmesh, mathutils=mathutils, math=math, random=random)
        try:
            lib = _nighty()
            ns["nighty"] = _sandbox.safe_nighty(lib, SAFE_NIGHTY) if safe else lib
        except Exception:  # noqa: BLE001 - the helper library is optional
            pass
    return ns


# The light guard: models come from the person (their file, an import, a scene mesh); building one in code is only for
# when the person asked for it. A script that fills an empty scene with many new meshes gets a short reminder in its
# answer; nothing is refused (the person may have asked for code-building).
GUARD_NEW_MESHES = 5
GUARD_NOTE = ("Note: models come from the person's file (import, then make_game_ready), not built in code. Build in "
              "code only when the person asked for it in their own words; then go on.")


def _mesh_count():
    try:
        return sum(1 for o in bpy.data.objects if o.type == "MESH")
    except Exception:  # noqa: BLE001 - restricted contexts
        return 0


def _guard_note(ctx, before, after):
    if before > 1 or after - before < GUARD_NEW_MESHES:      # not an empty scene (the startup cube is fine)
        return None
    return GUARD_NOTE


@action(
    "run_python",
    "Run a short Python script in Blender (bpy, bmesh, mathutils, math, random, nighty ready). For small fixes the "
    "person asked for; models come from the person's file (build one in code only when the person asks for that). "
    "`result` is returned; print() is captured. 'safe' level: no imports or risky calls; 'full': any.",
    {
        "type": "object",
        "properties": {"code": {"type": "string", "description": "The Python to run."}},
        "required": ["code"],
    },
    level="safe",
    changes=True,
)
def run_python(ctx, args):
    if bpy is None:
        raise ToolError("Blender is not available.")
    code = args.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ToolError("Give some `code` to run.")
    try:
        tree = ast.parse(code, filename="<nighty-run_python>", mode="exec")
    except SyntaxError as exc:
        raise ToolError("That script has a syntax error: %s (line %s)" % (exc.msg, exc.lineno))

    safe = ctx.level != "full"
    ns = _namespace(safe)
    if not safe:
        # Full Python: no allow-list. The panel shows a warning while this level is on.
        import builtins
        ns["__builtins__"] = dict(vars(builtins), __import__=_full_import)
    else:
        _check_safe(tree)
        ns["__builtins__"] = dict(SAFE_BUILTINS, __import__=_safe_import)

    out = io.StringIO()
    meshes_before = _mesh_count()
    try:
        compiled = compile(tree, filename="<nighty-run_python>", mode="exec")
        with contextlib.redirect_stdout(out):
            exec(compiled, ns)  # noqa: S102 - this is the point of the tool, gated by the person's level
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001 - hand the traceback back so the AI can fix it
        import traceback
        printed = out.getvalue()
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        raise ToolError(("%sTraceback:\n%s" % (("Printed:\n" + printed + "\n") if printed else "", tb)).strip())

    blocks = []
    printed = out.getvalue()
    if printed:
        blocks.append(text(printed.rstrip("\n")))
    if "result" in ns and ns["result"] is not None:
        blocks.append(text(_describe(ns["result"])))
    if not blocks:
        blocks.append(text("Ran. (No print() output and no `result` set.)"))
    note = _guard_note(ctx, meshes_before, _mesh_count())
    if note:
        blocks.append(text(note))
    return blocks


def _describe(value):
    try:
        import json
        return json.dumps(value, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(value)[:4000]


# ---------- undo (the AI's own steps only) ----------

@action(
    "undo",
    "Take back the AI's last change. It only ever undoes a step the AI made (named 'AI: ...'); if the most recent "
    "step is the person's own work, it refuses.",
    level="tools",
    changes=False,   # undo must not itself be wrapped in a new undo step
)
def undo(ctx, args):
    if bpy is None:
        raise ToolError("Blender is not available.")
    from ..dispatch import active_undo_name
    name = active_undo_name()
    if name is None:
        raise ToolError("Could not read the undo history, so nothing was undone (to be safe).")
    if not name.startswith("AI:"):
        raise ToolError("The most recent step is the person's own work (%r), not the AI's, so nothing was undone."
                        % name[:80])
    try:
        bpy.ops.ed.undo()
    except Exception as exc:  # noqa: BLE001
        raise ToolError("Undo failed: %s" % exc)
    return {"undone": name}


# ---------- jobs: wait and cancel ----------

@action(
    "wait_job",
    "Wait for a slow job (an import, bake, render or export) to finish, then return its result. It waits up to a few "
    "tens of seconds; if the job is still going it returns the progress so you can wait again.",
    {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "The job id a slow tool returned."},
            "seconds": {"type": "number", "description": "How long to wait, up to 40. Default 40."},
        },
        "required": ["id"],
    },
    level="tools",
    changes=False,
)
def wait_job(ctx, args):
    job_id = args.get("id")
    if not isinstance(job_id, str):
        raise ToolError("Give the job `id`.")
    seconds = args.get("seconds")
    seconds = 40 if not isinstance(seconds, (int, float)) else max(1, min(40, int(seconds)))
    if ctx.job_snapshot(job_id) is None:
        raise ToolError("There is no job %r." % job_id)
    return ctx.wait_job(job_id, seconds)   # parks the answer in the dispatcher; never blocks Blender


@action(
    "cancel_job",
    "Stop a slow job that is still running.",
    {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "The job id to stop."}},
        "required": ["id"],
    },
    level="tools",
    changes=False,
)
def cancel_job(ctx, args):
    job_id = args.get("id")
    if not isinstance(job_id, str):
        raise ToolError("Give the job `id`.")
    snap = ctx.job_snapshot(job_id)
    if snap is None:
        raise ToolError("There is no job %r." % job_id)
    stopped = ctx.cancel_job(job_id)
    return {"cancelled": bool(stopped), "state": snap.get("state")}
