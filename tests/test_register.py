# SPDX-License-Identifier: GPL-3.0-or-later
# The extension registers and unregisters cleanly, twice (reload-safe): the panel class and the WindowManager
# property come and go, and the Session is made and torn down without listening (nothing is paired in the sandbox).

import bpy

import nighty_blender
from nighty_blender import runtime


def test_register_unregister_twice():
    for _ in range(2):
        nighty_blender.register()
        try:
            assert hasattr(bpy.types, "NIGHTY_PT_panel")
            assert hasattr(bpy.types.WindowManager, "nighty_blender")
            session = runtime.get_session()
            assert session is not None
            assert session.listening is False          # enabling the addon does not listen before a pairing
            assert session.paired is False
            assert session.addon_version              # read from the manifest
        finally:
            nighty_blender.unregister()
        assert runtime.get_session() is None
        assert not hasattr(bpy.types, "NIGHTY_PT_panel")


def test_properties_default_sensibly():
    nighty_blender.register()
    try:
        props = bpy.context.window_manager.nighty_blender
        assert props.level == "safe"
        assert props.code == ""
    finally:
        nighty_blender.unregister()
