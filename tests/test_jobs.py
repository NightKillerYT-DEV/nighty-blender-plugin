# SPDX-License-Identifier: GPL-3.0-or-later
# The jobs framework: a generator job reports progress and finishes, a long one cancels, a crashing one fails; and,
# end to end through the listener and the dispatcher, a slow tool returns a job id and job { action: wait } delivers
# its result.

import json
import time

from nighty_blender import jobs as jobs_mod
from nighty_blender.jobs import JobManager
from nighty_blender.tools import TOOLS, text, tool
from ws_client import close_all, paired_session, pump


def test_generator_job_progress_and_done():
    sent = []
    mgr = JobManager(lambda obj: sent.append(obj))

    def step(job):
        yield 0.5, "halfway"
        return [text("finished")]

    job_id = mgr.start_gen(step, "demo", "demo", "tester")
    for _ in range(10):
        mgr.pump(budget=0.05)
        if mgr.get(job_id).state != jobs_mod.RUNNING:
            break
    job = mgr.get(job_id)
    assert job.state == jobs_mod.DONE, job.state
    assert job.progress == 1.0
    assert job.result == [text("finished")]
    states = [m["job"]["state"] for m in sent if m.get("type") == "job"]
    assert jobs_mod.DONE in states


def test_generator_job_cancel():
    mgr = JobManager(lambda obj: None)

    def forever(job):
        while True:
            if job.cancelled:
                return
            yield 0.1, "working"

    job_id = mgr.start_gen(forever, "demo", "demo", "tester")
    mgr.pump(budget=0.02)
    assert mgr.get(job_id).state == jobs_mod.RUNNING
    assert mgr.cancel(job_id)
    mgr.pump(budget=0.02)
    assert mgr.get(job_id).state == jobs_mod.CANCELLED


def test_generator_job_failure_carries_traceback():
    mgr = JobManager(lambda obj: None)

    def boom(job):
        yield 0.2
        raise ValueError("nope")

    job_id = mgr.start_gen(boom, "demo", "demo", "tester")
    for _ in range(10):
        mgr.pump(budget=0.05)
        if mgr.get(job_id).state != jobs_mod.RUNNING:
            break
    job = mgr.get(job_id)
    assert job.state == jobs_mod.FAILED
    assert "ValueError" in (job.error or "")


def test_subprocess_job():
    import os

    if os.name != "nt":
        return  # the test Blenders are Windows; the proc path is generic but this check uses cmd.exe
    mgr = JobManager(lambda obj: None)
    cmd = os.environ.get("COMSPEC", "cmd.exe")

    def finish(job, code, tail):
        return [text("exit %d, progress %.1f" % (code, job.progress))]

    job_id = mgr.start_proc([cmd, "/c", "echo NBJOB 1.0 done"], "demo", "demo", "tester", finish)
    for _ in range(100):
        mgr.pump(budget=0.05)
        if mgr.get(job_id).state != jobs_mod.RUNNING:
            break
        time.sleep(0.02)
    job = mgr.get(job_id)
    assert job.state == jobs_mod.DONE, (job.state, job.error)
    assert job.progress == 1.0
    assert "exit 0" in job.result[0]["text"]


def test_slow_tool_and_wait_job_end_to_end():
    name = "test_slow_demo"

    @tool(name, "A slow test tool.", {"type": "object", "properties": {"steps": {"type": "number"}}},
          slow=True, level="safe", changes=False)
    def _slow(ctx, args):
        steps = int(args.get("steps", 3))

        def step(job):
            for i in range(steps):
                if job.cancelled:
                    return
                yield (i + 1) / steps, "step %d" % (i + 1)
            return [text("done %d steps" % steps)]

        return ctx.start_job(step, "slow demo")

    session, client = paired_session()
    try:
        session.level = "safe"
        start = client.call(session, "s1", name, {"steps": 3})
        job_id = json.loads(start["content"][0]["text"])["job"]
        assert job_id
        done = client.call(session, "s2", "job", {"action": "wait", "id": job_id})
        assert done["isError"] is False
        assert "done 3 steps" in done["content"][0]["text"]
        # `job` progress messages went to the plugin on the way
        client.poll()
        assert any(m.get("type") == "job" for m in client.inbox)
    finally:
        TOOLS.pop(name, None)
        close_all(session, client)


def test_look_answers_in_the_same_call_without_long_ticks():
    """look runs as a job, one view per tick, parked: the AI gets the pictures in the same call and no tick of
    Blender's main thread takes a second (after the one-time render setup, which pairing does: view.warm_up)."""
    import bpy
    from nighty_blender import nighty as n
    bpy.ops.wm.read_factory_settings(use_empty=True)
    n.view.warm_up()
    assert n.view.warm_up() is False          # once per session
    for i in range(6):
        n.bevel(n.cylinder(0.05, 0.3, at=(i * 0.12, 0, 0.15), name="Post"), width=0.004)
    session, client = paired_session()
    try:
        session.level = "safe"
        client.send({"type": "call", "id": "l1", "tool": "look",
                     "args": {"wireframe": True, "mode": "matcap", "size": 320}})
        got, ticks = None, []
        end = time.monotonic() + 30
        while time.monotonic() < end and got is None:
            t = time.monotonic()
            session.tick()
            ticks.append(round(time.monotonic() - t, 3))
            client.poll()
            got = client.take("result", id="l1")
            time.sleep(0.01)
        assert got is not None, "look never answered"
        assert got["isError"] is False, got["content"][0].get("text")
        kinds = [b["type"] for b in got["content"]]
        assert kinds[0] == "text" and "image" in kinds
        assert max(ticks) < 1.0 * float(__import__("os").environ.get("NIGHTY_TEST_SLOW", "3" if __import__("os").environ.get("CI") else "1")), [x for x in ticks if x > 0.05]
    finally:
        close_all(session, client)
