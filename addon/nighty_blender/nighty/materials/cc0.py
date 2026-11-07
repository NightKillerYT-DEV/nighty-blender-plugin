# SPDX-License-Identifier: GPL-3.0-or-later
"""CC0 texture sets from Poly Haven and ambientCG, downloaded on demand into a folder the person agreed to.

Nothing is downloaded until the person said yes (`agree(folder)`, stored in Blender's user config). Files are
checked (MD5 from Poly Haven, zip names from ambientCG), kept in the cache folder and recorded with their license
(CC0) so exports can list them. Only color, roughness and height are used: metallic always comes from the
material (0 or 1), never from a picture."""

import hashlib
import json
import os
import threading
import urllib.request
import zipfile

import bpy

UA = "NightyBlender/2.0 (+https://github.com/NightKillerYT-DEV/nighty-blender-plugin)"
MAX_BYTES = 64 * 1024 * 1024
MAPS = {"color": ("Diffuse", "Color"), "roughness": ("Rough", "Roughness"), "height": ("Displacement", "Displacement"),
        "normal": ("nor_gl", "NormalGL")}


def _config_path():
    d = bpy.utils.user_resource("CONFIG", path="nighty_blender", create=True)
    return os.path.join(d, "cc0.json")


def default_folder():
    """The engine's folder when it is set up, else Blender's user folder."""
    eng = os.environ.get("NIGHTY_ENGINE_DIR") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "NightyBlender")
    if eng and os.path.isdir(eng):
        return os.path.join(eng, "cc0")
    return os.path.join(bpy.utils.user_resource("DATAFILES", path="nighty_blender", create=True), "cc0")


def consent():
    try:
        with open(_config_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if data.get("agreed") and data.get("folder") else None
    except (OSError, ValueError):
        return None


def agree(folder=None):
    """Records the person's yes and the folder (created). Returns the folder."""
    folder = os.path.abspath(bpy.path.abspath(folder)) if folder else default_folder()
    os.makedirs(folder, exist_ok=True)
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump({"agreed": True, "folder": folder}, f)
    return folder


def revoke():
    try:
        os.remove(_config_path())
    except OSError:
        pass


def _set_dir(folder, source, asset_id, res):
    return os.path.join(folder, source, f"{asset_id}_{res}")


def cached(source, asset_id, res="1k", folder=None):
    """{map: path} when the set is already in the cache, else None."""
    if not folder:
        c = consent()
        folder = c and c["folder"]
    if not folder:
        return None
    d = _set_dir(folder, source, asset_id, res)
    info = os.path.join(d, "license.json")
    if not os.path.exists(info):
        return None
    with open(info, encoding="utf-8") as f:
        data = json.load(f)
    files = {k: os.path.join(d, v) for k, v in data.get("files", {}).items()}
    return files if files and all(os.path.exists(p) for p in files.values()) else None


def _get(url, limit=MAX_BYTES):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"download too big: {url}")
    return data


def fetch(source, asset_id, res="1k", folder=None, progress=None):
    """Downloads one set (no bpy when `folder` is given: safe in a thread). Returns {map: path}."""
    if not folder:
        c = consent()
        folder = c and c["folder"]
    if not folder:
        raise PermissionError("CC0 downloads need the person's OK first")
    have = cached(source, asset_id, res, folder)
    if have:
        return have
    d = _set_dir(folder, source, asset_id, res)
    os.makedirs(d, exist_ok=True)
    files, page = {}, ""
    if source == "polyhaven":
        page = f"https://polyhaven.com/a/{asset_id}"
        meta = json.loads(_get(f"https://api.polyhaven.com/files/{asset_id}"))
        for i, (key, (ph, _)) in enumerate(MAPS.items()):
            if ph not in meta and key == "color":   # some sets name their color map differently
                ph = next((k for k in sorted(meta) if k.startswith("col")), ph)
            entry = meta.get(ph, {}).get(res, {})
            f = entry.get("jpg") or entry.get("png")
            if not f:
                continue
            data = _get(f["url"])
            if f.get("md5") and hashlib.md5(data).hexdigest() != f["md5"]:
                raise ValueError(f"checksum mismatch for {f['url']}")
            name = os.path.basename(f["url"].split("?")[0])
            with open(os.path.join(d, name), "wb") as fh:
                fh.write(data)
            files[key] = name
            if progress:
                progress((i + 1) / len(MAPS), f"{asset_id}: {key}")
    elif source == "ambientcg":
        page = f"https://ambientcg.com/view?id={asset_id}"
        meta = json.loads(_get(f"https://ambientcg.com/api/v2/full_json?id={asset_id}&include=downloadData"))
        downloads = meta["foundAssets"][0]["downloadFolders"]["default"]["downloadFiletypeCategories"]["zip"][
            "downloads"]
        want = f"{res.upper()}-JPG"
        entry = next((x for x in downloads if x.get("attribute") == want), None)
        if entry is None:
            raise ValueError(f"{asset_id} has no {want} download")
        zpath = os.path.join(d, "set.zip")
        with open(zpath, "wb") as fh:
            fh.write(_get(entry["downloadLink"]))
        with zipfile.ZipFile(zpath) as z:
            for key, (_, suffix) in MAPS.items():
                hit = [n for n in z.namelist() if n.endswith(f"_{suffix}.jpg") and "/" not in n and ".." not in n]
                if hit:
                    with z.open(hit[0]) as src, open(os.path.join(d, hit[0]), "wb") as dst:
                        dst.write(src.read(MAX_BYTES))
                    files[key] = hit[0]
        os.remove(zpath)
        if progress:
            progress(1.0, asset_id)
    else:
        raise ValueError("source must be polyhaven or ambientcg")
    with open(os.path.join(d, "license.json"), "w", encoding="utf-8") as fh:
        json.dump({"license": "CC0", "source": page, "id": asset_id, "res": res, "files": files}, fh)
    return {k: os.path.join(d, v) for k, v in files.items()}


def tag_images(files, source_page):
    """Marks loaded images with their license for the export's attribution file."""
    for p in files.values():
        for img in bpy.data.images:
            if img.filepath and os.path.normcase(bpy.path.abspath(img.filepath)) == os.path.normcase(p):
                img["nighty_license"] = "CC0"
                img["nighty_source"] = source_page


def download_steps(sets, res="1k"):
    """Downloads several sets in a background thread as a job (generator). sets: [(source, id), ...]."""
    c = consent()
    if not c:
        raise PermissionError("CC0 downloads need the person's OK first")
    folder = c["folder"]
    state = {"p": 0.0, "msg": "Starting", "done": False, "error": None, "out": {}}

    def work():
        try:
            for i, (src, aid) in enumerate(sets):
                def prog(p, m, i=i):
                    state["p"], state["msg"] = (i + p) / len(sets), m
                state["out"][aid] = fetch(src, aid, res, folder=folder, progress=prog)
        except Exception as e:  # reported to the AI
            state["error"] = f"{type(e).__name__}: {e}"
        state["done"] = True

    t = threading.Thread(target=work, daemon=True)
    t.start()
    while not state["done"]:
        yield state["p"], state["msg"]
    if state["error"]:
        raise RuntimeError(state["error"])
    return {"downloaded": sorted(state["out"])}
