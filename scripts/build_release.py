# SPDX-License-Identifier: GPL-3.0-or-later
# Builds everything a release ships, reproducibly (sorted entries, fixed timestamps), in plain Python:
#
#     python scripts/build_release.py [--tag v2.0.0] [--out dist/release] [--blender PATH]
#
#   1. nighty_blender-<v>.zip      the Blender add-on (addon/nighty_blender + guides + the examples' script,
#                                  verify.json and 512 px render), files at the zip's root like
#                                  `blender --command extension build` makes them; --blender also validates it
#   2. its SHA-256 and size are pinned into the plugin's main.js (the /*@pins*/ block)
#   3. nighty-blender-<v>.nightyplugin   plugin.json + main.js + icon.svg + README.md + skills/, checked against the
#                                  Nighty Vault plugin limits (5 MB, 2 MB a file, 200 files, allowed types only)
#   4. skills.zip                  skills/ (for people who install the skills by hand)
#   5. SHA256SUMS                  of the three files above
# Nothing here uploads or publishes anything (the GitHub workflow attaches the files to the release).

import argparse
import fnmatch
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ADDON = os.path.join(ROOT, "addon", "nighty_blender")
PLUGIN = os.path.join(ROOT, "plugin")
SKILLS = os.path.join(ROOT, "skills")
REPO_URL = "https://github.com/NightKillerYT-DEV/nighty-blender-plugin"
EXAMPLE_FILES = ("script.py", "verify.json", "render.jpg")
FIXED_TIME = (2026, 1, 1, 0, 0, 0)      # every zip entry gets this time: the same input gives the same bytes
PLUGIN_TYPES = (".js", ".json", ".md", ".txt", ".css", ".png", ".svg", ".webp", ".jpg")
PLUGIN_LIMITS = {"total": 5 * 1024 * 1024, "file": 2 * 1024 * 1024, "files": 200}
ADDON_LIMIT = int(3.3 * 1024 * 1024)


def addon_version():
    with open(os.path.join(ADDON, "blender_manifest.toml"), encoding="utf-8") as f:
        text = f.read()
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1), text


def excluded(rel, patterns):
    """blender_manifest.toml [build] paths_exclude_pattern, the way Blender reads it (gitignore-like)."""
    parts = rel.split("/")
    for pat in patterns:
        if pat.endswith("/"):
            name = pat.strip("/")
            if pat.startswith("/"):
                if rel == name or rel.startswith(name + "/"):
                    return True
            elif name in parts[:-1] or name == parts[-1]:
                return True
        elif any(fnmatch.fnmatch(p, pat) for p in parts):
            return True
    return False


def addon_files():
    """[(path inside the zip, source path)] of the add-on, sorted."""
    _, manifest = addon_version()
    m = re.search(r"paths_exclude_pattern\s*=\s*\[(.*?)\]", manifest, re.S)
    patterns = re.findall(r'"([^"]+)"', m.group(1)) if m else []
    out = []
    for dirpath, dirnames, filenames in os.walk(ADDON):
        dirnames.sort()
        for name in sorted(filenames):
            src = os.path.join(dirpath, name)
            rel = os.path.relpath(src, ADDON).replace(os.sep, "/")
            if excluded(rel, patterns) or name.endswith(".pyc"):
                continue
            out.append((rel, src))
    guides = os.path.join(ROOT, "guides")
    for name in sorted(os.listdir(guides)):
        if name.endswith((".md", ".json")):
            out.append(("guides/" + name, os.path.join(guides, name)))
    examples = os.path.join(ROOT, "examples")
    for name in sorted(os.listdir(examples)):
        folder = os.path.join(examples, name)
        if not os.path.isfile(os.path.join(folder, "script.py")):
            continue
        for f in EXAMPLE_FILES:
            if os.path.isfile(os.path.join(folder, f)):
                out.append((f"examples/{name}/{f}", os.path.join(folder, f)))
    return sorted(out)


def write_zip(path, entries):
    """entries: [(name, bytes)]. Deterministic: sorted names, fixed times, fixed permissions."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(entries):
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 3
            z.writestr(info, data)


def read(path):
    with open(path, "rb") as f:
        return f.read()


def sha256(path):
    return hashlib.sha256(read(path)).hexdigest()


def pin(main_js, version, url, digest, size):
    block = json.dumps({"addonVersion": version, "addonUrl": url, "addonSha256": digest, "addonSize": size},
                       indent=2)
    new, n = re.subn(r"/\*@pins\*/\{.*?\}/\*@end\*/", lambda _: "/*@pins*/" + block + "/*@end*/", main_js,
                     flags=re.S)
    if n != 1:
        sys.exit("main.js has no /*@pins*/ ... /*@end*/ block")
    return new


def plugin_entries(version, pinned_main):
    entries = []
    manifest = json.loads(read(os.path.join(PLUGIN, "plugin.json")).decode("utf-8"))
    if manifest.get("version") != version:
        sys.exit(f"plugin.json says {manifest.get('version')}, the add-on {version}: run scripts/gen_plugin_json.py")
    for name in sorted(os.listdir(PLUGIN)):
        src = os.path.join(PLUGIN, name)
        if not os.path.isfile(src):
            continue
        data = pinned_main.encode("utf-8") if name == "main.js" else read(src)
        entries.append((name, data))
    for dirpath, dirnames, filenames in os.walk(SKILLS):
        dirnames.sort()
        for name in sorted(filenames):
            src = os.path.join(dirpath, name)
            rel = os.path.relpath(src, ROOT).replace(os.sep, "/")
            entries.append((rel, read(src)))
    total = 0
    for name, data in entries:
        if not name.lower().endswith(PLUGIN_TYPES):
            sys.exit(f"{name}: Nighty Vault keeps only {', '.join(PLUGIN_TYPES)} files in a plugin")
        if len(data) > PLUGIN_LIMITS["file"]:
            sys.exit(f"{name}: over 2 MB")
        total += len(data)
    if total > PLUGIN_LIMITS["total"] or len(entries) > PLUGIN_LIMITS["files"]:
        sys.exit(f"the plugin is {total} bytes in {len(entries)} files (5 MB / 200 files at most)")
    return entries


def validate_with_blender(blender, zip_path):
    res = subprocess.run([blender, "--factory-startup", "--command", "extension", "validate", zip_path],
                         capture_output=True, text=True)
    print((res.stdout + res.stderr).strip())
    if res.returncode != 0:
        sys.exit("Blender says the add-on zip is not a valid extension")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", help="the release tag (vX.Y.Z); must match the add-on's version")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "release"))
    ap.add_argument("--blender", help="validate the add-on zip with this Blender (optional)")
    args = ap.parse_args()
    version, _ = addon_version()
    if args.tag and args.tag.lstrip("v") != version:
        sys.exit(f"tag {args.tag} does not match the add-on version {version}")
    out = os.path.abspath(args.out)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)

    # 1. the add-on zip
    zip_name = f"nighty_blender-{version}.zip"
    zip_path = os.path.join(out, zip_name)
    write_zip(zip_path, [(rel, read(src)) for rel, src in addon_files()])
    size = os.path.getsize(zip_path)
    digest = sha256(zip_path)
    print(f"1. {zip_name}: {size:,} bytes, sha256 {digest}")
    if size >= ADDON_LIMIT:
        sys.exit(f"the add-on zip is {size:,} bytes (keep it under 3.3 MB)")
    if args.blender:
        validate_with_blender(args.blender, zip_path)

    # 2. + 3. the plugin, with the add-on pinned
    url = f"{REPO_URL}/releases/download/v{version}/{zip_name}"
    main_js = pin(read(os.path.join(PLUGIN, "main.js")).decode("utf-8"), version, url, digest, size)
    plugin_name = f"nighty-blender-{version}.nightyplugin"
    plugin_path = os.path.join(out, plugin_name)
    write_zip(plugin_path, plugin_entries(version, main_js))
    print(f"2. pinned {digest[:16]}... into main.js")
    print(f"3. {plugin_name}: {os.path.getsize(plugin_path):,} bytes")

    # 4. skills.zip
    skills_path = os.path.join(out, "skills.zip")
    entries = []
    for dirpath, dirnames, filenames in os.walk(SKILLS):
        dirnames.sort()
        for name in sorted(filenames):
            src = os.path.join(dirpath, name)
            entries.append((os.path.relpath(src, SKILLS).replace(os.sep, "/"), read(src)))
    write_zip(skills_path, entries)
    print(f"4. skills.zip: {len(entries)} files")

    # 5. SHA256SUMS
    sums = "".join(f"{sha256(os.path.join(out, n))}  {n}\n" for n in (zip_name, plugin_name, "skills.zip"))
    with open(os.path.join(out, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as f:
        f.write(sums)
    print("5. SHA256SUMS\n" + sums.rstrip())
    with open(os.path.join(out, "release.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"version": version, "addon": {"file": zip_name, "sha256": digest, "size": size, "url": url},
                   "plugin": plugin_name}, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
