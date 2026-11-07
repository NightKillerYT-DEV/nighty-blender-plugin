# SPDX-License-Identifier: GPL-3.0-or-later
# Unpacks a downloaded archive (.7z / .zip, e.g. a tool's portable build) without extra software: Windows 10 / 11
# ship bsdtar (tar.exe in System32, libarchive) which reads 7z and zip. 7-Zip is used when installed. Unpacks into a
# temporary folder next to the target, checks the result, then moves it into place, so a cut never leaves half a
# folder.

import os
import shutil
import subprocess
import sys
import threading
import time

from .download import Cancelled


class UnpackError(Exception):
    pass


def _no_window():
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def find_tools():
    """[(name, exe)] in the order they are tried."""
    tools = []
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base and os.path.isfile(os.path.join(base, "7-Zip", "7z.exe")):
                tools.append(("7z", os.path.join(base, "7-Zip", "7z.exe")))
        system_tar = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
        if os.path.isfile(system_tar):
            tools.append(("bsdtar", system_tar))
    else:
        for name in ("7zz", "7z", "bsdtar"):
            exe = shutil.which(name)
            if exe:
                tools.append(("7z" if name.startswith("7z") else "bsdtar", exe))
    return tools


def command(tool, exe, archive, out_dir):
    if tool == "7z":
        return [exe, "x", "-y", "-bso0", "-bsp1", f"-o{out_dir}", archive]
    return [exe, "-xvf", archive, "-C", out_dir]


def unpack_7z(archive, target, check_files=(), progress=None, cancel=None, tools=None, expected_entries=None):
    """Unpacks `archive` so that its top folder ends up as `target`. check_files: paths (relative to the archive's
    top folder) that must exist afterwards. progress(done_entries, expected_entries or None)."""
    tools = tools if tools is not None else find_tools()
    if not tools:
        raise UnpackError("No unpacker found: Windows' tar.exe is missing. Install 7-Zip (7-zip.org) and try again.")
    parent = os.path.dirname(os.path.abspath(target))
    os.makedirs(parent, exist_ok=True)
    tmp = os.path.join(parent, ".unpack-" + os.path.basename(target))
    errors = []
    for tool, exe in tools:
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        try:
            _run(command(tool, exe, archive, tmp), tool, progress, cancel, expected_entries)
        except Cancelled:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        except UnpackError as err:
            errors.append(f"{tool}: {err}")
            continue
        top = _top_folder(tmp)
        missing = [p for p in check_files if not os.path.exists(os.path.join(top, *p.split("/")))]
        if missing:
            errors.append(f"{tool}: missing after unpacking: {', '.join(missing)}")
            continue
        if os.path.exists(target):
            old = target + ".old"
            shutil.rmtree(old, ignore_errors=True)
            os.replace(target, old)
            shutil.rmtree(old, ignore_errors=True)
        os.replace(top, target)
        shutil.rmtree(tmp, ignore_errors=True)
        return target
    shutil.rmtree(tmp, ignore_errors=True)
    raise UnpackError("Unpacking failed. " + " | ".join(errors))


def _top_folder(tmp):
    entries = [e for e in os.listdir(tmp) if not e.startswith(".")]
    if len(entries) == 1 and os.path.isdir(os.path.join(tmp, entries[0])):
        return os.path.join(tmp, entries[0])
    return tmp


def _run(cmd, tool, progress, cancel, expected):
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            **_no_window())
    count = [0]
    tail = []

    def reader():
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            tail.append(line)
            del tail[:-20]
            if tool == "bsdtar" and line.startswith("x "):
                count[0] += 1
            elif tool == "7z" and "%" in line:   # 7z -bsp1 prints " 42% 1234 - path"
                try:
                    count[0] = int(line.split("%", 1)[0].split()[-1])
                except (ValueError, IndexError):
                    pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            proc.kill()
            proc.wait()
            raise Cancelled()
        if progress:
            if tool == "7z":
                progress(count[0], 100)
            else:
                progress(count[0], expected)
        time.sleep(0.2)
    t.join(timeout=5)
    if proc.returncode != 0:
        raise UnpackError(f"exit code {proc.returncode}: {' / '.join(tail[-3:])}")
