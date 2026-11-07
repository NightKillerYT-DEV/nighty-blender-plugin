# SPDX-License-Identifier: GPL-3.0-or-later
# The addon's listener (protocol v2, docs/PROTOCOL.md): a small WebSocket server (RFC 6455) on 127.0.0.1 only, on the
# first free port of 47871-47873, for the Nighty Vault plugin. Pure stdlib, so Blender's own Python is enough.
#
# This file is only the wire. One thread accepts connections; each connection has a reader thread that checks the
# upgrade request, reads frames (text, ping, pong, close, fragments) and puts ("message", conn_id, dict) /
# ("open", conn_id, info) / ("close", conn_id, reason) on the inbox. It never touches bpy and knows nothing about
# pairing: session.py does that on Blender's main thread and answers with send(conn_id, dict).
#
# Refused at the door (HTTP 403 / 400, then closed): a request that isn't a WebSocket upgrade, one without the
# nighty-blender.v2 subprotocol, a Host that isn't 127.0.0.1 / localhost (DNS rebinding), and any Origin header
# except "null" (web pages always send their own origin; the plugin's worker sends "null" or none). Messages over
# 16 MB, unmasked client frames and binary messages close the connection.

import base64
import hashlib
import json
import os
import queue
import socket
import struct
import threading
import time

DEFAULT_PORTS = (47871, 47872, 47873)
SUBPROTOCOL = "nighty-blender.v2"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MESSAGE = 16 * 1024 * 1024
MAX_CONNECTIONS = 4
HANDSHAKE_SECONDS = 5.0

OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


def ports_from_env(env=None):
    """The port range, from NIGHTY_BLENDER_PORTS if set (tests: "0" = any free port), else 47871-47873."""
    raw = (env if env is not None else os.environ).get("NIGHTY_BLENDER_PORTS", "")
    got = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit() and 0 <= int(part) <= 65535:
            got.append(int(part))
    return tuple(got) or DEFAULT_PORTS


class HandshakeError(Exception):
    def __init__(self, status, why):
        super().__init__(why)
        self.status = status


def accept_key(key):
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode("ascii")).digest()).decode("ascii")


def check_upgrade(head, port):
    """Parses and checks an upgrade request. Returns (headers, the answer's bytes). Raises HandshakeError."""
    text = head.decode("latin-1")
    lines = text.split("\r\n")
    request = lines[0].split(" ")
    if len(request) < 3 or request[0] != "GET":
        raise HandshakeError(400, "not a GET request")
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
    if "websocket" not in headers.get("upgrade", "").lower() or \
            "upgrade" not in headers.get("connection", "").lower():
        raise HandshakeError(400, "not a WebSocket upgrade")
    if headers.get("sec-websocket-version") != "13" or not headers.get("sec-websocket-key"):
        raise HandshakeError(400, "bad WebSocket version or key")
    host = headers.get("host", "").lower()
    if host not in ("127.0.0.1:%d" % port, "localhost:%d" % port, "127.0.0.1", "localhost"):
        raise HandshakeError(403, "wrong Host")
    origin = headers.get("origin")
    if origin is not None and origin.strip().lower() != "null":
        raise HandshakeError(403, "a web page (Origin %s)" % origin[:80])
    protos = [p.strip() for p in headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
    if SUBPROTOCOL not in protos:
        raise HandshakeError(403, "not the %s subprotocol" % SUBPROTOCOL)
    answer = ("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
              "Sec-WebSocket-Accept: %s\r\nSec-WebSocket-Protocol: %s\r\n\r\n"
              % (accept_key(headers["sec-websocket-key"]), SUBPROTOCOL))
    return headers, answer.encode("ascii")


def encode_frame(opcode, payload, mask=False):
    """One frame (FIN set). Server frames are unmasked; mask=True makes a client frame (tests)."""
    length = len(payload)
    head = bytearray([0x80 | opcode])
    bit = 0x80 if mask else 0
    if length < 126:
        head.append(bit | length)
    elif length < 65536:
        head.append(bit | 126)
        head += struct.pack("!H", length)
    else:
        head.append(bit | 127)
        head += struct.pack("!Q", length)
    if mask:
        key = os.urandom(4)
        head += key
        payload = _xor(payload, key)
    return bytes(head) + payload


def _xor(data, key):
    if not data:
        return b""
    # fast unmask: XOR against the 4-byte key repeated, as big integers
    n = len(data)
    pad = (key * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "little") ^ int.from_bytes(pad, "little")).to_bytes(n, "little")


def _linger_close(sock, seconds):
    try:
        sock.shutdown(socket.SHUT_WR)
    except OSError:
        pass

    def finish():
        try:
            sock.close()
        except OSError:
            pass
    timer = threading.Timer(seconds, finish)
    timer.daemon = True
    timer.start()


class Conn:
    __slots__ = ("id", "sock", "addr", "lock", "buf", "alive", "opened")

    def __init__(self, conn_id, sock, addr):
        self.id, self.sock, self.addr = conn_id, sock, addr
        self.lock = threading.Lock()
        self.buf = bytearray()
        self.alive = True
        self.opened = time.monotonic()


class Server:
    def __init__(self, ports=None, log=None):
        self.ports = tuple(ports) if ports else ports_from_env()
        self.log = log or (lambda *_: None)
        self.inbox = queue.Queue()
        self.port = None
        self.error = None
        self._srv = None
        self._thread = None
        self._stop = threading.Event()
        self._conns = {}
        self._seq = 0
        self._lock = threading.Lock()

    @property
    def running(self):
        return self._srv is not None

    # ---------- start / stop ----------

    def start(self):
        """Listens on the first free port of the range. Returns the port, or None (self.error says why)."""
        if self._srv is not None:
            return self.port
        self._stop.clear()
        last = None
        for port in self.ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if os.name == "nt":
                # never share a port with another program (Windows' SO_REUSEADDR would allow a hijack)
                sock.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", -5), 1)
            try:
                sock.bind(("127.0.0.1", port))
                sock.listen(8)
            except OSError as exc:
                last = exc
                sock.close()
                continue
            sock.settimeout(0.3)
            self._srv = sock
            self.port = sock.getsockname()[1]
            self.error = None
            self._thread = threading.Thread(target=self._accept_loop, name="nighty-blender-server", daemon=True)
            self._thread.start()
            self.log("listening on 127.0.0.1:%d" % self.port)
            return self.port
        self.error = "ports %s are taken (%s)" % (", ".join(str(p) for p in self.ports), last)
        return None

    def stop(self):
        self._stop.set()
        srv, self._srv = self._srv, None
        if srv is not None:
            try:
                srv.close()
            except OSError:
                pass
        for conn in list(self._conns.values()):
            self.close(conn.id, 1001, "going away")
        thread, self._thread = self._thread, None
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self.port = None

    # ---------- sending (any thread) ----------

    def send(self, conn_id, obj):
        conn = self._conns.get(conn_id)
        if conn is None or not conn.alive:
            return False
        try:
            data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError):
            return False
        if len(data) > MAX_MESSAGE:
            return False
        return self._write(conn, encode_frame(OP_TEXT, data))

    def close(self, conn_id, code=1000, reason="bye", linger=1.0):
        """Sends a close frame and stops writing; the socket itself closes a moment later (closing at once with
        unread data makes Windows reset the connection, and the other side would lose our last messages)."""
        conn = self._conns.pop(conn_id, None)
        if conn is None:
            return
        if conn.alive:
            conn.alive = False
            try:
                self._write(conn, encode_frame(OP_CLOSE, struct.pack("!H", code) + reason.encode("utf-8")[:100]),
                            force=True)
            except OSError:
                pass
        _linger_close(conn.sock, linger)

    def connections(self):
        return list(self._conns)

    def _write(self, conn, data, force=False):
        if not conn.alive and not force:
            return False
        with conn.lock:
            try:
                conn.sock.sendall(data)
                return True
            except OSError:
                conn.alive = False
                return False

    # ---------- threads ----------

    def _accept_loop(self):
        while not self._stop.is_set():
            srv = self._srv
            if srv is None:
                break
            try:
                sock, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if addr[0] != "127.0.0.1" or len(self._conns) >= MAX_CONNECTIONS:
                try:
                    sock.close()
                except OSError:
                    pass
                continue
            with self._lock:
                self._seq += 1
                conn = Conn("c%d" % self._seq, sock, addr)
            threading.Thread(target=self._serve, args=(conn,), name="nighty-blender-conn", daemon=True).start()

    def _serve(self, conn):
        sock = conn.sock
        try:
            sock.settimeout(HANDSHAKE_SECONDS)
            head = self._read_head(conn)
            try:
                headers, answer = check_upgrade(head, self.port or 0)
            except HandshakeError as err:
                body = str(err).encode("utf-8")
                reason = "Forbidden" if err.status == 403 else "Bad Request"
                sock.sendall(b"HTTP/1.1 %d %s\r\nContent-Type: text/plain\r\nContent-Length: %d\r\n"
                             b"Connection: close\r\n\r\n%s" % (err.status, reason.encode(), len(body), body))
                self.log("refused a connection:", err)
                _linger_close(sock, 1.0)
                return
            sock.sendall(answer)
            sock.settimeout(None)
            self._conns[conn.id] = conn
            self.inbox.put(("open", conn.id, {"origin": headers.get("origin")}))
            reason = self._read_loop(conn)
        except (OSError, ValueError) as exc:
            reason = str(exc)
        if conn.id in self._conns:
            self.close(conn.id, 1002 if reason not in ("closed", "bye") else 1000, "bye")
        self.inbox.put(("close", conn.id, reason))

    def _read_head(self, conn):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.sock.recv(4096)
            if not chunk:
                raise OSError("closed during handshake")
            data += chunk
            if len(data) > 16384:
                raise OSError("handshake too long")
        head, _, rest = data.partition(b"\r\n\r\n")
        conn.buf = bytearray(rest)
        return head

    def _read_loop(self, conn):
        frags, frag_op, total = [], None, 0
        while conn.alive and not self._stop.is_set():
            frame = self._read_frame(conn)
            if frame is None:
                return "closed"
            fin, opcode, payload = frame
            if opcode == OP_PING:
                self._write(conn, encode_frame(OP_PONG, payload[:125]))
            elif opcode == OP_PONG:
                pass
            elif opcode == OP_CLOSE:
                return "bye"
            elif opcode in (OP_TEXT, OP_BIN, OP_CONT):
                if opcode == OP_CONT:
                    if frag_op is None:
                        return "stray continuation"
                else:
                    if frag_op is not None:
                        return "new message while fragmenting"
                    frag_op = opcode
                frags.append(payload)
                total += len(payload)
                if total > MAX_MESSAGE:
                    return "message over 16 MB"
                if fin:
                    whole, op = b"".join(frags), frag_op
                    frags, frag_op, total = [], None, 0
                    if op != OP_TEXT:
                        return "binary messages are not used"
                    try:
                        message = json.loads(whole.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        return "not JSON"
                    if isinstance(message, dict) and isinstance(message.get("type"), str):
                        self.inbox.put(("message", conn.id, message))
            else:
                return "unknown opcode"
        return "closed"

    def _read_frame(self, conn):
        head = self._recv(conn, 2)
        if head is None:
            return None
        fin, opcode = bool(head[0] & 0x80), head[0] & 0x0F
        masked, length = bool(head[1] & 0x80), head[1] & 0x7F
        if not masked:
            raise ValueError("unmasked client frame")
        if length == 126:
            ext = self._recv(conn, 2)
            if ext is None:
                return None
            length = struct.unpack("!H", ext)[0]
        elif length == 127:
            ext = self._recv(conn, 8)
            if ext is None:
                return None
            length = struct.unpack("!Q", ext)[0]
        if length > MAX_MESSAGE:
            raise ValueError("frame over 16 MB")
        key = self._recv(conn, 4)
        payload = self._recv(conn, length) if length else b""
        if key is None or payload is None:
            return None
        return fin, opcode, _xor(payload, key)

    def _recv(self, conn, n):
        while len(conn.buf) < n:
            try:
                chunk = conn.sock.recv(max(65536, n - len(conn.buf)))
            except OSError:
                return None
            if not chunk:
                return None
            conn.buf += chunk
        out = bytes(conn.buf[:n])
        del conn.buf[:n]
        return out
