// SPDX-License-Identifier: GPL-3.0-or-later
// The plugin's pure parts, in Node (no Blender, no network):  node tests/plugin/unit.mjs
//   - SHA-256 / HMAC / PBKDF2 in plain JS match Node's crypto (and WebCrypto)
//   - the pairing proofs match the add-on's pairing.py (vectors made with it)
//   - plugin.json follows the Nighty Vault contract; main.js fits the plugin limits
//   - the 1.x clean-up edits only the old "nighty-blender" entries (JSON and TOML)
//   - the AI tools answer plainly when Blender isn't there; job wait waits at most 45 s

import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { ROOT, loadPlugin } from "./host.mjs";

const VECTORS = {   // from addon/nighty_blender/pairing.py
  nc: "00112233445566778899aabbccddeeff", ns: "ffeeddccbbaa99887766554433221100", code: "482913",
  token: "0123456789abcdef0123456789abcdef",
  key: "e56536af625c96cec4b243f7c0b023323f7abeeb7829efc760662854647f6550",
  serverPair: "965864034c13a0f2e74d694e1f10f5a24e1e4b674f161767692888fa789c9f05",
  clientPair: "9c77440e5651871bbfd73b0201fc363b783efc991aae8b73fdecf2040f4b2729",
  serverAuth: "57aa5fc56cc1739091eba0b252ae822e4cd4f8bddc27e932309b07b6257f1dd5",
  clientAuth: "902677965175d6572134cf8c3b2b25659f950d92c1211009344623bae1c650f5",
  box: "79bb3355003ee5fc6ccd9f1f72404314",
};

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "nb-plugin-"));

function plugin(opts = {}) {
  const base = tmp();
  return loadPlugin({ dataDir: path.join(base, "data"), homeDir: path.join(base, "home"), ports: [1], ...opts });
}

test("plain SHA-256 and HMAC match Node", () => {
  const { context } = plugin();
  const X = context.__NIGHTY_BLENDER_TEST__.exports;
  for (const n of [0, 1, 55, 56, 63, 64, 65, 119, 120, 1000, 100000]) {
    const data = crypto.randomBytes(n);
    assert.equal(Buffer.from(X.sha256(new Uint8Array(data))).toString("hex"), crypto.createHash("sha256").update(data).digest("hex"), "sha256 " + n);
    const key = crypto.randomBytes(n % 100 + 1);
    assert.equal(Buffer.from(X.hmac(new Uint8Array(key), new Uint8Array(data))).toString("hex"),
      crypto.createHmac("sha256", key).update(data).digest("hex"), "hmac " + n);
  }
});

test("PBKDF2 in plain JS and WebCrypto match Node", async () => {
  for (const plainCrypto of [true, false]) {
    const { context } = plugin({ plainCrypto });
    const X = context.__NIGHTY_BLENDER_TEST__.exports;
    const got = Buffer.from(await X.pbkdf2("482913", "salt|a|b", 2000)).toString("hex");
    assert.equal(got, crypto.pbkdf2Sync("482913", "salt|a|b", 2000, 32, "sha256").toString("hex"), "plain=" + plainCrypto);
  }
});

test("the pairing proofs match the add-on's pairing.py", async () => {
  for (const plainCrypto of [false, true]) {
    const { context } = plugin({ plainCrypto });
    const X = context.__NIGHTY_BLENDER_TEST__.exports;
    const v = VECTORS;
    const t0 = Date.now();
    const key = await X.pbkdf2(v.code, `nighty-blender.v2|${v.nc}|${v.ns}`, 100000);
    if (plainCrypto) console.log(`    plain-JS PBKDF2 (100,000 rounds): ${Date.now() - t0} ms`);
    assert.equal(Buffer.from(key).toString("hex"), v.key);
    assert.equal(X.P.serverPair(key, v.nc, v.ns), v.serverPair);
    assert.equal(X.P.clientPair(key, v.nc, v.ns), v.clientPair);
    assert.equal(X.P.serverAuth(v.token, v.nc, v.ns), v.serverAuth);
    assert.equal(X.P.clientAuth(v.token, v.nc, v.ns), v.clientAuth);
    assert.equal(X.P.openToken(key, v.box, v.nc, v.ns), v.token);
  }
});

test("codes are 6 digits", () => {
  const { context } = plugin();
  const X = context.__NIGHTY_BLENDER_TEST__.exports;
  const seen = new Set();
  for (let i = 0; i < 500; i++) {
    const c = X.newCode();
    assert.match(c, /^\d{6}$/);
    seen.add(c);
  }
  assert.ok(seen.size > 490, "random");
});

test("plugin.json follows the contract and the files fit the plugin limits", () => {
  const pj = JSON.parse(fs.readFileSync(path.join(ROOT, "plugin", "plugin.json"), "utf8"));
  assert.deepEqual(pj.permissions, ["system", "panel", "storage"]);
  assert.equal(pj.mcp.prefix, "blender");
  assert.match(pj.mcp.prefix, /^[a-z][a-z0-9]{1,15}$/);
  assert.ok(pj.mcp.note.length <= 600);
  assert.ok(pj.mcp.note.includes("Models come from the person's file, an import, or code only when the person asks"));
  assert.equal(pj.mcp.tools.length, 15);
  const names = pj.mcp.tools.map((t) => t.name).sort();
  assert.deepEqual(names, ["check", "export", "guide", "import", "job", "look", "make_game_ready", "measure", "mesh",
    "reference", "run_python", "scene", "status", "texture", "undo"]);
  for (const t of pj.mcp.tools) {
    assert.match(t.name, /^[a-z][a-z0-9_]{0,39}$/);
    assert.ok(("blender_" + t.name).length <= 56);
    assert.ok(t.description.length > 0 && t.description.length <= 1024, t.name);
    assert.equal(t.inputSchema.type, "object");
    for (const [k, v] of Object.entries(t.annotations || {})) assert.equal(typeof v, "boolean", k);
  }
  assert.ok(Buffer.byteLength(JSON.stringify(pj.mcp.tools)) <= 64 * 1024);
  let total = 0;
  for (const f of fs.readdirSync(path.join(ROOT, "plugin"))) {
    assert.match(f, /\.(js|json|md|txt|css|png|svg|webp|jpg)$/, f);
    const size = fs.statSync(path.join(ROOT, "plugin", f)).size;
    assert.ok(size <= 2 * 1024 * 1024, f);
    total += size;
  }
  assert.ok(total <= 5 * 1024 * 1024);
});

test("the 1.x clean-up removes only the old entries", () => {
  const { context } = plugin();
  const X = context.__NIGHTY_BLENDER_TEST__.exports;
  const toml = `model = "o3"\n\n[mcp_servers.nighty-blender]\ncommand = "npx"\nargs = ["x"]\n\n[mcp_servers.nighty-blender.env]\nA = "1"\n\n[mcp_servers.other]\ncommand = "node"\n`;
  const out = X.tomlWithout(toml, "nighty-blender");
  assert.equal(out.removed, 2);
  assert.ok(!out.text.includes("nighty-blender") && out.text.includes("[mcp_servers.other]") && out.text.includes('model = "o3"'));
  const data = { mcpServers: { "nighty-blender": { command: "npx" }, keep: { command: "x" } },
    projects: { "C:/p": { mcpServers: { "nighty-blender": {}, mine: {} } } } };
  assert.equal(X.jsonWithout(data, "nighty-blender"), 2);
  assert.deepEqual(Object.keys(data.mcpServers), ["keep"]);
  assert.deepEqual(Object.keys(data.projects["C:/p"].mcpServers), ["mine"]);
});

test("blender --version and repo-list are read", () => {
  const { context } = plugin();
  const X = context.__NIGHTY_BLENDER_TEST__.exports;
  assert.deepEqual([...X.versionOf("Blender 4.2.23 LTS\n\tbuild date")], [4, 2, 23]);
  const repos = X.parseRepoList("user_default:\n    name: \"User Default\"\n    directory: \"C:\\\\x\\\\user_default\"\nnightycode:\n    name: \"NightyCode\"\n    url: \"https://nightkilleryt.com/blender/extensions/index.json\"\n    directory: \"C:\\\\y\"\n");
  assert.equal(repos.length, 2);
  assert.equal(repos[1].id, "nightycode");
  assert.ok(repos[1].url.includes("nightkilleryt.com"));
});

test("without Blender the tools answer plainly; status still answers", async () => {
  const p = plugin();
  const status = await p.call("status");
  assert.ok(!status.isError);
  const s = JSON.parse(status.content[0].text);
  assert.equal(s.connected, false);
  assert.ok(s.models_come_from.includes("person's file"));
  const look = await p.call("look", {});
  assert.equal(look.isError, true);
  assert.match(look.content[0].text, /Blender isn't connected|not paired/);
  const job = await p.call("job", { action: "wait" });
  assert.equal(job.isError, true);
});

test("job wait returns at once when the job is done, and stops at 45 s", async () => {
  const p = plugin();
  const X = p.context.__NIGHTY_BLENDER_TEST__.exports;
  X.S.jobs.set("j1", { id: "j1", tool: "bake", state: "done", progress: 1, result: [{ type: "text", text: "baked" }] });
  const done = await p.call("job", { action: "wait", id: "j1" });
  assert.equal(done.content[0].text, "baked");
  X.S.jobs.set("j2", { id: "j2", tool: "bake", state: "running", progress: 0.5, message: "half" });
  const t0 = Date.now();
  const r = await p.call("job", { action: "wait", id: "j2", seconds: 1 });
  assert.ok(Date.now() - t0 < 2500);
  assert.match(r.content[0].text, /still running \(50%\)/);
});

test("a tampered or unpinned add-on is refused", async () => {
  const base = tmp();
  const zip = Buffer.from("not the real add-on");
  const http = await import("node:http");
  const srv = http.createServer((q, res) => { res.end(zip); }).listen(0, "127.0.0.1");
  await new Promise((r) => srv.once("listening", r));
  const url = `http://127.0.0.1:${srv.address().port}/nighty_blender-2.0.0.zip`;
  try {
    const p = loadPlugin({ dataDir: path.join(base, "data"), homeDir: path.join(base, "home"), ports: [1],
      pins: { addonVersion: "2.0.0", addonUrl: url, addonSha256: "0".repeat(64), addonSize: zip.length },
      env: { BLENDER_USER_RESOURCES: path.join(base, "blender-user") } });
    await p.click("install");
    const { until, panelText } = await import("./host.mjs");
    await until(() => /Refused|No Blender|Found only/.test(panelText(p.state)), 120000, "the refusal");
    const text = panelText(p.state);
    if (/No Blender|Found only/.test(text)) console.log("    (no Blender 4.2+ here: the hash check was not reached)");
    else assert.match(text, /Refused: the downloaded add-on doesn't match the pinned SHA-256/);
    const unpinned = loadPlugin({ dataDir: path.join(base, "data2"), homeDir: path.join(base, "home"), ports: [1] });
    await unpinned.click("install");
    assert.match(panelText(unpinned.state), /no pinned add-on/);
  } finally {
    srv.close();
  }
});

let failed = 0;
for (const [name, fn] of tests) {
  const t0 = Date.now();
  try {
    await fn();
    console.log(`  ok   ${name} (${Date.now() - t0} ms)`);
  } catch (e) {
    failed++;
    console.log(`  FAIL ${name}: ${e && e.stack || e}`);
  }
}
console.log(`\nplugin unit tests: ${tests.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
