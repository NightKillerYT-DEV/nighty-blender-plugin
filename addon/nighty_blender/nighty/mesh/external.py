# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional helpers that are NOT part of Blender. We only find and use what the person has:

- Instant Meshes (BSD-3 + an "Enhancements" clause, see docs/LICENSES.md): a separate program, downloaded only when
  the person says yes (the Nighty Vault plugin's Get Instant Meshes button): the official build, size and SHA-256 pinned
  below, into <tools folder>/tools/instant-meshes/ (the plugin's Get Instant Meshes button does the same in its own folder). Also found via NIGHTY_INSTANT_MESHES or on PATH.
- xatlas (MIT, mworchel/xatlas-python): shipped as wheels inside the extension (blender_manifest.toml), run in
  Blender's own python.exe as a separate process (in Blender 4.2 the module crashes inside Blender: an older C++
  runtime is loaded there). See xa.py.
- QuadWild / QuadWild-BiMDF (GPL-3.0): command-line programs the person installed (NIGHTY_QUADWILD_DIR or PATH).
- QRemeshify (GPL-3.0 Blender extension, wraps QuadWild): used when the person installed and enabled it.
- Exoside Quad Remesher (commercial, per seat): only reported when the person owns and installed it; it runs from
  its own panel with their license.
Blender's QuadriFlow (MIT, built in) is always there.
"""

import glob
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

import bpy
import numpy as np

from . import _util as U

ENGINE_NAMES = {"quadriflow": "QuadriFlow", "instant_meshes": "Instant Meshes", "quadwild": "QuadWild",
                "qremeshify": "QRemeshify", "quad_remesher": "Quad Remesher"}

# The official Instant Meshes build (README of wjakob/instant-meshes, line 31). Fetched once with the owner's OK on
# 2026-10-23 to pin it; a person's own download is kept only when size and SHA-256 match. The zip holds one file.
INSTANT_MESHES_DOWNLOAD = {
    "win32": {"url": "https://instant-meshes.s3.eu-central-1.amazonaws.com/Release/instant-meshes-windows.zip",
              "size": 1401791, "sha256": "c9f6217e83ea90f98a8cd54cf82dac88420df20cf197e7a4ef2bef81c5ae068d",
              "exe": "Instant Meshes.exe", "exe_size": 3449856,
              "exe_sha256": "f1fe5b5f56d1002ae61dbd76a3fd646229fc1fe15322e7a3744f8ce442c76b2d"},
    # macOS / Linux builds exist at the same place but are not pinned yet (not fetched): no download there for now
    "darwin": {"url": "https://instant-meshes.s3.eu-central-1.amazonaws.com/instant-meshes-macos.zip",
               "exe": "Instant Meshes.app/Contents/MacOS/Instant Meshes", "sha256": ""},
    "linux": {"url": "https://instant-meshes.s3.eu-central-1.amazonaws.com/instant-meshes-linux.zip",
              "exe": "Instant Meshes", "sha256": ""},
    "host": "instant-meshes.s3.eu-central-1.amazonaws.com",
    "page": "https://github.com/wjakob/instant-meshes",
    "license": "BSD-3-Clause with an extra 'Enhancements' clause (improvements you share are licensed back to the "
               "authors); free, also commercially",
    "folder": "tools/instant-meshes",  # inside tools_root()
}


def tools_root():
    """Where Nighty Blender keeps helper programs it downloads itself (development / no plugin): <state dir>/tools.
    NIGHTY_TOOLS_DIR overrides it (tests). The Nighty Vault plugin installs Instant Meshes in its own folder and
    tells the addon the path (settings.set_tool_path)."""
    env = os.environ.get("NIGHTY_TOOLS_DIR")
    if env:
        return env
    from ..io import settings
    return settings.state_dir()


def _platform_key():
    return "win32" if sys.platform == "win32" else ("darwin" if sys.platform == "darwin" else "linux")


def instant_meshes_path():
    """Where the installed program lives (it may not be there yet)."""
    return os.path.normpath(os.path.join(tools_root(), INSTANT_MESHES_DOWNLOAD["folder"],
                                         INSTANT_MESHES_DOWNLOAD[_platform_key()]["exe"]))


def find_instant_meshes():
    """Path (or a command list for tests) of Instant Meshes, or None."""
    env = os.environ.get("NIGHTY_INSTANT_MESHES")
    if env:
        return env
    try:
        from ..io import settings
        given = settings.tool_path("instant_meshes")   # installed by the Nighty Vault plugin
    except Exception:  # noqa: BLE001
        given = None
    if given:
        return given
    p = instant_meshes_path()
    if os.path.isfile(p):
        return p
    for name in ("Instant Meshes", "instant-meshes", "InstantMeshes"):
        w = shutil.which(name)
        if w:
            return w
    return None


def instant_meshes_offer():
    """What to tell the person before downloading Instant Meshes (None when this platform has no pinned build)."""
    info = INSTANT_MESHES_DOWNLOAD[_platform_key()]
    if not info.get("sha256"):
        return None
    folder = os.path.dirname(instant_meshes_path())
    return {"what": "Instant Meshes: a quad remesher (clean quads, keeps creases), faster than Blender's built-in one",
            "size_mb": round(info["size"] / 1e6, 1), "from": info["url"], "page": INSTANT_MESHES_DOWNLOAD["page"],
            "license": INSTANT_MESHES_DOWNLOAD["license"], "folder": folder,
            "ask": (f"OK to download Instant Meshes ({info['size'] / 1e6:.1f} MB, free, BSD license) from its "
                    f"official address into {folder}?")}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _only_host(host):
    def check(u):  # just this one host, https only (also after redirects)
        import urllib.parse
        parts = urllib.parse.urlsplit(u)
        return parts.scheme == "https" and (parts.hostname or "").lower() == host
    return check


def install_instant_meshes(progress=None, cancel=None, url=None, check=None):
    """Downloads the pinned official build (only after the person said yes), checks its size and SHA-256, unpacks
    the one program file into <tools folder>/tools/instant-meshes/ (the plugin's Get Instant Meshes button does the same in its own folder) and checks that too. Returns the program path.
    url / check: tests only (a local server)."""
    import zipfile
    from ..io import download as D
    info = INSTANT_MESHES_DOWNLOAD[_platform_key()]
    if not info.get("sha256"):
        raise ValueError("there is no checked Instant Meshes build for this system yet")
    exe = instant_meshes_path()
    if os.path.isfile(exe) and os.path.getsize(exe) == info["exe_size"] and _sha256(exe) == info["exe_sha256"]:
        return exe
    zpath = os.path.join(tools_root(), "downloads", "instant-meshes-windows.zip")
    report = progress or (lambda frac, msg: None)
    D.download(url or info["url"], zpath, info["size"], info["sha256"],
               progress=lambda phase, done, total: report(0.9 * done / max(total, 1), f"{phase} {done // 1024} KB"),
               cancel=cancel, check=check or _only_host(INSTANT_MESHES_DOWNLOAD["host"]), segments=1)
    report(0.92, "unpacking")
    folder = os.path.dirname(exe)
    os.makedirs(folder, exist_ok=True)
    tmp = exe + ".part"
    with zipfile.ZipFile(zpath) as z:
        if info["exe"] not in z.namelist():
            raise ValueError(f"the download has no {info['exe']!r}")
        with z.open(info["exe"]) as src, open(tmp, "wb") as dst:  # only the one expected file, by its exact name
            shutil.copyfileobj(src, dst)
    if os.path.getsize(tmp) != info["exe_size"] or _sha256(tmp) != info["exe_sha256"]:
        os.remove(tmp)
        raise ValueError("the unpacked program does not match the pinned SHA-256; it was deleted")
    os.replace(tmp, exe)
    with open(os.path.join(folder, "SOURCE.txt"), "w", encoding="utf-8") as f:
        f.write(f"Instant Meshes, downloaded from {info['url']}\nProject: {INSTANT_MESHES_DOWNLOAD['page']}\n"
                f"License: {INSTANT_MESHES_DOWNLOAD['license']} (see the project's LICENSE.txt)\n"
                f"SHA-256: {info['exe_sha256']}\n")
    try:
        os.remove(zpath)
    except OSError:
        pass
    report(1.0, "ready")
    return exe


def find_quadwild():
    d = os.environ.get("NIGHTY_QUADWILD_DIR")
    cands = []
    if d:
        cands.append(d)
    cands.append(os.path.join(tools_root(), "tools", "quadwild"))
    for c in cands:
        qw = [os.path.join(c, n) for n in ("quadwild.exe", "quadwild")]
        qp = [os.path.join(c, n) for n in ("quad_from_patches.exe", "quad_from_patches")]
        a = next((x for x in qw if os.path.isfile(x)), None)
        b = next((x for x in qp if os.path.isfile(x)), None)
        if a and b:
            return {"dir": c, "quadwild": a, "quad_from_patches": b}
    a, b = shutil.which("quadwild"), shutil.which("quad_from_patches")
    if a and b:
        return {"dir": os.path.dirname(a), "quadwild": a, "quad_from_patches": b}
    return None


def _addon_module(fragment):
    """Module name of an enabled addon / extension whose name contains fragment (or None)."""
    try:
        for m in bpy.context.preferences.addons.keys():
            if fragment in m.lower():
                return m
    except Exception:  # noqa: BLE001 - background / no prefs
        pass
    return None


def find_qremeshify():
    mod = _addon_module("qremeshify")
    if mod and hasattr(bpy.ops, "qremeshify") and hasattr(bpy.types.Scene, "quadwild_props"):
        return mod
    return mod


def find_quad_remesher():
    for frag in ("quadremesher", "quad_remesher", "qremesher"):
        m = _addon_module(frag)
        if m:
            return m
    return None


def has_xatlas():
    """xatlas is there (found, not imported: importing it inside Blender 4.2 crashes Blender)."""
    from . import xa
    return xa.module_dir() is not None


def engines():
    """What is available here, for status / the retopo tool's answer."""
    im = find_instant_meshes()
    return {
        "quadriflow": {"available": True, "license": "MIT (built into Blender)"},
        "instant_meshes": {"available": bool(im), "path": im if isinstance(im, str) else None,
                           "license": "BSD-3 + Enhancements clause",
                           "note": None if im else "not installed: the person gets it with Get Instant Meshes in Nighty Vault's Blender card"},
        "quadwild": {"available": bool(find_quadwild()), "license": "GPL-3.0 (installed by you)"},
        "qremeshify": {"available": bool(find_qremeshify()), "license": "GPL-3.0 (installed by you)"},
        "quad_remesher": {"available": bool(find_quad_remesher()), "license": "commercial (your own license)",
                          "note": "runs from its own panel with your license (not driven by Nighty)"},
        "xatlas": {"available": has_xatlas(), "license": "MIT", "use": "UVs for triangle meshes"},
    }


def pick_quad_engine(engine="auto"):
    """'auto': QRemeshify > Instant Meshes > QuadriFlow (best free quality first, all only if present)."""
    if engine in (None, "auto"):
        if find_qremeshify():
            return "qremeshify"
        if find_instant_meshes():
            return "instant_meshes"
        return "quadriflow"
    if engine == "instant_meshes" and not find_instant_meshes():
        raise ValueError("Instant Meshes is not installed: the person gets it with Get Instant Meshes in Nighty Vault's Blender card")
    if engine == "quadwild" and not find_quadwild():
        raise ValueError("QuadWild is not installed (set NIGHTY_QUADWILD_DIR to its folder)")
    if engine == "qremeshify" and not find_qremeshify():
        raise ValueError("QRemeshify is not installed / enabled in this Blender")
    if engine == "quad_remesher":
        raise ValueError("Quad Remesher runs from its own panel with your license (Nighty does not drive it); run "
                         "it there, then uv_unwrap / make_lods work on its result")
    if engine not in ENGINE_NAMES:
        raise ValueError(f"unknown engine {engine!r}")
    return engine


# ---------------------------------------------------------------- OBJ in / out (tiny, fast, no operators)

def write_obj(path, co, faces_flat, sizes):
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write("".join(f"v {x:.7g} {y:.7g} {z:.7g}\n" for x, y, z in co))
        i = 0
        lines = []
        for s in sizes:
            lines.append("f " + " ".join(str(int(v) + 1) for v in faces_flat[i:i + s]) + "\n")
            i += s
        f.write("".join(lines))


def read_obj(path):
    co, flat, sizes = [], [], []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("v "):
                co.append([float(t) for t in line.split()[1:4]])
            elif line.startswith("f "):
                idx = [int(t.split("/")[0]) for t in line.split()[1:]]
                n = len(co)
                idx = [i - 1 if i > 0 else n + i for i in idx]
                flat.extend(idx)
                sizes.append(len(idx))
    return np.array(co, dtype=np.float64).reshape(-1, 3), np.array(flat, dtype=np.int64), np.array(sizes, dtype=np.int64)


def _mesh_arrays(obj):
    me = obj.data
    start, total, lv, _le = U.polys(me)
    return U.verts(me), lv, total


def _replace_from_obj(obj, path):
    co, flat, sizes = read_obj(path)
    if len(sizes) == 0:
        raise RuntimeError("the remesher wrote an empty mesh")
    me = U.new_mesh_from_arrays(obj.data.name, co, flat, sizes)
    U.replace_mesh(obj, me)


class RemesherTimeout(RuntimeError):
    """An outside remesher stopped answering (it was killed)."""


def _kill_tree(proc):
    """Kills a process and everything it started (Windows: taskkill /T; elsewhere its process group)."""
    try:
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=20, creationflags=flags)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:  # noqa: BLE001 - already gone
        pass
    try:
        proc.kill()
        proc.wait(timeout=10)
    except Exception:  # noqa: BLE001
        pass


def _run(cmd, timeout, cwd=None):
    """Runs an outside program with no window and nothing on stdin (it can never wait for a key or a dialog), its
    output in a file (a full pipe can never block it), and kills it with everything it started after `timeout`
    seconds (RemesherTimeout)."""
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess,
                                                                                   "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kw["start_new_session"] = True
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **kw)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            raise RemesherTimeout(f"{os.path.basename(str(cmd[0]))} did not finish in {timeout:.0f} s") from None
        log.seek(0)
        out = log.read().decode("utf-8", "replace")[-2000:]
    if code != 0:
        raise RuntimeError(f"{os.path.basename(str(cmd[0]))} failed (code {code}): {out.strip()[-400:]}")
    return out


def remesher_timeout(in_faces):
    """Seconds an outside remesher may take: tens of seconds, a bit more for big inputs (Instant Meshes does 500k
    faces in ~15-20 s). NIGHTY_REMESH_TIMEOUT overrides it (tests)."""
    env = os.environ.get("NIGHTY_REMESH_TIMEOUT")
    if env:
        return float(env)
    return min(150.0, max(30.0, 15.0 + 25.0 * in_faces / 100000.0))


def instant_meshes(obj, faces, crease=None, exe=None, timeout=None):
    """Instant Meshes: pure quads (4-RoSy / 4-PoSy), creases kept above `crease` degrees. In place. Its pure-quad
    mode splits every face of its quad-dominant result in four, so it is asked for a quarter of the faces; one more
    run corrects the count when it is far off. Returns the face count."""
    exe = exe or find_instant_meshes()
    if not exe:
        raise ValueError("Instant Meshes is not installed")
    cmd0 = exe if isinstance(exe, list) else [exe]
    d = tempfile.mkdtemp(prefix="nighty-im-")
    try:
        src, out = os.path.join(d, "in.obj"), os.path.join(d, "out.obj")
        co, flat, sizes = _mesh_arrays(obj)
        write_obj(src, co, flat, sizes)
        border = U.edge_flags(obj.data, "use_seam").any() or _has_border(obj)
        ask = max(8, int(faces) // 4)
        limit = timeout or remesher_timeout(len(sizes))
        threads = str(max(1, min(8, (os.cpu_count() or 4) // 2)))  # never all cores: other work keeps running
        best = None
        for _try in range(2):
            cmd = cmd0 + [src, "-o", out, "-f", str(ask), "-r", "4", "-p", "4", "-d", "-S", "2", "-t", threads]
            if crease:
                cmd += ["-c", str(float(crease))]
            if border:
                cmd += ["-b"]
            if os.path.isfile(out):
                os.remove(out)
            try:
                _run(cmd, limit)
            except RemesherTimeout:  # it hangs now and then (seen under heavy CPU load): one more try
                if os.path.isfile(out):
                    os.remove(out)
                _run(cmd, limit)
            if not os.path.isfile(out):
                raise RuntimeError("Instant Meshes wrote no output")
            got = read_obj(out)
            n = len(got[2])
            if best is None or abs(n - faces) < abs(best[0] - faces):
                best = (n, got)
            if abs(n - faces) <= 0.12 * faces or n == 0:
                break
            ask = max(8, int(ask * faces / max(n, 1)))
        co2, flat2, sizes2 = best[1]
        if len(sizes2) == 0:
            raise RuntimeError("Instant Meshes wrote an empty mesh")
        me = U.new_mesh_from_arrays(obj.data.name, co2, flat2, sizes2)
        U.replace_mesh(obj, me)
        return len(obj.data.polygons)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _has_border(obj):
    _s, _t, _lv, le = U.polys(obj.data)
    return bool(len(le)) and bool((np.bincount(le) == 1).any())


def quadwild(obj, faces, sharp=None, timeout=1800):
    """QuadWild-BiMDF command-line programs (GPL, installed by the person). Experimental: face count is steered by
    QuadWild's own scale; the result count is reported."""
    qw = find_quadwild()
    if not qw:
        raise ValueError("QuadWild is not installed")
    d = tempfile.mkdtemp(prefix="nighty-qw-")
    try:
        src = os.path.join(d, "mesh.obj")
        co, flat, sizes = _mesh_arrays(obj)
        write_obj(src, co, flat, sizes)
        prep = os.path.join(qw["dir"], "config", "prep_config", "basic_setup.txt")
        main = os.path.join(qw["dir"], "config", "main_config", "flow_noalign.txt")
        _run([qw["quadwild"], src, "2", prep] if os.path.isfile(prep) else [qw["quadwild"], src, "2"], timeout, cwd=d)
        rem = os.path.join(d, "mesh_rem_p0.obj")
        if not os.path.isfile(rem):
            raise RuntimeError("QuadWild wrote no patches")
        args = [qw["quad_from_patches"], rem, "123"] + ([main] if os.path.isfile(main) else [])
        _run(args, timeout, cwd=d)
        outs = sorted(glob.glob(os.path.join(d, "*quadrangulation*.obj")), key=os.path.getmtime)
        if not outs:
            raise RuntimeError("QuadWild wrote no quad mesh")
        smooth = [o for o in outs if "smooth" in o]
        _replace_from_obj(obj, (smooth or outs)[-1])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def qremeshify(obj, faces, sharp=None, symmetry=None):
    """QRemeshify (GPL extension, installed by the person), synchronous. Its scale factor sets the density, so the
    face count is approximate."""
    if not find_qremeshify():
        raise ValueError("QRemeshify is not installed / enabled")
    sc = bpy.context.scene
    props, qr = sc.quadwild_props, sc.quadpatches_props
    props.enableSharp = bool(sharp)
    if sharp:
        props.sharpAngle = float(sharp)
    props.symmetryX = symmetry == "x"
    props.symmetryY = symmetry == "y"
    props.symmetryZ = symmetry == "z"
    props.enableRemesh = True
    props.enableSmoothing = True
    props.useCache = False
    # QuadWild's scale factor: bigger = bigger quads. Rough start from the current face size.
    try:
        area = sum(p.area for p in obj.data.polygons)
        qr.scaleFact = max(0.1, min(10.0, (area / max(faces, 1)) ** 0.5 / ((area / max(len(obj.data.polygons), 1)) ** 0.5 * 4)))
    except Exception:  # noqa: BLE001
        pass
    names = set(o.name for o in bpy.data.objects)
    with U.override(obj):
        res = bpy.ops.qremeshify.remesh()
    if 'FINISHED' not in res:
        raise RuntimeError("QRemeshify did not finish")
    new = [o for o in bpy.data.objects if o.name not in names and o.type == 'MESH']
    if not new:
        raise RuntimeError("QRemeshify made no object")
    res_obj = new[0]
    for m in list(res_obj.modifiers):  # symmetry comes as a Mirror modifier: apply it
        U.apply_modifiers(res_obj, [m])
    U.replace_mesh(obj, res_obj.data.copy())
    obj.hide_set(False)
    for o in new:
        bpy.data.objects.remove(o)
