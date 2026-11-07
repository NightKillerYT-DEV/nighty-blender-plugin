# SPDX-License-Identifier: GPL-3.0-or-later
# Resumable downloads of pinned files (a tool such as Instant Meshes): HTTP range requests continue a cut download
# from the `.part` file, progress goes to a callback, and the file is only kept when its SHA-256 matches the pinned
# one. Only https addresses on the allowed hosts are fetched, also after redirects.
# No cookies, no tokens, no telemetry: one plain GET per try.

import hashlib
import http.client
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import IO_VERSION

ALLOWED_HOSTS = ("huggingface.co", "hf.co", "github.com", "githubusercontent.com")
USER_AGENT = f"NightyBlender/{IO_VERSION}"
CHUNK = 1 << 20
SEGMENTS = 4                 # connections per big file
PARALLEL_MIN = 64 << 20      # files from this size up come in segments


class DownloadError(Exception):
    """A download that can't finish (the message says why, in plain words)."""


class HashMismatch(DownloadError):
    pass


class HostNotAllowed(DownloadError):
    pass


class Cancelled(Exception):
    pass


class _NoRanges(Exception):
    """The server ignores range requests: download over one connection instead."""


def host_allowed(url, hosts=ALLOWED_HOSTS):
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return False
    return any(host == h or host.endswith("." + h) for h in hosts)


class _GuardedRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, check):
        super().__init__()
        self.check = check

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self.check(newurl):
            raise HostNotAllowed(f"refused a redirect to {urllib.parse.urlsplit(newurl).hostname}")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.remove_header("Authorization")
            new.remove_header("Cookie")
        return new


def make_opener(check=None):
    check = check or host_allowed
    # build_opener keeps the system's proxy settings, so people behind a proxy still download.
    return urllib.request.build_opener(_GuardedRedirects(check))


def sha256_file(path, progress=None, cancel=None):
    h = hashlib.sha256()
    done = 0
    total = os.path.getsize(path)
    with open(path, "rb") as f:
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            buf = f.read(CHUNK * 4)
            if not buf:
                break
            h.update(buf)
            done += len(buf)
            if progress:
                progress(done, total)
    return h.hexdigest()


_RANGE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)")


def _transient(err):
    if isinstance(err, urllib.error.HTTPError):
        return err.code in (408, 425, 429) or err.code >= 500
    return isinstance(err, (urllib.error.URLError, OSError, http.client.HTTPException, socket.timeout))


def download(url, dest, size, sha256, progress=None, cancel=None, retries=6, check=None, opener=None,
             timeout=30, sleep=time.sleep, chunk=CHUNK, trust_existing=False, segments=SEGMENTS,
             parallel_min=PARALLEL_MIN):
    """Downloads `url` to `dest` (resuming its .part files), checks size and SHA-256, returns dest.
    Big files come over `segments` connections at once (one connection to a CDN is often slow); small ones, or a
    server without range support, over one. progress(phase, done, total): phase is "check" (hashing what is
    already here) or "download". cancel: a threading.Event; the .part files stay for the next try."""
    check = check or host_allowed
    if not check(url):
        raise HostNotAllowed(f"not an allowed download address: {url}")
    opener = opener or make_opener(check)
    report = progress or (lambda phase, done, total: None)
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    if os.path.isfile(dest) and os.path.getsize(dest) == size:
        if trust_existing or sha256_file(dest, lambda d, t: report("check", d, t), cancel) == sha256:
            report("download", size, size)
            return dest
    if segments > 1 and size >= max(parallel_min, segments):
        try:
            return _download_parallel(url, dest, size, sha256, report, cancel, retries, opener, timeout, sleep,
                                      chunk, segments)
        except _NoRanges:
            _drop_segments(dest)             # this server sends whole files only: one connection, from the start
    return _download_single(url, dest, size, sha256, report, cancel, retries, opener, timeout, sleep, chunk)


def _download_single(url, dest, size, sha256, report, cancel, retries, opener, timeout, sleep, chunk):
    part = dest + ".part"
    h = hashlib.sha256()
    done = 0
    if os.path.isfile(part):
        have = os.path.getsize(part)
        if have > size:
            os.remove(part)
        else:
            with open(part, "rb") as f:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    buf = f.read(CHUNK * 4)
                    if not buf:
                        break
                    h.update(buf)
                    done += len(buf)
                    report("check", done, have)
    failures = 0
    while done < size:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        if done:
            headers["Range"] = f"bytes={done}-"
        start = done
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:
                status = getattr(resp, "status", 200)
                if done and status == 206:
                    m = _RANGE.match(resp.headers.get("Content-Range") or "")
                    if not m or int(m.group(1)) != done or (m.group(3) != "*" and int(m.group(3)) != size):
                        raise DownloadError("the server sent a different part of the file; starting over")
                elif status == 200:
                    if done:                     # the server ignored the range: start from zero
                        h, done, start = hashlib.sha256(), 0, 0
                    length = resp.headers.get("Content-Length")
                    if length is not None and int(length) != size:
                        raise DownloadError(f"the file on the server has a different size ({length} bytes, "
                                            f"expected {size}): it changed, so it was not downloaded")
                else:
                    raise DownloadError(f"unexpected answer {status} from the server")
                with open(part, "ab" if done else "wb") as f:
                    while True:
                        if cancel is not None and cancel.is_set():
                            raise Cancelled()
                        buf = resp.read(chunk)
                        if not buf:
                            break
                        if done + len(buf) > size:
                            raise DownloadError("the server sent more data than expected")
                        f.write(buf)
                        h.update(buf)
                        done += len(buf)
                        report("download", done, size)
            if done < size:
                raise ConnectionError("the connection ended early")
        except (Cancelled, HostNotAllowed):
            raise
        except DownloadError as err:
            if "starting over" in str(err):
                try:
                    os.remove(part)
                except OSError:
                    pass
                h, done = hashlib.sha256(), 0
                failures += 1
                if failures > retries:
                    raise
                continue
            raise
        except Exception as err:  # noqa: BLE001 - network errors come in many types
            if isinstance(err, urllib.error.HTTPError) and not _transient(err):
                if err.code == 416:
                    try:
                        os.remove(part)
                    except OSError:
                        pass
                    h, done = hashlib.sha256(), 0
                    failures += 1
                    if failures > retries:
                        raise DownloadError("the server refused to continue the download") from err
                    continue
                if err.code in (401, 403):
                    raise DownloadError(f"the server refused the download ({err.code}): the file may have become "
                                        "private or gated") from err
                if err.code == 404:
                    raise DownloadError("the file is gone from the server (404); Nighty Blender needs an update") \
                        from err
                raise DownloadError(f"download failed ({err.code} {err.reason})") from err
            if not _transient(err) and not isinstance(err, (ConnectionError, ValueError)):
                raise
            if done > start:
                failures = 0          # it moved forward: a cut, not a dead server
            failures += 1
            if failures > retries:
                raise DownloadError(f"the download keeps failing ({err}); it continues from "
                                    f"{done / 1e9:.2f} GB next time") from err
            wait = min(30.0, 2.0 ** failures)
            end = time.monotonic() + wait
            while time.monotonic() < end:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                sleep(min(0.25, wait))
    if h.hexdigest() != sha256:
        try:
            os.remove(part)
        except OSError:
            pass
        raise HashMismatch("the downloaded file's SHA-256 doesn't match; it was deleted (try again)")
    os.replace(part, dest)
    return dest


def _segment_paths(dest, n):
    return [dest + ".part"] + [f"{dest}.part{i}" for i in range(1, n)]


def _drop_segments(dest):
    """Removes segment files 1..n and the plan (segment 0 = dest.part stays: it is a valid prefix)."""
    folder, base = os.path.split(os.path.abspath(dest))
    for name in os.listdir(folder):
        tail = name[len(base):] if name.startswith(base) else ""
        if tail == ".part.json" or (tail.startswith(".part") and tail[5:].isdigit()):
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _plan_segments(dest, size, sha256, n):
    """The byte ranges, kept in dest.part.json so a resumed download uses the same ones. Segment 0 is dest.part,
    so a cut one-connection download (a plain prefix) carries on as segment 0."""
    plan_path = dest + ".part.json"
    try:
        with open(plan_path, encoding="utf-8") as f:
            plan = json.load(f)
        if plan.get("size") == size and plan.get("sha256") == sha256 and plan.get("bounds"):
            return [tuple(b) for b in plan["bounds"]]
    except (OSError, ValueError):
        pass
    _drop_segments(dest)
    first = min(max(_size(dest + ".part"), size // n), size)
    rest = size - first
    k = n - 1 if rest > 0 else 0
    bounds = [(0, first)] + [(first + rest * i // k, first + rest * (i + 1) // k) for i in range(k)]
    bounds = [b for b in bounds if b[1] > b[0]]
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump({"size": size, "sha256": sha256, "bounds": bounds}, f)
    return bounds


def _download_parallel(url, dest, size, sha256, report, cancel, retries, opener, timeout, sleep, chunk, n):
    bounds = _plan_segments(dest, size, sha256, n)
    paths = _segment_paths(dest, len(bounds))
    for path, (a, b) in zip(paths, bounds):
        if _size(path) > b - a:                     # longer than its range: something is off, fetch it again
            os.remove(path)
    # segment 0 is hashed as it grows (first what is already here), the others at the end, in order
    h = hashlib.sha256()
    have0 = _size(paths[0])
    if have0:
        hashed = 0
        with open(paths[0], "rb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                buf = f.read(CHUNK * 4)
                if not buf:
                    break
                h.update(buf)
                hashed += len(buf)
                report("check", hashed, have0)
    done = [_size(p) for p in paths]
    lock = threading.Lock()
    stop = threading.Event()
    errors = []

    def worker(i):
        a, b = bounds[i]
        failures = 0
        while done[i] < b - a and not stop.is_set():
            start = done[i]
            headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity",
                       "Range": f"bytes={a + start}-{b - 1}"}
            try:
                with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:
                    status = getattr(resp, "status", 200)
                    if status == 200:
                        raise _NoRanges()
                    m = _RANGE.match(resp.headers.get("Content-Range") or "")
                    if status != 206 or not m or int(m.group(1)) != a + start or (
                            m.group(3) != "*" and int(m.group(3)) != size):
                        raise DownloadError("the server sent a different part of the file")
                    with open(paths[i], "ab") as f:
                        while not stop.is_set() and done[i] < b - a:
                            buf = resp.read(min(chunk, b - a - done[i]))
                            if not buf:
                                break
                            f.write(buf)
                            if i == 0:
                                h.update(buf)
                            with lock:
                                done[i] += len(buf)
                if done[i] < b - a and not stop.is_set():
                    raise ConnectionError("the connection ended early")
            except (_NoRanges, DownloadError) as err:
                errors.append(err)
                stop.set()
                return
            except Exception as err:  # noqa: BLE001 - network errors come in many types
                if isinstance(err, HostNotAllowed) or (isinstance(err, urllib.error.HTTPError)
                                                      and not _transient(err)):
                    errors.append(_http_error(err) if isinstance(err, urllib.error.HTTPError) else err)
                    stop.set()
                    return
                if not _transient(err) and not isinstance(err, (ConnectionError, ValueError)):
                    errors.append(err)
                    stop.set()
                    return
                if done[i] > start:
                    failures = 0                    # it moved forward: a cut, not a dead server
                failures += 1
                if failures > retries:
                    errors.append(DownloadError(f"the download keeps failing ({err}); it continues from here "
                                                "next time"))
                    stop.set()
                    return
                end = time.monotonic() + min(30.0, 2.0 ** failures)
                while time.monotonic() < end and not stop.is_set():
                    sleep(0.25)

    threads = [threading.Thread(target=worker, args=(i,), daemon=True, name=f"nighty-dl-{i}")
               for i in range(len(bounds)) if done[i] < bounds[i][1] - bounds[i][0]]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        if cancel is not None and cancel.is_set():
            stop.set()
            for t in threads:
                t.join(timeout=30)
            raise Cancelled()
        with lock:
            total = sum(done)
        report("download", total, size)
        time.sleep(0.25)
    if errors:
        raise errors[0]
    report("download", size, size)
    with open(paths[0], "ab") as out:             # the rest, in order: hashed while appended to segment 0
        for path in paths[1:]:
            with open(path, "rb") as f:
                while True:
                    buf = f.read(CHUNK * 8)
                    if not buf:
                        break
                    h.update(buf)
                    out.write(buf)
    for path in paths[1:]:
        os.remove(path)
    try:
        os.remove(dest + ".part.json")
    except OSError:
        pass
    if h.hexdigest() != sha256 or _size(paths[0]) != size:
        os.remove(paths[0])
        raise HashMismatch("the downloaded file's SHA-256 doesn't match; it was deleted (try again)")
    os.replace(paths[0], dest)
    return dest


def _http_error(err):
    if err.code in (401, 403):
        return DownloadError(f"the server refused the download ({err.code}): the file may have become private or "
                             "gated")
    if err.code == 404:
        return DownloadError("the file is gone from the server (404); Nighty Blender needs an update")
    if err.code == 416:
        return DownloadError("the server refused that part of the file (416)")
    return DownloadError(f"download failed ({err.code} {err.reason})")


class Speed:
    """Smoothed speed and time left for progress lines."""

    def __init__(self):
        self.t0 = time.monotonic()
        self.last = None
        self.rate = 0.0

    def update(self, done):
        now = time.monotonic()
        if self.last is None:            # the first reading may include bytes from before a resume
            self.last = (now, done)
            return self.rate
        t, d = self.last
        if now - t >= 0.5:
            inst = (done - d) / (now - t)
            self.rate = inst if not self.rate else self.rate * 0.7 + inst * 0.3
            self.last = (now, done)
        return self.rate

    @staticmethod
    def text(done, total, rate):
        left = (total - done) / rate if rate > 0 else None
        eta = ""
        if left is not None:
            eta = f", {int(left // 60)} min left" if left >= 90 else f", {int(left)} s left"
        return f"{done / 1e9:.2f} of {total / 1e9:.2f} GB ({rate / 1e6:.1f} MB/s{eta})"
