// SPDX-License-Identifier: GPL-3.0-or-later
// The plugin and the real Blender add-on together, headless:  node tests/plugin/e2e.mjs [path to blender]
//   pairing in the panel (the code typed into Blender), the 15 tools through nighty.mcp.onCall (import a file and wait
//   for its job, a picture from look, the options question), reconnect with the kept token, a fake listener caught
//   before anything is sent, Forget. Blender runs in a sandbox (its user folders and the add-on's state in a temp
//   folder) on a free port, never 47871-47873.

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import crypto from "node:crypto";
import os from "node:os";
import path from "node:path";
import { ROOT, loadPlugin, panelText, until } from "./host.mjs";

const BLENDER = process.argv[2] || "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe";
const base = fs.mkdtempSync(path.join(os.tmpdir(), "nb-e2e-"));
const dataDir = path.join(base, "data");
const homeDir = path.join(base, "home");
const codeFile = path.join(base, "code.txt");
const doneFile = path.join(base, "done.txt");
fs.mkdirSync(homeDir, { recursive: true });
const sandbox = { BLENDER_USER_RESOURCES: path.join(base, "blender-user"), NIGHTY_BLENDER_STATE_DIR: path.join(base, "state") };

const results = [];
async function step(name, fn) {
  const t0 = Date.now();
  try {
    await fn();
    results.push([name, true]);
    console.log(`  ok   ${name} (${Date.now() - t0} ms)`);
  } catch (e) {
    results.push([name, false]);
    console.log(`  FAIL ${name}: ${e && e.stack || e}`);
  }
}

const blender = spawn(BLENDER, ["-b", "--factory-startup", "--python", path.join(ROOT, "tests", "plugin", "blender_server.py")],
  { env: { ...process.env, ...sandbox, NB_CODE_FILE: codeFile, NB_DONE_FILE: doneFile }, windowsHide: true });
let log = "";
blender.stdout.on("data", (d) => { log += d; });
blender.stderr.on("data", (d) => { log += d; });
await until(() => /PORT (\d+)/.test(log), 60000, "Blender's port");
const port = Number(/PORT (\d+)/.exec(log)[1]);
console.log(`Blender listening on 127.0.0.1:${port}`);

const opts = { dataDir, homeDir, ports: [port], env: sandbox };
let p = loadPlugin(opts);
const S = () => p.context.__NIGHTY_BLENDER_TEST__.exports.S;

await step("finds Blender, not paired yet; tools answer 'not paired'", async () => {
  await until(() => S().link === "unpaired", 20000, "unpaired");
  const r = await p.call("scene");
  assert.equal(r.isError, true);
  assert.match(r.content[0].text, /not paired/);
});

await step("pairs with the code shown in the Night Panel and typed in Blender", async () => {
  await p.click("pair");
  await until(() => /Pairing code/.test(JSON.stringify(p.state.panel)), 5000, "the code on the card");
  const code = S().code;
  assert.match(code, /^\d{6}$/);
  fs.writeFileSync(codeFile, code.slice(0, 3) + " " + code.slice(3));   // the person types it, with a space
  await until(() => S().link === "connected", 30000, "connected");
  assert.ok(/^[0-9a-f]{32}$/.test(S().token));
  const kept = JSON.parse(fs.readFileSync(path.join(dataDir, "pairing.json"), "utf8"));
  assert.equal(kept.token, S().token, "the token is in the plugin's own folder (outside the vault)");
  assert.match(panelText(p.state), /Connected/);
});

await step("status, guide and the options question through nighty.mcp", async () => {
  const st = JSON.parse((await p.call("status")).content[0].text);
  assert.equal(st.paired, true);
  assert.ok(st.addon.startsWith("2."));
  const g = await p.call("guide", { topic: "workflow" });
  assert.match(g.content[0].text, /import first/i);
  const api = await p.call("guide", { api: "bpy.types.Mesh.vertices" });
  assert.ok(!api.isError, api.content[0].text);
  const q = JSON.parse((await p.call("make_game_ready", { ask: true, options: { made_for: "roblox" } })).content[0].text);
  assert.match(q.question, /Triangles: 15,000/);
});

await step("import a file (a job) and wait for it in the plugin", async () => {
  const obj = path.join(base, "crate.obj");
  let v = "", f = "";
  const box = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]];
  for (const [x, y, z] of box) v += `v ${x} ${y} ${z}\n`;
  for (const q of [[1, 2, 3, 4], [5, 8, 7, 6], [1, 5, 6, 2], [2, 6, 7, 3], [3, 7, 8, 4], [4, 8, 5, 1]]) f += `f ${q.join(" ")}\n`;
  fs.writeFileSync(obj, v + f);
  const started = await p.call("import", { file: obj.replace(/\\/g, "/"), name: "Crate", size: 0.5 });
  assert.ok(!started.isError, started.content[0].text);
  const job = JSON.parse(started.content[0].text).job;
  let res;
  for (let i = 0; i < 5; i++) {
    res = await p.call("job", { action: "wait", id: job, seconds: 20 });
    if (!/still running/.test(res.content[0].text)) break;
  }
  assert.ok(!res.isError, res.content[0].text);
  const out = JSON.parse(res.content[0].text);
  assert.equal(out.object, "Crate");
  assert.equal(out.source, "Crate_SOURCE");
  assert.ok(Array.isArray(out.triage) && out.triage.length);
  assert.equal(out.facts.triangles, 12);
  const touch = await p.call("mesh", { op: "decimate", objects: ["Crate_SOURCE"], faces: 6 });
  assert.equal(touch.isError, true, "the _SOURCE copy is locked");
});

await step("a picture comes back from look", async () => {
  const r = await p.call("look", { names: ["Crate"], size: 128 });
  assert.ok(!r.isError, r.content[0].text);
  const img = r.content.find((b) => b.type === "image");
  assert.ok(img && img.data.length > 1000 && img.mimeType === "image/png");
});

await step("reconnects with the kept token (Blender proves it first)", async () => {
  p.context.__NIGHTY_BLENDER_TEST__.exports.stop();
  p = loadPlugin(opts);
  await until(() => S().link === "connected", 20000, "connected again without a code");
  const r = await p.call("scene");
  assert.ok(!r.isError);
});

await step("a fake listener is caught before anything is sent", async () => {
  const got = [];
  const token = S().token;
  // a WebSocket server that answers the handshake and a v2 hello, but knows no token
  const srv = http.createServer();
  srv.on("upgrade", (req, sock) => {
    const accept = crypto.createHash("sha1").update(req.headers["sec-websocket-key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest("base64");
    sock.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\nSec-WebSocket-Protocol: nighty-blender.v2\r\n\r\n`);
    sock.on("data", (buf) => {
      const len = buf[1] & 0x7f, off = len === 126 ? 4 : 2, mask = buf.subarray(off, off + 4);
      const n = len === 126 ? buf.readUInt16BE(2) : len;
      const body = Buffer.from(buf.subarray(off + 4, off + 4 + n).map((b, i) => b ^ mask[i & 3])).toString();
      try { got.push(JSON.parse(body).type); } catch (e) { return; }
      if (got[got.length - 1] === "hello") {
        const msg = Buffer.from(JSON.stringify({ type: "hello", v: 2, nonce: "ab".repeat(16), paired: true, proof: "cd".repeat(32) }));
        const head = msg.length < 126 ? Buffer.from([0x81, msg.length]) : Buffer.from([0x81, 126, msg.length >> 8, msg.length & 255]);
        sock.write(Buffer.concat([head, msg]));
      }
    });
  });
  await new Promise((r) => srv.listen(0, "127.0.0.1", r));
  const fakeDir = path.join(base, "fake-data");
  fs.mkdirSync(fakeDir, { recursive: true });
  fs.writeFileSync(path.join(fakeDir, "pairing.json"), JSON.stringify({ token }));
  const victim = loadPlugin({ ...opts, dataDir: fakeDir, ports: [srv.address().port] });
  const VS = () => victim.context.__NIGHTY_BLENDER_TEST__.exports.S;
  await until(() => VS().warn, 15000, "the warning");
  assert.match(VS().warn, /paired with something else|isn't Nighty Blender/);
  assert.deepEqual(got, ["hello"], "nothing but hello was sent to the fake listener");
  const r = await victim.call("scene");
  assert.equal(r.isError, true);
  victim.context.__NIGHTY_BLENDER_TEST__.exports.stop();
  srv.close();
});

await step("Forget ends the pairing on both sides", async () => {
  await p.click("forget");
  await p.click("forget");                  // the second click confirms
  await until(() => S().link !== "connected", 10000, "not connected");
  assert.equal(S().token, null);
  assert.ok(!fs.existsSync(path.join(dataDir, "pairing.json")));
});

fs.writeFileSync(doneFile, "done");
await until(() => /BYE/.test(log) || blender.exitCode !== null, 30000, "Blender to stop").catch(() => blender.kill());
const failed = results.filter(([, ok]) => !ok).length;
console.log(`\nplugin + add-on end to end: ${results.length - failed} passed, ${failed} failed`);
if (failed) console.log(log.split("\n").slice(-40).join("\n"));
fs.rmSync(base, { recursive: true, force: true });
process.exit(failed ? 1 : 0);
