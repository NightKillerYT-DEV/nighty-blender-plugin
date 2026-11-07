# SPDX-License-Identifier: GPL-3.0-or-later
# The panel: text wraps to a width, the colored state icons exist on this Blender, each state has its own button text
# and line, the sub-panels and the NC logo register, and the AI's code can never change the safety level.

import bpy

import nighty_blender
from nighty_blender import panel, runtime
from nighty_blender.session import Session


def _measure(text):
    return len(text) * 7  # 7 px per letter, for the pure wrap test


def test_wrap_lines_fits_the_width():
    text = "Local only: your AI reaches this Blender through Nighty Blender MCP on this computer."
    lines = panel.wrap_lines(text, 140, _measure)
    assert len(lines) > 1
    assert all(_measure(line) <= 140 for line in lines), lines
    assert " ".join(lines) == text  # nothing lost, nothing cut to "..."


def test_wrap_lines_breaks_a_very_long_word():
    lines = panel.wrap_lines("a" * 50, 70, _measure)
    assert all(_measure(line) <= 70 for line in lines)
    assert "".join(lines) == "a" * 50


def test_state_icons_exist_here():
    for color in ("green", "yellow", "orange", "red", "blue"):
        assert panel.dot(color) != "NONE", color
    for name in ("LINKED", "KEYINGSET", "PREFERENCES", "LOCKED", "UNLOCKED"):
        assert panel.icon(name) == name, name


def test_each_state_has_its_own_view():
    session = Session(ports=[0])
    session.forget()
    seen = {"off": panel._state_view(session)}
    session.server.error = "ports taken"
    seen["error"] = panel._state_view(session)
    session.server.error = None
    assert session.start()
    try:
        seen["waiting"] = panel._state_view(session)
        session.conns["c1"] = {"authed": False, "client": "Nighty Vault"}
        session.pending = "c1"
        seen["code"] = panel._state_view(session)
        session.pending = None
        session.locked = True
        seen["locked"] = panel._state_view(session)
        session.locked = False
        session.record = {"token": "0" * 32, "client": "Nighty Vault"}
        seen["paired"] = panel._state_view(session)
        session.conns["c1"]["authed"] = True
        seen["connected"] = panel._state_view(session)
    finally:
        session.conns.clear()
        session.record = None
        session.stop()
    texts = {state: view[0] for state, view in seen.items()}
    assert len(set(texts.values())) == len(texts), texts
    assert seen["locked"][2] is True and seen["error"][2] is True        # red (alert)
    assert seen["connected"][1] == panel.dot("green")
    assert "Nighty Vault" in seen["connected"][3]


def test_subpanels_and_logo_register():
    nighty_blender.register()
    try:
        for name in ("NIGHTY_PT_panel", "NIGHTY_PT_pairing", "NIGHTY_PT_settings"):
            assert hasattr(bpy.types, name), name
        assert panel._previews is not None and "nc" in panel._previews
    finally:
        nighty_blender.unregister()
    assert panel._previews is None


def test_ai_code_cannot_change_the_level():
    nighty_blender.register()
    try:
        session = runtime.get_session()
        props = bpy.context.window_manager.nighty_blender
        assert session.level == "safe"
        # a safe-level script tries to raise its own level: refused (reverted), the person's choice stays
        session.dispatcher._run_call("x1", "run_python",
                                     {"code": "bpy.context.window_manager.nighty_blender.level = 'full'"},
                                     "AI", None)
        assert session.level == "safe"
        assert props.level == "safe"
        # the person can change it (no AI code running)
        props.level = "tools"
        assert session.level == "tools"
    finally:
        nighty_blender.unregister()
    # a reload keeps the person's choice (it must never quietly go up)
    nighty_blender.register()
    try:
        assert runtime.get_session().level == "tools"
        bpy.context.window_manager.nighty_blender.level = "safe"
    finally:
        nighty_blender.unregister()
