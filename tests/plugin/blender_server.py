# SPDX-License-Identifier: GPL-3.0-or-later
# The Blender side of tests/plugin/e2e.mjs: a headless Blender with the add-on's real listener on a free port. It plays
# the person too: when Nighty Vault asks to pair, it types the code the test wrote into NB_CODE_FILE. It stops when
# NB_DONE_FILE appears (or after 5 minutes). Run by the test in a sandbox (BLENDER_USER_RESOURCES,
# NIGHTY_BLENDER_STATE_DIR in a temp folder).

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "addon"))

import nighty_blender  # noqa: E402
from nighty_blender import runtime  # noqa: E402
from nighty_blender.session import Session  # noqa: E402

nighty_blender.load_tools()
session = Session(ports=[0])
session.forget()
session.level = os.environ.get("NB_LEVEL", "safe")
runtime.set_session(session)
port = session.start()
print("PORT %d" % port, flush=True)
code_file = os.environ["NB_CODE_FILE"]
done_file = os.environ["NB_DONE_FILE"]
end = time.monotonic() + 300
while time.monotonic() < end and not os.path.exists(done_file):
    session.tick()
    if session.status == "code" and os.path.exists(code_file):
        with open(code_file, encoding="utf-8") as f:
            typed = f.read().strip()
        os.remove(code_file)
        print("TYPED %s -> %s" % (typed, session.enter_code(typed)), flush=True)
    time.sleep(0.005)
session.stop()
session.forget()
print("BYE", flush=True)
