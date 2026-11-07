# SPDX-License-Identifier: GPL-3.0-or-later
# The tests' stand-in for the Nighty Vault plugin: a stdlib WebSocket client that speaks protocol v2 exactly like
# plugin/main.js (hello, Blender's proof checked first, auth with the token, or pair_request -> the person's code ->
# pair_proof checked -> pair_confirm -> the sealed token), plus helpers that pump the add-on's main-thread tick by
# hand (background Blender does not run app timers during a script). Not a test file itself.

import base64
import hashlib
import json
import os
import socket
import struct
import time

from nighty_blender import pairing as P
from nighty_blender.server import SUBPROTOCOL, WS_GUID, encode_frame

OP_TEXT, OP_CLOSE, OP_PING, OP_PONG = 0x1, 0x8, 0x9, 0xA


class FakeServerDetected(Exception):
    """The listener could not prove it knows the token / code: not the real Nighty Blender."""


class HandshakeRefused(Exception):
    def __init__(self, status_line):
        super().__init__(status_line)
        self.status_line = status_line


def pump(session, pred, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        session.tick()
        if pred():
            return True
        time.sleep(0.005)
    session.tick()
    return bool(pred())


class Client:
    def __init__(self, port, *, origin=None, protocols=(SUBPROTOCOL,), host=None, name="Test plugin"):
        self.port = port
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5.0)
        self.buf = b""
        self.inbox = []
        self.closed = False
        self.name = name
        key = base64.b64encode(os.urandom(16)).decode()
        lines = ["GET / HTTP/1.1", "Host: %s" % (host or "127.0.0.1:%d" % port), "Upgrade: websocket",
                 "Connection: Upgrade", "Sec-WebSocket-Key: " + key, "Sec-WebSocket-Version: 13"]
        if protocols:
            lines.append("Sec-WebSocket-Protocol: " + ", ".join(protocols))
        if origin is not None:
            lines.append("Origin: " + origin)
        self.sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise HandshakeRefused("closed")
            head += chunk
        head, _, self.buf = head.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0].decode()
        if " 101 " not in status + " ":
            self.sock.close()
            raise HandshakeRefused(status)
        want = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        if want.encode() not in head:
            raise HandshakeRefused("bad accept key")
        self.sock.settimeout(0.02)
        self.nonce = P.new_nonce()
        self.server_nonce = None
        self.token = None
        self.hello = None

    # ---------- frames ----------

    def send(self, obj):
        self.sock.sendall(encode_frame(OP_TEXT, json.dumps(obj).encode(), mask=True))

    def send_raw(self, data):
        self.sock.sendall(data)

    def _read(self):
        try:
            chunk = self.sock.recv(1 << 20)
        except socket.timeout:
            return
        except OSError:
            self.closed = True
            return
        if not chunk:
            self.closed = True
            return
        self.buf += chunk
        while True:
            if len(self.buf) < 2:
                return
            b0, b1 = self.buf[0], self.buf[1]
            n, pos = b1 & 0x7F, 2
            if n == 126:
                if len(self.buf) < 4:
                    return
                n, pos = struct.unpack("!H", self.buf[2:4])[0], 4
            elif n == 127:
                if len(self.buf) < 10:
                    return
                n, pos = struct.unpack("!Q", self.buf[2:10])[0], 10
            if len(self.buf) < pos + n:
                return
            payload, self.buf = self.buf[pos:pos + n], self.buf[pos + n:]
            op = b0 & 0x0F
            if op == OP_TEXT:
                self.inbox.append(json.loads(payload.decode()))
            elif op == OP_CLOSE:
                self.closed = True
            elif op == OP_PING:
                self.sock.sendall(encode_frame(OP_PONG, payload, mask=True))

    def poll(self):
        self._read()

    def take(self, kind, **match):
        for i, m in enumerate(self.inbox):
            if m.get("type") == kind and all(m.get(k) == v for k, v in match.items()):
                return self.inbox.pop(i)
        return None

    def wait(self, session, kind, timeout=8.0, **match):
        got = {}

        def ready():
            self.poll()
            m = self.take(kind, **match)
            if m is not None:
                got["m"] = m
            return "m" in got or self.closed
        pump(session, ready, timeout)
        if "m" not in got:
            raise AssertionError("no %s message (have %s, closed %s)" % (kind, [m.get("type") for m in self.inbox],
                                                                          self.closed))
        return got["m"]

    def close(self):
        try:
            self.sock.sendall(encode_frame(OP_CLOSE, struct.pack("!H", 1000), mask=True))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    # ---------- the protocol, as the plugin does it ----------

    def say_hello(self, session):
        self.send({"type": "hello", "v": 2, "nonce": self.nonce, "client": {"name": self.name, "version": "test"}})
        self.hello = self.wait(session, "hello")
        self.server_nonce = self.hello["nonce"]
        return self.hello

    def check_server(self, token):
        """Fake-server detection: the listener must prove it knows our token before we say anything else."""
        want = P.server_auth_proof(token, self.nonce, self.server_nonce)
        if not P.same(self.hello.get("proof"), want):
            raise FakeServerDetected("the listener on port %d did not prove it knows the pairing" % self.port)

    def auth(self, session, token):
        self.check_server(token)
        self.token = token
        self.send({"type": "auth", "proof": P.client_auth_proof(token, self.nonce, self.server_nonce)})
        return self.wait(session, "ready")

    def pair(self, session, code, typed=None):
        """Plays both sides of a first pairing: the plugin shows `code`; the person types `typed` (default the same)
        in Blender. Returns the ready message (or raises with the error)."""
        self.send({"type": "pair_request"})
        self.wait(session, "pair_wait")
        assert session.enter_code(typed if typed is not None else code)
        proof = self.wait(session, "pair_proof")
        key = P.derive_key(code, self.nonce, self.server_nonce)
        if not P.same(proof["proof"], P.server_pair_proof(key, self.nonce, self.server_nonce)):
            self.send({"type": "pair_fail"})
            return self.wait(session, "error")
        self.send({"type": "pair_confirm", "proof": P.client_pair_proof(key, self.nonce, self.server_nonce)})
        paired = self.wait(session, "paired")
        self.token = P.open_token(key, paired["box"], self.nonce, self.server_nonce)
        return self.wait(session, "ready")

    def call(self, session, call_id, tool, args=None, timeout=10.0):
        self.send({"type": "call", "id": call_id, "tool": tool, "args": args or {}, "client": "test"})
        return self.wait(session, "result", timeout=timeout, id=call_id)


def paired_session(code="482913"):
    """A listening Session on a free port and a client paired with it. Caller closes both (close_all)."""
    from nighty_blender import runtime
    from nighty_blender.session import Session
    session = Session(ports=[0])
    session.forget()
    assert session.start(), session.message
    runtime.set_session(session)        # the status tool reads the live session
    client = Client(session.server.port)
    pump(session, lambda: bool(session.conns))
    client.say_hello(session)
    ready = client.pair(session, code)
    assert ready.get("type") == "ready", ready
    return session, client


def close_all(session, *clients):
    from nighty_blender import runtime
    for c in clients:
        c.close()
    session.stop()
    session.forget()
    if runtime.get_session() is session:
        runtime.set_session(None)
