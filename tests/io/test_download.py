# SPDX-License-Identifier: GPL-3.0-or-later
# Downloads: resume after a cut (HTTP range), SHA-256 check, allowed hosts only (also after redirects), cancel,
# servers that ignore ranges. Against a local server, then against small real files on Hugging Face and GitHub.

import hashlib
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import _load

E = _load.io()
from nighty_io import download  # noqa: E402

BLOB = os.urandom(3 * 1024 * 1024 + 123)
BLOB_SHA = hashlib.sha256(BLOB).hexdigest()


class Server:
    def __init__(self):
        self.mode = "ok"
        self.cut_after = None      # bytes per response before the connection is dropped
        self.cuts_left = 0
        self.delay = 0.0           # seconds per 64 KB (a slow network)
        self.ranges = []
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.ranges.append(self.headers.get("Range"))
                if self.path == "/missing":
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path == "/redirect-bad":
                    self.send_response(302)
                    self.send_header("Location", "http://evil.example/x")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path == "/redirect-good":
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{outer.port}/file")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = BLOB if outer.mode != "wrong" else bytes(len(BLOB))
                start = 0
                rng = self.headers.get("Range")
                end = len(data) - 1
                if rng and outer.mode != "norange":
                    first, _, last = rng.split("=")[1].partition("-")
                    start = int(first)
                    end = int(last) if last else end
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                else:
                    self.send_response(200)
                body = data[start:end + 1]
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if outer.cut_after and outer.cuts_left > 0:
                    outer.cuts_left -= 1
                    self.wfile.write(body[:outer.cut_after])
                    self.wfile.flush()
                    self.close_connection = True
                    try:
                        self.connection.shutdown(2)
                    except OSError:
                        pass
                    return
                if outer.delay:
                    for k in range(0, len(body), 65536):
                        self.wfile.write(body[k:k + 65536])
                        time.sleep(outer.delay)
                    return
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, path="/file"):
        return f"http://127.0.0.1:{self.port}{path}"


def local_only(url):
    return url.startswith("http://127.0.0.1:")


class LocalDownloads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server()

    @classmethod
    def tearDownClass(cls):
        cls.server.httpd.shutdown()

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nighty-dl-")
        self.dest = os.path.join(self.dir, "sub", "file.bin")
        self.server.mode, self.server.cut_after, self.server.cuts_left = "ok", None, 0
        self.server.ranges.clear()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def fetch(self, url=None, **kw):
        kw.setdefault("sleep", lambda s: None)
        kw.setdefault("check", local_only)
        kw.setdefault("segments", 1)              # one connection here; ParallelDownloads covers segments
        return download.download(url or self.server.url(), self.dest, len(BLOB), BLOB_SHA, **kw)

    def test_plain(self):
        seen = []
        self.fetch(progress=lambda phase, d, t: seen.append((phase, d)))
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), BLOB)
        self.assertFalse(os.path.exists(self.dest + ".part"))
        self.assertEqual(seen[-1], ("download", len(BLOB)))
        # again: already here and right, nothing downloaded
        self.server.ranges.clear()
        self.fetch()
        self.assertEqual(self.server.ranges, [])

    def test_resume_after_cuts(self):
        self.server.cut_after, self.server.cuts_left = 700_000, 3
        self.fetch()
        with open(self.dest, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), BLOB_SHA)
        self.assertEqual(self.server.ranges[0], None)
        self.assertEqual(self.server.ranges[1], "bytes=700000-")
        self.assertEqual(self.server.ranges[2], "bytes=1400000-")
        self.assertEqual(len(self.server.ranges), 4)

    def test_resume_from_part_file(self):
        os.makedirs(os.path.dirname(self.dest))
        with open(self.dest + ".part", "wb") as f:
            f.write(BLOB[:1_000_000])
        phases = []
        self.fetch(progress=lambda phase, d, t: phases.append(phase))
        self.assertEqual(self.server.ranges, ["bytes=1000000-"])
        self.assertIn("check", phases)
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), BLOB)

    def test_part_file_too_big_or_server_ignores_range(self):
        os.makedirs(os.path.dirname(self.dest))
        with open(self.dest + ".part", "wb") as f:
            f.write(BLOB[:500_000])
        self.server.mode = "norange"
        self.fetch()
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), BLOB)
        with open(self.dest + ".part", "wb") as f:
            f.write(b"x" * (len(BLOB) + 10))
        os.remove(self.dest)
        self.server.mode = "ok"
        self.fetch()
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), BLOB)

    def test_hash_mismatch(self):
        self.server.mode = "wrong"
        with self.assertRaises(download.HashMismatch):
            self.fetch()
        self.assertFalse(os.path.exists(self.dest))
        self.assertFalse(os.path.exists(self.dest + ".part"), "a bad file is deleted")

    def test_wrong_size_on_server(self):
        with self.assertRaises(download.DownloadError) as cm:
            download.download(self.server.url(), self.dest, len(BLOB) + 5, BLOB_SHA, check=local_only,
                              sleep=lambda s: None, segments=1)
        self.assertIn("different size", str(cm.exception))

    def test_cancel_keeps_part(self):
        cancel = threading.Event()

        def progress(phase, done, total):
            if done > 1_000_000:
                cancel.set()
        with self.assertRaises(download.Cancelled):
            self.fetch(progress=progress, cancel=cancel, chunk=65536)
        self.assertTrue(os.path.getsize(self.dest + ".part") > 1_000_000)
        self.fetch()
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), BLOB)

    def test_hosts(self):
        with self.assertRaises(download.HostNotAllowed):
            download.download(self.server.url(), self.dest, 1, "0" * 64)       # http + 127.0.0.1: not allowed
        with self.assertRaises(download.HostNotAllowed):
            self.fetch(self.server.url("/redirect-bad"))
        self.fetch(self.server.url("/redirect-good"))
        self.assertTrue(download.host_allowed("https://huggingface.co/x"))
        self.assertTrue(download.host_allowed("https://us.aws.cdn.hf.co/x"))
        self.assertTrue(download.host_allowed("https://release-assets.githubusercontent.com/x"))
        self.assertFalse(download.host_allowed("http://huggingface.co/x"))
        self.assertFalse(download.host_allowed("https://huggingface.co.evil.com/x"))
        self.assertFalse(download.host_allowed("https://evilhuggingface.co/x"))
        self.assertFalse(download.host_allowed("file:///c:/x"))

    def test_404(self):
        with self.assertRaises(download.DownloadError) as cm:
            self.fetch(self.server.url("/missing"))
        self.assertIn("404", str(cm.exception))

    def test_speed_text(self):
        self.assertIn("MB/s", download.Speed.text(1e9, 5e9, 20e6))
        self.assertIn("min left", download.Speed.text(1e9, 5e9, 20e6))


class ParallelDownloads(unittest.TestCase):
    """Big files come over several connections (segments in dest.part, dest.part1 ...), resumable and checked."""

    @classmethod
    def setUpClass(cls):
        cls.server = Server()

    @classmethod
    def tearDownClass(cls):
        cls.server.httpd.shutdown()

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nighty-pdl-")
        self.dest = os.path.join(self.dir, "big.bin")
        self.server.mode, self.server.cut_after, self.server.cuts_left = "ok", None, 0
        self.server.delay = 0.0
        self.server.ranges.clear()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def fetch(self, **kw):
        kw.setdefault("sleep", lambda s: None)
        return download.download(self.server.url(), self.dest, len(BLOB), BLOB_SHA, check=local_only,
                                 segments=4, parallel_min=0, **kw)

    def leftovers(self):
        return sorted(n for n in os.listdir(self.dir) if n != "big.bin")

    def test_four_connections(self):
        seen = []
        self.fetch(progress=lambda p, d, t: seen.append(d))
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), BLOB)
        self.assertEqual(self.leftovers(), [], "segments, plan and .part are gone")
        ranges = sorted(self.server.ranges, key=lambda r: int(r.split("=")[1].split("-")[0]))
        self.assertEqual(len(ranges), 4)
        q = len(BLOB) // 4
        self.assertEqual(ranges[0], f"bytes=0-{q - 1}")
        self.assertTrue(ranges[-1].endswith(f"-{len(BLOB) - 1}"))
        self.assertEqual(seen[-1], len(BLOB))

    def test_cuts_on_every_connection(self):
        self.server.cut_after, self.server.cuts_left = 200_000, 8
        self.fetch()
        with open(self.dest, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), BLOB_SHA)
        self.assertGreater(len(self.server.ranges), 4, "cut connections came back with ranges")
        self.assertEqual(self.leftovers(), [])

    def test_carries_on_from_a_one_connection_part(self):
        prefix = 1_900_000
        with open(self.dest + ".part", "wb") as f:
            f.write(BLOB[:prefix])
        self.fetch()
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), BLOB)
        starts = [int(r.split("=")[1].split("-")[0]) for r in self.server.ranges]
        self.assertEqual(min(starts), prefix, "nothing before the old prefix was fetched again")
        self.assertEqual(len(starts), 3)

    def test_cancel_then_resume(self):
        cancel = threading.Event()
        self.server.delay = 0.1

        def progress(phase, done, total):
            if done > len(BLOB) // 3:
                cancel.set()
        with self.assertRaises(download.Cancelled):
            self.fetch(progress=progress, cancel=cancel, chunk=16384)
        self.assertIn("big.bin.part.json", self.leftovers())
        before = sum(os.path.getsize(os.path.join(self.dir, n)) for n in self.leftovers() if not n.endswith(".json"))
        self.server.ranges.clear()
        self.server.delay = 0.0
        self.fetch()
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), BLOB)
        self.assertGreater(before, 0)
        self.assertTrue(all(not r.startswith("bytes=0-") for r in self.server.ranges), "resumed, not restarted")
        self.assertEqual(self.leftovers(), [])

    def test_server_without_ranges(self):
        self.server.mode = "norange"
        self.fetch()
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), BLOB)
        self.assertEqual(self.leftovers(), [])

    def test_bad_data_deleted(self):
        self.server.mode = "wrong"
        with self.assertRaises(download.HashMismatch):
            self.fetch()
        self.assertEqual(self.leftovers(), [], "every segment of a bad file is deleted")
        self.assertFalse(os.path.exists(self.dest))


if __name__ == "__main__":
    unittest.main()
