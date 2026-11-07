# SPDX-License-Identifier: GPL-3.0-or-later
# Unpacking a .7z with LZMA2 + BCJ2 (the hardest common 7z filters) with the unpacker Windows ships
# (tar.exe = libarchive) or 7-Zip. The archive is libarchive's own test file test_read_format_7zip_bcj2_lzma2_2.7z
# (BSD-2-Clause, test data only).

import hashlib
import os
import shutil
import tempfile
import threading
import unittest

import _load

E = _load.io()
from nighty_io import unpack  # noqa: E402
from nighty_io.download import Cancelled  # noqa: E402

ARCHIVE = _load.FIXTURE


@unittest.skipUnless(unpack.find_tools(), "no tar.exe / 7-Zip here")
class Unpack(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nighty-unpack-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_bcj2_lzma2(self):
        target = os.path.join(self.dir, "runtime", "tool-test")
        seen = []
        out = unpack.unpack_7z(ARCHIVE, target, check_files=("x86exe",), progress=lambda d, e: seen.append(d),
                               expected_entries=1)
        self.assertEqual(out, target)
        path = os.path.join(target, "x86exe")
        self.assertEqual(os.path.getsize(path), 27328)
        with open(path, "rb") as f:
            self.assertEqual(f.read(4), b"\x7fELF", "the x86 program came out whole (BCJ2 decoded, CRC checked)")
        self.assertFalse([n for n in os.listdir(os.path.dirname(target)) if n.startswith(".unpack-")],
                         "no temporary folder left")
        # unpacking again replaces the old copy
        unpack.unpack_7z(ARCHIVE, target, check_files=("x86exe",))
        self.assertTrue(os.path.isfile(path))

    def test_missing_file_after_unpack(self):
        target = os.path.join(self.dir, "rt")
        with self.assertRaises(unpack.UnpackError) as cm:
            unpack.unpack_7z(ARCHIVE, target, check_files=("python_embeded/python.exe",))
        self.assertIn("missing", str(cm.exception))
        self.assertFalse(os.path.exists(target))

    def test_broken_archive(self):
        bad = os.path.join(self.dir, "bad.7z")
        with open(ARCHIVE, "rb") as f:
            data = bytearray(f.read())
        data[200:400] = bytes(200)
        with open(bad, "wb") as f:
            f.write(data)
        with self.assertRaises(unpack.UnpackError):
            unpack.unpack_7z(bad, os.path.join(self.dir, "rt"), check_files=("x86exe",))

    def test_no_tools(self):
        with self.assertRaises(unpack.UnpackError) as cm:
            unpack.unpack_7z(ARCHIVE, os.path.join(self.dir, "rt"), tools=[])
        self.assertIn("7-Zip", str(cm.exception))

    def test_cancel(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            unpack.unpack_7z(ARCHIVE, os.path.join(self.dir, "rt"), cancel=cancel)


if __name__ == "__main__":
    unittest.main()
