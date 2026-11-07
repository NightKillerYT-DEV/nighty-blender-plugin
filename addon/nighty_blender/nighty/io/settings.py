# SPDX-License-Identifier: GPL-3.0-or-later
# The addon's own small state on this computer, outside any project or vault: the pairing (a 32-hex token shared
# with the Nighty Vault plugin; never written into a .blend, a vault or the AI's context) and the paths of helper
# programs the plugin installed for it (Instant Meshes). Kept in the extension's own user folder, so it survives
# addon updates; NIGHTY_BLENDER_STATE_DIR overrides the folder (tests always use a temp folder).
# Plain Python: no bpy needed at import time.

import json
import os
import sys
import tempfile
import threading

_LOCK = threading.Lock()
PACKAGE = "nighty_blender"


def state_dir():
    """NIGHTY_BLENDER_STATE_DIR, else Blender's user folder for this extension, else a per-user fallback."""
    override = os.environ.get("NIGHTY_BLENDER_STATE_DIR")
    if override:
        return override
    try:
        import bpy
        pkg = __package__.rsplit(".nighty.io", 1)[0] if __package__ else PACKAGE
        return bpy.utils.extension_path_user(pkg, path="", create=True)
    except Exception:  # noqa: BLE001 - not an installed extension (development, plain tests)
        pass
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "NightyBlender2")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/NightyBlender2")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "nighty-blender2")


def _path(name):
    return os.path.join(state_dir(), name)


def _write_json(path, data, private=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        if private and os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# ---------- the pairing ----------

def load_pairing():
    """{"token": 32 hex, "client": name, "since": date} or None."""
    with _LOCK:
        data = _read_json(_path("pairing.json"))
    token = data.get("token")
    if isinstance(token, str) and len(token) == 32 and all(c in "0123456789abcdef" for c in token):
        return data
    return None


def save_pairing(record):
    with _LOCK:
        _write_json(_path("pairing.json"), record, private=True)


def forget_pairing():
    with _LOCK:
        try:
            os.remove(_path("pairing.json"))
        except OSError:
            pass


# ---------- helper programs ----------

def tool_paths():
    with _LOCK:
        data = _read_json(_path("tools.json"))
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def tool_path(name):
    """The path the plugin gave for a helper program (only if that file is there), else None."""
    path = tool_paths().get(name)
    return path if path and os.path.isfile(path) else None


def set_tool_path(name, path):
    """The plugin installed a helper: remember its path (an existing file; None forgets it)."""
    with _LOCK:
        data = _read_json(_path("tools.json"))
        if path:
            data[name] = os.path.normpath(path)
        else:
            data.pop(name, None)
        _write_json(_path("tools.json"), data)
