# SPDX-License-Identifier: GPL-3.0-or-later
# Protocol v2 end to end against the add-on's own listener (server.py + session.py), with the tests' client playing
# the Nighty Vault plugin: the door (Origin, subprotocol, Host), nothing before pairing, pairing with the code and
# the sealed token, reconnect with the token, 5 wrong codes lock it, two programs pairing at once, fake-server
# detection, forget, the 16 MB cap and a 1 MB picture round trip. The listener binds a free port (never 47871-47873).

import base64
import json
import os
import socket
import threading
import time

from nighty_blender import pairing as P
from nighty_blender.server import encode_frame
from nighty_blender.session import Session
from nighty_blender.tools import TOOLS, image, text, tool
from ws_client import Client, FakeServerDetected, HandshakeRefused, close_all, paired_session, pump


def _listening():
    session = Session(ports=[0])
    session.forget()
    assert session.start(), session.message
    return session


def _connect(session, **kw):
    client = Client(session.server.port, **kw)
    n = len(session.conns)
    pump(session, lambda: len(session.conns) > n)
    return client


def test_listens_on_loopback_only_and_refuses_web_pages():
    session = _listening()
    try:
        assert session.server._srv.getsockname()[0] == "127.0.0.1"
        for kw in ({"origin": "https://evil.example"}, {"protocols": ("chat",)}, {"protocols": ()},
                   {"host": "evil.example:%d" % session.server.port}):
            try:
                Client(session.server.port, **kw)
                raise AssertionError("accepted %r" % (kw,))
            except HandshakeRefused as refused:
                assert "403" in refused.status_line, refused.status_line
        ok = Client(session.server.port, origin="null")      # the plugin's worker (opaque origin)
        ok.close()
    finally:
        session.stop()


def test_nothing_works_before_pairing():
    session = _listening()
    client = _connect(session)
    try:
        client.say_hello(session)
        assert client.hello["paired"] is False and "proof" not in client.hello
        res = client.call(session, "c1", "status")
        assert res["isError"] is True and "Not paired" in res["content"][0]["text"]
        client.send({"type": "config", "instantMeshes": "C:/x.exe"})
        err = client.wait(session, "error")
        assert err["code"] == "unpaired"
        # a call before hello is refused too
        other = _connect(session)
        res = other.call(session, "c2", "scene")
        assert res["isError"] is True
        other.close()
    finally:
        client.close()
        session.stop()


def test_pair_with_the_code_then_calls_work():
    session, client = paired_session("204816")
    try:
        assert client.token == session.record["token"] and P.is_hex(client.token, 32)
        assert session.status == "connected"
        res = client.call(session, "s1", "status")
        assert res["isError"] is False, res
        body = json.loads(res["content"][0]["text"])
        assert body["paired"] is True and body["addon"].startswith("2.")
        # the token was kept for next time (in the sandboxed state folder, not in any .blend)
        from nighty_blender.nighty.io import settings
        assert settings.load_pairing()["token"] == client.token
        assert os.environ["NIGHTY_BLENDER_STATE_DIR"] in settings.state_dir()
    finally:
        close_all(session, client)


def test_reconnect_with_the_token():
    session, first = paired_session()
    token = first.token
    first.close()
    pump(session, lambda: not session.client_conn)
    second = _connect(session)
    try:
        second.say_hello(session)
        assert second.hello["paired"] is True
        ready = second.auth(session, token)        # checks Blender's proof first (fake-server detection)
        assert ready["type"] == "ready" and "make_game_ready" in ready["tools"] and len(ready["tools"]) == 15
        assert second.call(session, "r1", "scene")["isError"] is False
        # a wrong token is refused and the connection closed
        third = _connect(session)
        third.say_hello(session)
        third.send({"type": "auth", "proof": "0" * 64})
        assert third.wait(session, "error")["code"] == "auth_failed"
        third.close()
    finally:
        close_all(session, second)


def test_a_wrong_code_and_five_wrong_codes_lock_it():
    session = _listening()
    client = _connect(session)
    try:
        client.say_hello(session)
        for i in range(1, 6):
            err = client.pair(session, "111111", typed="222222")
            if i < 5:
                assert err["code"] == "wrong_code" and err["left"] == 5 - i, err
                assert session.status == "waiting" or session.status == "code"
            else:
                assert err["code"] == "locked", err
        assert session.locked and session.status == "locked" and session.record is None
        client.send({"type": "pair_request"})
        assert client.wait(session, "error")["code"] == "locked"
        assert session.enter_code("111111") is False          # the panel refuses too
        session.unlock()                                       # only the person, in the panel
        ready = client.pair(session, "333444")
        assert ready["type"] == "ready"
    finally:
        close_all(session, client)


def test_two_programs_pairing_at_once_get_nothing():
    session = _listening()
    a, b = _connect(session), _connect(session)
    try:
        a.say_hello(session)
        b.say_hello(session)
        a.send({"type": "pair_request"})
        a.wait(session, "pair_wait")
        b.send({"type": "pair_request"})
        assert b.wait(session, "error")["code"] == "busy"
        assert a.wait(session, "error")["code"] == "busy"
        assert session.pending is None and session.enter_code("123456") is False
    finally:
        a.close()
        b.close()
        session.stop()


class _FakeListener:
    """Something else listening where Blender should be: it speaks WebSocket and v2's hello, but knows no token."""

    def __init__(self):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        conn, _ = self.srv.accept()
        head = b""
        while b"\r\n\r\n" not in head:
            head += conn.recv(4096)
        key = [l.split(":", 1)[1].strip() for l in head.decode().split("\r\n") if l.lower().startswith(
            "sec-websocket-key")][0]
        from nighty_blender.server import accept_key
        conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      "Sec-WebSocket-Accept: %s\r\nSec-WebSocket-Protocol: nighty-blender.v2\r\n\r\n"
                      % accept_key(key)).encode())
        time.sleep(0.2)
        hello = {"type": "hello", "v": 2, "nonce": P.new_nonce(), "paired": True, "proof": "ab" * 32}
        conn.sendall(encode_frame(0x1, json.dumps(hello).encode()))
        time.sleep(1.0)
        conn.close()


def test_fake_server_is_detected():
    # 1) a listener that knows nothing
    fake = _FakeListener()
    client = Client(fake.port)
    client.send({"type": "hello", "v": 2, "nonce": client.nonce})
    end = time.monotonic() + 3
    while time.monotonic() < end and not client.inbox:
        client.poll()
    client.hello = client.inbox.pop(0)
    client.server_nonce = client.hello["nonce"]
    try:
        client.check_server("0123456789abcdef0123456789abcdef")
        raise AssertionError("the fake listener was trusted")
    except FakeServerDetected:
        pass
    client.close()
    # 2) a real Nighty Blender, but paired with someone else (another token)
    session, owner = paired_session()
    other = _connect(session)
    try:
        other.say_hello(session)
        try:
            other.check_server("fedcba9876543210fedcba9876543210")
            raise AssertionError("a Blender paired with another token was trusted")
        except FakeServerDetected:
            pass
        other.check_server(owner.token)                     # the right token checks out
    finally:
        other.close()
        close_all(session, owner)


def test_forget_ends_the_pairing():
    session, client = paired_session()
    try:
        client.send({"type": "forget"})
        bye = client.wait(session, "bye")
        assert bye["reason"] == "unpaired" and session.record is None
        from nighty_blender.nighty.io import settings
        assert settings.load_pairing() is None
    finally:
        close_all(session, client)


def test_messages_over_16_mb_close_the_connection():
    session, client = paired_session()
    try:
        big = b'{"type":"call","id":"x","tool":"status","args":{"pad":"' + b"a" * (16 * 1024 * 1024 + 10) + b'"}}'
        try:
            client.send_raw(encode_frame(0x1, big, mask=True))
        except OSError:
            pass                                             # the server may close while we still write
        assert pump(session, lambda: (client.poll() or True) and not session.client_conn, timeout=15)
    finally:
        close_all(session, client)


def test_a_1_mb_picture_round_trip():
    name = "test_echo_picture"

    @tool(name, "Echo a picture (test only).", {"type": "object", "properties": {"data": {"type": "string"}}},
          changes=False)
    def _echo(ctx, args):
        return [text("ok"), image(base64.b64decode(args["data"]))]

    session, client = paired_session()
    try:
        blob = os.urandom(1024 * 1024)
        data = base64.b64encode(blob).decode()
        times = []
        for i in range(5):
            t = time.perf_counter()
            res = client.call(session, "img%d" % i, name, {"data": data})
            times.append(time.perf_counter() - t)
            assert res["isError"] is False
            assert base64.b64decode(res["content"][1]["data"]) == blob
        best = min(times)
        print("    1 MB picture round trip: best %.1f ms, median %.1f ms" % (best * 1000,
                                                                         sorted(times)[2] * 1000))
        assert best < 0.1, "a 1 MB round trip took %.0f ms (the plan asks under 100 ms)" % (best * 1000)
    finally:
        TOOLS.pop(name, None)
        close_all(session, client)


def test_level_gate_and_undo_naming():
    import bpy
    session, client = paired_session()
    try:
        session.level = "tools"
        res = client.call(session, "p1", "run_python", {"code": "result = 1"})
        assert res["isError"] is True and "safety level" in res["content"][0]["text"]
        session.level = "safe"
        bpy.ops.wm.read_factory_settings(use_empty=True)
        res = client.call(session, "p2", "run_python", {"code": "import bpy\nbpy.ops.mesh.primitive_cube_add()\n"
                                                                "result = len(bpy.data.objects)"})
        assert res["isError"] is False, res
        res = client.call(session, "u0", "undo", {"list": True})
        assert res["isError"] is False
    finally:
        close_all(session, client)


def test_unknown_tool():
    session, client = paired_session()
    try:
        res = client.call(session, "x1", "no_such_tool")
        assert res["isError"] is True and "no tool" in res["content"][0]["text"].lower()
    finally:
        close_all(session, client)
