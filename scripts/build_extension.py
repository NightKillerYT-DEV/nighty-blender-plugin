# SPDX-License-Identifier: GPL-3.0-or-later
# Build the Nighty Blender extension and the static repository the site hosts.
#
#     python scripts/build_extension.py [BLENDER_EXE ...]
#
# With no arguments it uses the two portable test Blenders. It:
#   1. regenerates addon/nighty_blender/tools.json from the registry (inside Blender),
#   2. stages the addon with the guides (guides/*.md, guides.json) and the examples (script.py, verify.json,
#      render.jpg) inside it, so the guide tool (guides and examples) works in the installed extension, and builds the
#      extension zip from that stage into dist/repo/  (`blender --command extension build`),
#   3. writes the static repo index.json + index.html (`blender --command extension server-generate --html`).
# With --check-install it then installs the extension on each Blender, in a throwaway user folder, and runs
# scripts/check_installed.py there (the installed copy's tools: guide, look, run_python, check).
# Nothing here publishes: the owner uploads dist/repo to the site by hand.

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ADDON = os.path.join(ROOT, "addon", "nighty_blender")
DIST = os.path.join(ROOT, "dist")
REPO = os.path.join(DIST, "repo")
STAGE = os.path.join(DIST, "stage", "nighty_blender")
EXAMPLE_FILES = ("script.py", "verify.json", "render.jpg")  # the 512 px JPEG (scripts/example_thumbs.py), not the PNG
ZIP = None   # --zip: check this zip instead of building

DEFAULT_BLENDERS = [
    r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
    os.environ.get("NIGHTY_BLENDER_42", ""),  # a portable Blender 4.2 LTS, if you have one
]


def _addon_version():
    """The version in blender_manifest.toml (the built zip is named after it)."""
    import re
    with open(os.path.join(ADDON, "blender_manifest.toml"), encoding="utf-8") as f:
        m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
    return m.group(1) if m else "1.0.0"


def run(argv, **kw):
    print("  $", " ".join(str(a) for a in argv))
    result = subprocess.run(argv, capture_output=True, text=True, **kw)
    if result.stdout:
        print("    " + result.stdout.replace("\n", "\n    ").rstrip())
    if result.returncode != 0:
        print("    [stderr] " + (result.stderr or "").replace("\n", "\n    ").rstrip())
    return result


def gen_tools_json(blender):
    print("1. tools.json")
    res = run([blender, "-b", "--factory-startup", "--python", os.path.join(HERE, "gen_tools_json.py")])
    if res.returncode != 0:
        sys.exit("tools.json generation failed")


def stage():
    """The addon folder plus guides/ and examples/ (what the package ships), in dist/stage/nighty_blender."""
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    shutil.copytree(ADDON, STAGE, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    guides = os.path.join(ROOT, "guides")
    os.makedirs(os.path.join(STAGE, "guides"))
    for name in sorted(os.listdir(guides)):
        if name.endswith((".md", ".json")):
            shutil.copy2(os.path.join(guides, name), os.path.join(STAGE, "guides", name))
    examples = os.path.join(ROOT, "examples")
    count = 0
    for name in sorted(os.listdir(examples)):
        src = os.path.join(examples, name)
        if not os.path.isfile(os.path.join(src, "script.py")):
            continue
        os.makedirs(os.path.join(STAGE, "examples", name))
        for f in EXAMPLE_FILES:
            if os.path.isfile(os.path.join(src, f)):
                shutil.copy2(os.path.join(src, f), os.path.join(STAGE, "examples", name, f))
        count += 1
    print("   staged the addon with %d guides and %d examples" % (len(os.listdir(os.path.join(STAGE, "guides"))),
                                                                  count))
    return STAGE


def build(blender):
    print("2. build zip")
    source = stage()
    if os.path.isdir(REPO):
        for name in os.listdir(REPO):
            if name.endswith(".zip"):
                os.remove(os.path.join(REPO, name))
    os.makedirs(REPO, exist_ok=True)
    res = run([blender, "--command", "extension", "build", "--source-dir", source, "--output-dir", REPO])
    if res.returncode != 0:
        sys.exit("build failed")


def server_generate(blender):
    print("3. static repo (index.json + index.html)")
    res = run([blender, "--command", "extension", "server-generate", "--repo-dir", REPO, "--html"])
    if res.returncode != 0:
        sys.exit("server-generate failed")
    index = os.path.join(REPO, "index.json")
    if not os.path.exists(index):
        sys.exit("no index.json was written")
    print("   wrote:", ", ".join(sorted(os.listdir(REPO))))


def check_install(blenders):
    print("4. check install on each Blender (throwaway user folder)")
    zip_path = ZIP or os.path.join(REPO, "nighty_blender-%s.zip" % _addon_version())
    if not ZIP:
        _check_index()
    ok = True
    for blender in blenders:
        print("   -", blender)
        user = tempfile.mkdtemp(prefix="nb-install-")
        env = dict(os.environ, BLENDER_USER_RESOURCES=user)
        try:
            # install the built zip into the user_default repo, then enable and list it (no online access needed)
            run([blender, "--command", "extension", "install-file", "-r", "user_default", "-e", zip_path], env=env)
            listing = run([blender, "--command", "extension", "list"], env=env)
            out = listing.stdout or ""
            if "Nighty Blender" not in out and "nighty_blender" not in out:
                print("     ! not listed as installed")
                ok = False
            if "Policy violation" in out:
                print("     ! Blender reports an extension policy violation")
                ok = False
            # the installed copy really works: guides, examples, look, run_python with `import nighty`
            check = run([blender, "-b", "--python-exit-code", "1", "--python",
                         os.path.join(HERE, "check_installed.py")], env=env)
            if check.returncode != 0 or "INSTALLED OK" not in (check.stdout or ""):
                print("     ! the installed extension's tools failed")
                ok = False
        finally:
            shutil.rmtree(user, ignore_errors=True)
    print("   install check:", "ok" if ok else "FAILED")
    return ok


def _check_index():
    import json
    with open(os.path.join(REPO, "index.json"), encoding="utf-8") as handle:
        index = json.load(handle)
    rows = [row for row in index.get("data", []) if row.get("id") == "nighty_blender"]
    if not rows:
        sys.exit("index.json has no nighty_blender entry")
    row = rows[0]
    if not str(row.get("archive_hash", "")).startswith("sha256:"):
        sys.exit("index.json entry has no sha256 archive_hash")
    print("   index.json: nighty_blender %s, %d bytes, %s"
          % (row.get("version"), row.get("archive_size"), row.get("archive_hash")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("blenders", nargs="*", default=None, help="Blender executables")
    parser.add_argument("--check-install", action="store_true")
    parser.add_argument("--zip", help="only check this built zip (e.g. dist/release/nighty_blender-2.0.0.zip)")
    args = parser.parse_args()
    blenders = args.blenders or [b for b in DEFAULT_BLENDERS if os.path.exists(b)]
    if not blenders:
        sys.exit("no Blender found: pass a path to blender(.exe)")
    build_blender = blenders[0]
    if args.zip:
        global ZIP
        ZIP = os.path.abspath(args.zip)
        sys.exit(0 if check_install(blenders) else 1)

    gen_tools_json(build_blender)
    build(build_blender)
    server_generate(build_blender)
    if args.check_install:
        if not check_install(blenders):
            sys.exit(1)
    print("\nDone. Static repo in: %s" % REPO)


if __name__ == "__main__":
    main()
