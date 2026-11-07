# SPDX-License-Identifier: GPL-3.0-or-later
# The "Nighty" tab in the 3D View sidebar (press N). Native Blender widgets only, laid out calmly:
#   Nighty Blender (NC logo in the header, version on the right)
#     a big button that shows the state (a colored dot: off / waiting for Nighty Vault / type the code / connected /
#     locked) and one short line under it saying what happens next
#   Pairing   the 6-digit code box + Pair (only while Nighty Vault asks to pair), Unlock after 5 wrong codes
#   Settings  the safety level (only the person sets it, here), Forget pairing, the local-only line
# Every text wraps to the sidebar's width (wrap()), so nothing ends in "...".

import os

import bpy

from . import runtime

_syncing = False  # guards the propertygroup <-> session sync so an update callback can't loop
_previews = None  # the preview collection holding the NC logo


# ---------- icons ----------

_ICON_NAMES = None


def icon(*names):
    """The first of these built-in icon names this Blender has (names changed between 4.2 and 5.x)."""
    global _ICON_NAMES
    if _ICON_NAMES is None:
        try:
            _ICON_NAMES = set(bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items.keys())
        except Exception:  # noqa: BLE001
            _ICON_NAMES = set()
    for name in names:
        if name in _ICON_NAMES:
            return name
    return "NONE"


def dot(color):
    """A colored dot icon: green / yellow / orange / red / blue (strip colors: SEQUENCE_ in 4.2, STRIP_ in 5.x)."""
    number = {"red": "01", "orange": "02", "yellow": "03", "green": "04", "blue": "05"}[color]
    return icon("STRIP_COLOR_" + number, "SEQUENCE_COLOR_" + number)


def logo_id():
    try:
        return _previews["nc"].icon_id if _previews is not None else 0
    except Exception:  # noqa: BLE001
        return 0


def _load_previews():
    global _previews
    import bpy.utils.previews
    _previews = bpy.utils.previews.new()
    path = os.path.join(os.path.dirname(__file__), "icons", "nc-128.png")
    if os.path.exists(path):
        _previews.load("nc", path, "IMAGE")


def _free_previews():
    global _previews
    if _previews is not None:
        import bpy.utils.previews
        bpy.utils.previews.remove(_previews)
        _previews = None


# ---------- text that wraps to the panel width ----------

def wrap_lines(text, width, measure):
    """Split text into lines no wider than `width` (measured by measure(str) -> px). Long words break by letters."""
    lines = []
    for paragraph in str(text).split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = word if not line else line + " " + word
            if measure(candidate) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            while measure(word) > width and len(word) > 1:  # one word wider than the line
                cut = len(word)
                while cut > 1 and measure(word[:cut]) > width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        lines.append(line)
    return lines


def _measure(context):
    prefs = context.preferences
    scale = prefs.system.ui_scale or prefs.view.ui_scale or 1.0
    try:
        import blf
        style = prefs.ui_styles[0]
        points = getattr(getattr(style, "widget_label", None) or style.widget, "points", 11)
        blf.size(0, points * scale)
        return scale, (lambda t: blf.dimensions(0, t)[0])
    except Exception:  # noqa: BLE001
        return scale, (lambda t: len(t) * 6.5 * scale)


def wrap(layout, context, text, *, icon_name="NONE", inset=0, dim=False, alert=False):
    """Draw text as labels that wrap to the sidebar's width. inset: extra px taken by boxes around it."""
    scale, measure = _measure(context)
    region = context.region
    region_width = region.width if region is not None else 300
    # the tab strip, the panel's margins, the icon, plus any boxes around the text
    width = (region_width - (52 + inset + (34 if icon_name != "NONE" else 0)) * scale) * 0.97
    col = layout.column(align=True)
    col.scale_y = 0.85
    col.active = not dim
    col.alert = alert
    for index, line in enumerate(wrap_lines(text, max(60 * scale, width), measure)):
        if icon_name != "NONE":
            col.label(text=line, icon=icon_name if index == 0 else "BLANK1")
        else:
            col.label(text=line)
    return col


# ---------- the settings the panel binds to ----------

def _on_level(self, context):
    if _syncing:
        return
    session = runtime.get_session()
    if session is None:
        return
    if session.ai_running:          # only the person sets the level, never the AI's code
        _sync_props(self, session)
        return
    session.set_level(self.level)


def _on_code(self, context):
    # Enter in the code box sends it at once (a StringProperty updates when the edit is confirmed)
    global _syncing
    if _syncing:
        return
    session = runtime.get_session()
    code = (self.code or "").strip()
    if session and session.status == "code" and len("".join(ch for ch in code if ch.isdigit())) == 6:
        session.enter_code(code)
        _syncing = True
        try:
            self.code = ""
        finally:
            _syncing = False


LEVEL_TEXT = {
    "tools": "The AI uses the built-in tools only. No Python.",
    "safe": "The AI may also run Python that can't touch your files, other programs or the internet.",
    "full": "The AI may run any Python.",
}


class NightyBlenderProps(bpy.types.PropertyGroup):
    level: bpy.props.EnumProperty(
        name="Safety level",
        description="How much the AI may do. Only you can change this, here",
        items=[
            ("tools", "Tools only", "The AI uses the built-in tools only; no Python", "LOCKED", 0),
            ("safe", "Safe Python", "The AI may also run sandboxed Python (no files, programs or internet)",
             "CHECKMARK", 1),
            ("full", "Full Python", "The AI may run any Python. Only for a chat you trust; save your work first",
             "ERROR", 2),
        ],
        default="safe",
        update=_on_level,
    )
    code: bpy.props.StringProperty(
        name="Pairing code",
        description="The 6-digit code Nighty Vault shows in its Blender card (press Enter or Pair)",
        default="",
        maxlen=12,
        update=_on_code,
    )


# ---------- operators ----------

class NIGHTY_OT_listen(bpy.types.Operator):
    bl_idname = "nighty_blender.listen"
    bl_label = "Connect to Nighty Vault"
    bl_description = "Listen for the Nighty Blender plugin in Nighty Vault, on this computer only (127.0.0.1)"
    bl_options = {"INTERNAL"}

    @classmethod
    def description(cls, context, properties):
        session = runtime.get_session()
        if session and session.listening:
            return "Stop listening. Nighty Vault can't reach this Blender until you turn it on again"
        return "Listen for Nighty Vault on this computer only. Nothing works before you pair with a code"

    def execute(self, context):
        session = runtime.get_session()
        if session:
            if session.listening:
                session.stop()
            elif not session.start():
                self.report({"WARNING"}, session.message or "Could not listen.")
                return {"CANCELLED"}
        return {"FINISHED"}


class NIGHTY_OT_pair(bpy.types.Operator):
    bl_idname = "nighty_blender.pair"
    bl_label = "Pair"
    bl_description = "Pair with the 6-digit code Nighty Vault shows"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        global _syncing
        session = runtime.get_session()
        props = context.window_manager.nighty_blender
        code = (props.code or "").strip()
        if not code:
            self.report({"WARNING"}, "Type the code Nighty Vault shows first.")
            return {"CANCELLED"}
        ok = bool(session and session.enter_code(code))
        _syncing = True
        try:
            props.code = ""
        finally:
            _syncing = False
        if not ok:
            self.report({"WARNING"}, (session.message if session else None) or "Not sent.")
            return {"CANCELLED"}
        return {"FINISHED"}


class NIGHTY_OT_unlock(bpy.types.Operator):
    bl_idname = "nighty_blender.unlock"
    bl_label = "Unlock pairing"
    bl_description = "Pairing locked itself after 5 wrong codes. Unlock it to try again"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        session = runtime.get_session()
        if session:
            session.unlock()
        return {"FINISHED"}


class NIGHTY_OT_forget(bpy.types.Operator):
    bl_idname = "nighty_blender.forget"
    bl_label = "Forget pairing"
    bl_description = "End the pairing with Nighty Vault. Pairing again needs a new code"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        session = runtime.get_session()
        if session:
            session.forget()
        return {"FINISHED"}


# ---------- what each state looks like ----------

def _state_view(session):
    """(button text, icon, alert, the line under it) for the session's state."""
    status = session.status
    if status == "off":
        return ("Connect to Nighty Vault", icon("LINKED"), False,
                "Lets the AI in Nighty Vault work in this Blender, after you pair once with a code.")
    if status == "error":
        return ("Can't listen", dot("red"), True,
                (session.message or "The Nighty ports are taken.") + " Close the other Blender, then try again.")
    if status == "waiting":
        return ("Waiting for Nighty Vault", dot("yellow"), False,
                "In Nighty Vault, open the Blender card in the Night Panel and press Pair. Then type its code here.")
    if status == "code":
        return ("Type the code", dot("yellow"), False, "Nighty Vault asks to pair. Type the 6 digits it shows.")
    if status == "locked":
        return ("Pairing locked", dot("red"), True, "5 wrong codes. Press Unlock when you are ready to try again.")
    if status == "paired":
        who = session.client_name or "Nighty Vault"
        return ("Paired, waiting", dot("blue"), False,
                "Paired with %s. It connects by itself while Nighty Vault is open." % who)
    if status == "connected":
        return ("Connected", dot("green"), False,
                "%s can work in this Blender now." % (session.client_name or "Nighty Vault"))
    return status, "NONE", False, ""


# ---------- the panels ----------

class _NightyBase:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Nighty"


class NIGHTY_PT_panel(_NightyBase, bpy.types.Panel):
    bl_label = "Nighty Blender"
    bl_idname = "NIGHTY_PT_panel"

    def draw_header(self, context):
        logo = logo_id()
        if logo:
            self.layout.label(text="", icon_value=logo)
        else:
            self.layout.label(text="", icon="LINKED")

    def draw_header_preset(self, context):
        session = runtime.get_session()
        if session is not None:
            row = self.layout.row()
            row.active = False
            row.label(text=session.addon_version)

    def draw(self, context):
        layout = self.layout
        session = runtime.get_session()
        if session is None:
            layout.label(text="Starting…")
            return
        _sync_props(context.window_manager.nighty_blender, session)
        text, icon_name, alert, line = _state_view(session)
        col = layout.column()
        row = col.row()
        row.scale_y = 1.6
        row.alert = alert
        row.operator("nighty_blender.listen", text=text, icon=icon_name, depress=session.listening)
        col.separator(factor=0.5)
        wrap(col, context, line, dim=True)
        if session.status == "locked":
            col.separator(factor=0.5)
            col.operator("nighty_blender.unlock", icon=icon("UNLOCKED"))


class NIGHTY_PT_pairing(_NightyBase, bpy.types.Panel):
    bl_label = "Pairing"
    bl_idname = "NIGHTY_PT_pairing"
    bl_parent_id = "NIGHTY_PT_panel"
    bl_order = 0

    @classmethod
    def poll(cls, context):
        session = runtime.get_session()
        if session is None:
            return False
        return bool(session.listening and session.status in ("waiting", "code", "locked")) or bool(session.message)

    def draw_header(self, context):
        self.layout.label(text="", icon=icon("KEYINGSET"))

    def draw(self, context):
        layout = self.layout
        session = runtime.get_session()
        props = context.window_manager.nighty_blender
        ready = session.status == "code"
        if session.status in ("waiting", "code"):
            wrap(layout, context, "Type the code Nighty Vault shows." if ready
                 else "The code box works once Nighty Vault asks to pair.", dim=True)
            row = layout.row(align=True)
            row.scale_y = 1.3
            row.enabled = ready
            if _has_placeholder():
                row.prop(props, "code", text="", placeholder="123456")
            else:
                row.prop(props, "code", text="")
            row.operator("nighty_blender.pair", text="Pair")
        if session.message:
            layout.separator(factor=0.5)
            wrap(layout, context, session.message, icon_name="INFO", alert=session.status == "locked")


class NIGHTY_PT_settings(_NightyBase, bpy.types.Panel):
    bl_label = "Settings"
    bl_idname = "NIGHTY_PT_settings"
    bl_parent_id = "NIGHTY_PT_panel"
    bl_order = 2

    def draw_header(self, context):
        self.layout.label(text="", icon=icon("PREFERENCES"))

    def draw(self, context):
        layout = self.layout
        session = runtime.get_session()
        props = context.window_manager.nighty_blender
        layout.label(text="Safety level")
        layout.prop(props, "level", text="")
        wrap(layout, context, LEVEL_TEXT.get(props.level, ""), dim=True)
        if props.level == "full":
            layout.separator(factor=0.5)
            wrap(layout, context, "Full Python can change anything on this computer. Use it only with a chat "
                 "you trust, and save your work first.", icon_name="ERROR", alert=True)
        if session is not None and session.paired:
            layout.separator()
            layout.operator("nighty_blender.forget", icon=icon("UNLINKED", "X"))
        layout.separator()
        wrap(layout, context, "Local only: Nighty Vault reaches this Blender on this computer (127.0.0.1), and only "
             "after you paired with its code. Nighty Blender makes no models itself.", icon_name="LOCKED",
             dim=True)


def _has_placeholder():
    # UILayout.prop(placeholder=...) exists from Blender 4.1
    try:
        return "placeholder" in bpy.types.UILayout.bl_rna.functions["prop"].parameters
    except Exception:  # noqa: BLE001
        return False


def _sync_props(props, session):
    # keep the level widget showing what the session actually uses (after a reload, or a refused change)
    global _syncing
    _syncing = True
    try:
        if props.level != session.level:
            props.level = session.level
    except Exception:  # noqa: BLE001
        pass
    finally:
        _syncing = False


CLASSES = (
    NightyBlenderProps,
    NIGHTY_OT_listen,
    NIGHTY_OT_pair,
    NIGHTY_OT_unlock,
    NIGHTY_OT_forget,
    NIGHTY_PT_panel,
    NIGHTY_PT_pairing,
    NIGHTY_PT_settings,
)


def register():
    _load_previews()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.nighty_blender = bpy.props.PointerProperty(type=NightyBlenderProps)


def unregister():
    if hasattr(bpy.types.WindowManager, "nighty_blender"):
        del bpy.types.WindowManager.nighty_blender
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    _free_previews()
