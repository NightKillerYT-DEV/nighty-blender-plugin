# SPDX-License-Identifier: GPL-3.0-or-later
# The one object that ties the parts together on Blender's main thread: the settings the person picks in the panel
# (the safety level), the listener (server.py), the pairing (pairing.py, docs/PROTOCOL.md section 3), the
# dispatcher (which runs tool calls) and the jobs. The panel, the operators and the timer all talk to this Session.
#
# Nothing works before pairing: until a connection has proved it knows the pairing code (first time) or the token
# (after that), every call is refused. The token lives in the addon's own user folder (nighty/io/settings.py), never
# in a .blend or a vault. Five wrong codes lock pairing until the person unlocks it in the panel.

import time

try:
    import bpy
except Exception:  # noqa: BLE001
    bpy = None

from . import pairing as P
from .dispatch import Dispatcher, _warm_up_soon
from .nighty.io import settings
from .server import Server, ports_from_env
from .tools import TOOLS

LEVELS = ("tools", "safe", "full")
LEVEL_DEFAULT = "safe"
PAIR_SECONDS = 300          # a pairing request waits this long for the person's code
UNAUTH_SECONDS = 600        # an unpaired connection is closed after this long


class Session:
    def __init__(self, *, ports=None, log=None):
        self.log = log or (lambda *_: None)
        self.level = LEVEL_DEFAULT
        self.addon_version = _addon_version()
        self.blender_version = bpy.app.version_string if bpy is not None else "unknown"
        self.python_version = _python_version()
        self.server = Server(ports or ports_from_env(), log=self.log)
        self.dispatcher = Dispatcher(self)
        self.conns = {}               # conn id -> {"nc", "ns", "client", "authed", "key", "since"}
        self.record = settings.load_pairing()
        self.wrong = 0
        self.locked = False
        self.pending = None           # conn id waiting for the person's code
        self.message = None           # the last thing to tell the person (wrong code, two programs...)
        self.ai_running = False       # True while the AI's code runs (a call or a job step): settings are locked
        self.last_used = 0.0
        self._dirty = False
        self._timer_fn = None

    # ---------- what the panel shows ----------

    @property
    def listening(self):
        return self.server.running

    @property
    def paired(self):
        return self.record is not None

    @property
    def client_conn(self):
        """The connection that proved itself (only one at a time), or None."""
        for cid, c in self.conns.items():
            if c.get("authed"):
                return cid
        return None

    @property
    def client_name(self):
        cid = self.client_conn
        if cid:
            return self.conns[cid].get("client")
        return (self.record or {}).get("client")

    @property
    def status(self):
        """off | error | locked | code (type the code) | connected | paired (waiting for Nighty Vault) | waiting
        (not paired yet)."""
        if not self.listening:
            return "error" if self.server.error else "off"
        if self.locked:
            return "locked"
        if self.pending and self.pending in self.conns:
            return "code"
        if self.client_conn:
            return "connected"
        return "paired" if self.paired else "waiting"

    # ---------- on / off ----------

    def start(self):
        port = self.server.start()
        self.message = None if port else "Can't listen: %s." % self.server.error
        self._mark_dirty()
        return port

    def stop(self):
        for cid in list(self.conns):
            self.server.send(cid, {"type": "bye", "reason": "stopped"})
        self.server.stop()
        self.conns.clear()
        self.pending = None
        self._mark_dirty()

    def set_level(self, level):
        """The person picked a safety level in the panel (never the AI: the panel refuses while its code runs)."""
        if level not in LEVELS or level == self.level:
            return
        self.level = level
        cid = self.client_conn
        if cid:
            self.server.send(cid, {"type": "info", "level": level, "file": _file_name()})
        self._mark_dirty()

    def unlock(self):
        """The person's Unlock: five wrong codes locked pairing; this lets them try again."""
        self.locked = False
        self.wrong = 0
        self.message = None
        self._mark_dirty()

    def forget(self):
        """End the pairing here (the plugin needs a new code next time)."""
        settings.forget_pairing()
        self.record = None
        for cid in list(self.conns):
            if self.conns[cid].get("authed"):
                self.server.send(cid, {"type": "bye", "reason": "unpaired"})
                self.server.close(cid)
                self.conns.pop(cid, None)
        self._mark_dirty()

    # ---------- the person types the code ----------

    def enter_code(self, typed):
        """The code the person typed in the panel. Returns True when it went to Nighty Vault to compare."""
        if self.locked:
            self.message = "Pairing is locked after 5 wrong codes. Press Unlock to try again."
            self._mark_dirty()
            return False
        code = P.normalize_code(typed)
        if code is None:
            self.message = "The code is 6 digits, as Nighty Vault shows it."
            self._mark_dirty()
            return False
        cid = self.pending
        c = self.conns.get(cid) if cid else None
        if c is None:
            self.message = "Nighty Vault isn't asking to pair right now. Open its Blender card and press Pair."
            self._mark_dirty()
            return False
        c["key"] = P.derive_key(code, c["nc"], c["ns"])
        self.server.send(cid, {"type": "pair_proof", "proof": P.server_pair_proof(c["key"], c["nc"], c["ns"])})
        self.message = "Checking the code with Nighty Vault…"
        self._mark_dirty()
        return True

    def _wrong_code(self, cid, why):
        self.wrong += 1
        left = max(0, P.MAX_WRONG - self.wrong)
        c = self.conns.get(cid)
        if c is not None:
            c["key"] = None
        if left == 0:
            self.locked = True
            self.pending = None
            self.message = "5 wrong codes: pairing is locked. Press Unlock when you are ready to try again."
            self.server.send(cid, {"type": "error", "code": "locked", "message": "Pairing is locked in Blender "
                                   "after 5 wrong codes. The person unlocks it in Blender's Nighty panel."})
        else:
            self.message = "%s %d tries left." % (why, left)
            self.server.send(cid, {"type": "error", "code": "wrong_code", "left": left,
                                   "message": "The code typed in Blender doesn't match."})
        self._mark_dirty()

    # ---------- the main-thread tick ----------

    def tick(self):
        handled = 0
        while handled < 50:
            try:
                kind, cid, data = self.server.inbox.get_nowait()
            except Exception:  # noqa: BLE001 - queue.Empty
                break
            handled += 1
            try:
                if kind == "open":
                    self.conns[cid] = {"since": time.monotonic(), "authed": False, "nc": None,
                                       "ns": P.new_nonce(), "client": None, "key": None}
                elif kind == "close":
                    self._closed(cid)
                elif kind == "message" and cid in self.conns:
                    self._message(cid, data)
            except Exception as exc:  # noqa: BLE001 - never let one bad message stop the timer
                self.log("session:", exc)
        now = time.monotonic()
        for cid, c in list(self.conns.items()):
            if not c["authed"] and now - c["since"] > UNAUTH_SECONDS:
                self.server.close(cid, 1008, "not paired")
                self._closed(cid)
            elif cid == self.pending and now - c.get("pair_since", now) > PAIR_SECONDS:
                self.pending = None
                self.server.send(cid, {"type": "error", "code": "pair_timeout",
                                       "message": "No code was typed in Blender in time. Press Pair again."})
                self._mark_dirty()
        self.dispatcher.tick()

    def _closed(self, cid):
        was = self.conns.pop(cid, None)
        if cid == self.pending:
            self.pending = None
        if was is not None:
            self._mark_dirty()

    def _message(self, cid, m):
        c = self.conns[cid]
        t = m.get("type")
        if t == "hello":
            return self._hello(cid, c, m)
        if t == "ping":
            return self.server.send(cid, {"type": "pong"})
        if c["nc"] is None:
            return self._refuse(cid, m, "hello", "Say hello first.")
        if t == "auth":
            return self._auth(cid, c, m)
        if t == "pair_request":
            return self._pair_request(cid, c)
        if t == "pair_fail":                     # the plugin found Blender's proof wrong: the code doesn't match
            if cid == self.pending and c.get("key"):
                self._wrong_code(cid, "That code doesn't match the one Nighty Vault shows.")
            return None
        if t == "pair_confirm":
            return self._pair_confirm(cid, c, m)
        if not c["authed"]:
            return self._refuse(cid, m, "unpaired", "Not paired: pair Nighty Vault with Blender first (the code "
                                                    "in Nighty Vault's Blender card, typed in Blender's N panel).")
        if t == "call":
            self.last_used = time.monotonic()
            return self.dispatcher.on_call(m)
        if t == "config":
            path = m.get("instantMeshes")
            if isinstance(path, str) and path:
                settings.set_tool_path("instant_meshes", path)
            elif path is None and "instantMeshes" in m:
                settings.set_tool_path("instant_meshes", None)
            return self.server.send(cid, {"type": "config_ok"})
        if t == "forget":
            return self.forget()
        if t == "bye":
            self.server.close(cid)
            return self._closed(cid)
        return None

    def _refuse(self, cid, m, code, text):
        if m.get("type") == "call" and m.get("id") is not None:
            self.server.send(cid, {"type": "result", "id": m["id"], "isError": True,
                                   "content": [{"type": "text", "text": text}]})
            return None
        out = {"type": "error", "code": code, "message": text}
        if m.get("id") is not None:
            out["id"] = m["id"]
        self.server.send(cid, out)
        return None

    def _hello(self, cid, c, m):
        nc = m.get("nonce")
        if m.get("v") != 2 or not P.is_hex(nc, 32):
            self.server.send(cid, {"type": "error", "code": "version", "message": "This Blender add-on speaks "
                                   "protocol v2 (Nighty Blender 2.x)."})
            self.server.close(cid, 1002, "version")
            return self._closed(cid)
        client = m.get("client") if isinstance(m.get("client"), dict) else {}
        c["nc"] = nc
        c["client"] = str(client.get("name") or "Nighty Vault")[:60]
        c["client_version"] = str(client.get("version") or "")[:20]
        out = {"type": "hello", "v": 2, "addon": self.addon_version, "blender": self.blender_version,
               "python": self.python_version, "nonce": c["ns"], "paired": self.paired, "locked": self.locked,
               "level": self.level, "kdf": {"name": "pbkdf2-sha256", "iterations": P.ITERATIONS}}
        if self.record:
            out["proof"] = P.server_auth_proof(self.record["token"], nc, c["ns"])
        self.server.send(cid, out)
        self._mark_dirty()
        return None

    def _auth(self, cid, c, m):
        if not self.record or not P.same(m.get("proof"), P.client_auth_proof(self.record["token"], c["nc"],
                                                                             c["ns"])):
            self.server.send(cid, {"type": "error", "code": "auth_failed", "message": "That pairing is not known "
                                   "here (Blender forgot it, or it was another Blender). Pair again."})
            self.server.close(cid, 1008, "auth")
            return self._closed(cid)
        return self._ready(cid, c)

    def _ready(self, cid, c):
        # one AI link at a time: a newer proven connection replaces an older one
        for other, oc in list(self.conns.items()):
            if other != cid and oc.get("authed"):
                self.server.send(other, {"type": "bye", "reason": "replaced"})
                self.server.close(other)
                self.conns.pop(other, None)
        c["authed"] = True
        self.message = None
        self.last_used = time.monotonic()
        self.server.send(cid, {"type": "ready", "addon": self.addon_version, "blender": self.blender_version,
                               "level": self.level, "file": _file_name(), "tools": sorted(TOOLS)})
        _warm_up_soon()
        self._mark_dirty()
        return None

    def _pair_request(self, cid, c):
        if self.locked:
            self.server.send(cid, {"type": "error", "code": "locked", "message": "Pairing is locked in Blender "
                                   "after 5 wrong codes. The person unlocks it in Blender's Nighty panel."})
            return None
        if self.pending and self.pending != cid and self.pending in self.conns:
            # two programs asking at once: neither gets it (the person sees why)
            self.server.send(cid, {"type": "error", "code": "busy", "message": "Another program is pairing with "
                                   "this Blender right now."})
            self.server.send(self.pending, {"type": "error", "code": "busy", "message": "Another program asked to "
                                            "pair at the same time; try again."})
            self.message = "Two programs asked to pair at once, so neither was paired. Try again from Nighty Vault."
            self.pending = None
            self._mark_dirty()
            return None
        self.pending = cid
        c["pair_since"] = time.monotonic()
        c["key"] = None
        self.message = None
        self.server.send(cid, {"type": "pair_wait", "message": "Type the code in Blender's N panel (Nighty tab)."})
        self._mark_dirty()
        return None

    def _pair_confirm(self, cid, c, m):
        key = c.get("key")
        if cid != self.pending or key is None:
            return self._refuse(cid, m, "no_code", "No code was typed in Blender for this connection.")
        if not P.same(m.get("proof"), P.client_pair_proof(key, c["nc"], c["ns"])):
            return self._wrong_code(cid, "That code doesn't match.")
        token = P.new_token()
        self.record = {"token": token, "client": c["client"], "since": time.strftime("%Y-%m-%d %H:%M")}
        settings.save_pairing(self.record)
        self.pending = None
        self.wrong = 0
        self.server.send(cid, {"type": "paired", "box": P.seal_token(key, token, c["nc"], c["ns"])})
        c["key"] = None
        return self._ready(cid, c)

    # ---------- sending (the dispatcher and jobs) ----------

    def send(self, obj):
        cid = self.client_conn
        return self.server.send(cid, obj) if cid else False

    # ---------- the main-thread timer ----------

    def start_timer(self):
        if bpy is None:
            return
        if self._timer_fn is None:
            self._timer_fn = self._on_timer
            bpy.app.timers.register(self._timer_fn, persistent=True)

    def stop_timer(self):
        if bpy is None:
            return
        fn = self._timer_fn
        self._timer_fn = None
        if fn is not None and bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)

    def _on_timer(self):
        try:
            self.tick()
            if self._dirty:
                self._dirty = False
                _tag_redraw()
        except Exception as exc:  # noqa: BLE001 - never let the timer die
            self.log("timer:", exc)
        return 0.02

    def _mark_dirty(self):
        self._dirty = True


# ---------- small helpers ----------

def _addon_version():
    try:
        import os
        import tomllib  # Python 3.11+ (Blender 4.2 and up)
        path = os.path.join(os.path.dirname(__file__), "blender_manifest.toml")
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
        return str(data.get("version") or "2.0.0")
    except Exception:  # noqa: BLE001
        return "2.0.0"


def _file_name():
    if bpy is None or not bpy.data.filepath:
        return ""
    return bpy.data.filepath.replace("\\", "/").rsplit("/", 1)[-1]


def _python_version():
    import platform
    return platform.python_version()


def _tag_redraw():
    if bpy is None:
        return
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    for region in area.regions:
                        if region.type == "UI":
                            region.tag_redraw()
    except Exception:  # noqa: BLE001
        pass
