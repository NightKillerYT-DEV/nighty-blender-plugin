# SPDX-License-Identifier: GPL-3.0-or-later
# Runs the add-on's tests headless in a sandbox, so they never touch the person's own Blender settings, add-ons or
# Nighty Blender pairing:
#
#     python scripts/run_tests.py [--blender PATH ...] [-- name_filter ...]
#
# For each Blender it makes a fresh temporary folder and points Blender's user folders there
# (BLENDER_USER_RESOURCES), plus NIGHTY_BLENDER_STATE_DIR (the pairing token, tool paths), NIGHTY_TOOLS_DIR and
# NIGHTY_BLENDER_PORTS=0 (a free port, never the live 47871-47873). Then `blender -b --factory-startup --python
# tests/run.py`. The folder is removed afterwards. Default Blenders: the installed 5.2 and the portable 4.2.23 test
# copy when they exist.

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULTS = [
    r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
    os.environ.get("NIGHTY_BLENDER_42", ""),  # a portable Blender 4.2 LTS, if you have one
]


def sandbox_env(base, instant_meshes=None):
    env = dict(os.environ)
    env["BLENDER_USER_RESOURCES"] = os.path.join(base, "blender-user")
    env["NIGHTY_BLENDER_STATE_DIR"] = os.path.join(base, "state")
    env["NIGHTY_TOOLS_DIR"] = os.path.join(base, "tools")
    env["NIGHTY_BLENDER_PORTS"] = "0"
    env["NIGHTY_TEST_SANDBOX"] = base
    env.pop("NIGHTY_INSTANT_MESHES", None)
    if instant_meshes:                 # a real, pinned build to test with (only run, never changed)
        env["NIGHTY_INSTANT_MESHES"] = instant_meshes
    return env


def run(blender, filters, instant_meshes=None):
    base = tempfile.mkdtemp(prefix="nighty-blender-tests-")
    try:
        argv = [blender, "-b", "--factory-startup", "--python", os.path.join(ROOT, "tests", "run.py")]
        if filters:
            argv += ["--"] + filters
        print(f"== {blender}\n   sandbox {base}", flush=True)
        return subprocess.call(argv, env=sandbox_env(base, instant_meshes), cwd=ROOT)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main():
    argv = sys.argv[1:]
    filters = []
    if "--" in argv:
        filters = argv[argv.index("--") + 1:]
        argv = argv[:argv.index("--")]
    ap = argparse.ArgumentParser()
    ap.add_argument("--blender", action="append")
    ap.add_argument("--instant-meshes", help="the pinned Instant Meshes program, for its real-build test")
    args = ap.parse_args(argv)
    blenders = args.blender or [b for b in DEFAULTS if os.path.isfile(b)]
    if not blenders:
        sys.exit("No Blender found: pass --blender PATH")
    codes = [run(b, filters, args.instant_meshes) for b in blenders]
    sys.exit(max(codes) if codes else 1)


if __name__ == "__main__":
    main()
