# SPDX-License-Identifier: GPL-3.0-or-later
# The io package's plain-Python tests (tests/io: looks, downloads, unpacking) inside Blender's own Python (3.11 on
# 4.2, 3.13 on 5.2), since that is where the add-on really runs them.

import os
import sys
import unittest

IO_TESTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "io")


def test_io_plain_tests_in_blender_python():
    if IO_TESTS not in sys.path:
        sys.path.insert(0, IO_TESTS)
    suite = unittest.defaultTestLoader.discover(IO_TESTS, pattern="test_*.py", top_level_dir=IO_TESTS)
    result = unittest.TextTestRunner(verbosity=0, stream=sys.stdout).run(suite)
    print(f"  io plain tests: {result.testsRun} run, {len(result.skipped)} skipped")
    problems = result.failures + result.errors
    assert not problems, "; ".join(str(t) for t, _ in problems)
