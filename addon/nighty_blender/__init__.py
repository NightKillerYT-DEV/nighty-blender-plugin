# SPDX-License-Identifier: GPL-3.0-or-later
# Nighty Blender 2: the Blender add-on that lets the AI in Nighty Vault (through the Nighty Blender plugin you paired
# with) make your models game-ready in your Blender. Everything runs on this computer: the add-on listens on
# 127.0.0.1 only and does nothing before pairing. See docs/PROTOCOL.md.
#
# This file is only the wiring: load the tool modules so they register themselves, build the one Session, start the
# main-thread timer and the panel, and listen again by itself when a pairing is kept. Reload-safe.

import importlib
import pkgutil
import sys

from . import panel, runtime, tools
from .session import Session


def load_tools():
    """Import every module in the tools package so each @tool registers itself. Missing optional modules (a helper
    library not installed yet) are skipped, never fatal. Returns the names that loaded."""
    loaded = []
    package = tools
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_"):
            continue
        try:
            importlib.import_module("%s.%s" % (package.__name__, info.name))
            loaded.append(info.name)
        except Exception as exc:  # noqa: BLE001 - one bad tool module must not stop the rest
            print("Nighty Blender: could not load tools.%s: %s" % (info.name, exc))
    return loaded


def nighty_alias():
    """For development scripts and tests outside run_python: make `import nighty` give this helper library. The
    installed extension never calls it (Blender's extension policy forbids adding top-level modules); run_python
    resolves `import nighty` itself."""
    from . import nighty as library
    sys.modules["nighty"] = library
    return library


def _log(*parts):
    print("Nighty Blender:", *(str(p) for p in parts))


def register():
    load_tools()
    panel.register()
    session = Session(log=_log)
    _keep_choices(session)
    runtime.set_session(session)
    session.start_timer()
    if session.paired and not _background():
        session.start()          # paired before: listen again, so Nighty Vault reconnects by itself
    _log("ready (addon %s, Blender %s)." % (session.addon_version, session.blender_version))


def _background():
    try:
        import bpy
        return bool(bpy.app.background)
    except Exception:  # noqa: BLE001
        return True


def _keep_choices(session):
    # After a reload the panel's properties still hold the person's choices for this Blender run: keep them (never
    # let a reload quietly change the safety level).
    try:
        import bpy
        props = bpy.context.window_manager.nighty_blender
        session.level = props.level
    except Exception:  # noqa: BLE001 - no window manager yet (factory startup): the defaults stand
        pass


def unregister():
    session = runtime.get_session()
    if session is not None:
        try:
            session.dispatcher.jobs.cancel_all()
        except Exception:  # noqa: BLE001
            pass
        session.stop_timer()
        session.stop()
        runtime.set_session(None)
    panel.unregister()
