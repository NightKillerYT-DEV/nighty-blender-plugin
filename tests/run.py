# SPDX-License-Identifier: GPL-3.0-or-later
# Run every tests/test_*.py inside Blender and exit non-zero if anything fails. Use the sandboxed launcher, which
# points Blender's user folders and Nighty Blender's state at a temporary folder:
#
#     python scripts/run_tests.py [-- name_filter ...]
#
# (It runs  blender -b --factory-startup --python tests/run.py [-- name_filter ...]  with that environment; this file
# refuses to run without it, so a test can never write into the person's own Blender settings.)
#
# Each test file holds plain functions named test_*(); a function passes if it returns without raising. A file that
# sets FRESH_SCENE = True gets an empty factory scene before each of its tests (the modeling tests count objects).
# Filters (after --) run only tests whose "file.function" name contains one of them. Run it on BOTH test Blenders
# (4.2 and 5.2). The tests never touch the live ports 47871-47873: the server binds a free OS-chosen port and the
# test client is pointed straight at it. The io package's plain tests (tests/io) run inside test_io_pure.

import importlib
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ADDON_DIR = os.path.join(ROOT, "addon")


def fresh_scene():
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    nighty = sys.modules.get("nighty_blender.nighty")
    if nighty is not None:
        nighty.core._S.update({"detail": "medium", "size": 1.0, "collection": None})


def main(filters):
    import signal
    if hasattr(signal, "SIGPIPE"):   # Linux/macOS: a test server writing to a closed socket must not kill Blender
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    for path in (HERE, ADDON_DIR):
        if path not in sys.path:
            sys.path.insert(0, path)
    import bpy
    sandbox = os.environ.get("NIGHTY_TEST_SANDBOX")
    user = bpy.utils.user_resource("DATAFILES")

    def inside(path):
        return bool(sandbox) and os.path.normcase(os.path.abspath(path)).startswith(
            os.path.normcase(os.path.abspath(sandbox)))
    if not inside(user) or not inside(os.environ.get("NIGHTY_BLENDER_STATE_DIR", "")):
        print("Refusing to run: start the tests with  python scripts/run_tests.py  (a sandbox for Blender's user "
              "folders and Nighty Blender's state), never against this computer's own settings.")
        sys.stdout.flush()
        sys.exit(2)
    import nighty_blender
    nighty_blender.load_tools()
    nighty_blender.nighty_alias()

    files = sorted(f for f in os.listdir(HERE) if f.startswith("test_") and f.endswith(".py"))
    passed = failed = 0
    fails = []
    start = time.time()
    for fname in files:
        mod_name = fname[:-3]
        try:
            module = importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            fails.append((mod_name, exc))
            print("  FAIL %s (import): %s" % (mod_name, exc))
            traceback.print_exc()
            continue
        fresh = getattr(module, "FRESH_SCENE", False)
        tests = [getattr(module, n) for n in sorted(dir(module))
                 if n.startswith("test_") and callable(getattr(module, n))]
        for fn in tests:
            name = "%s.%s" % (mod_name, fn.__name__)
            if filters and not any(f in name for f in filters):
                continue
            if fresh:
                fresh_scene()
            t = time.time()
            try:
                fn()
                passed += 1
                print("  ok   %s (%.2fs)" % (name, time.time() - t))
            except Exception as exc:  # noqa: BLE001
                failed += 1
                fails.append((name, exc))
                print("  FAIL %s: %s" % (name, exc))
                traceback.print_exc()

    print("\nNighty Blender tests on Blender %s: %d passed, %d failed (%.0f s)."
          % (bpy.app.version_string, passed, failed, time.time() - start))
    if fails:
        print("Failures:")
        for name, exc in fails:
            print("  - %s: %s" % (name, exc))
    sys.stdout.flush()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
