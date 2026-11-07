// SPDX-License-Identifier: GPL-3.0-or-later
// The plugin's "Install / update add-on" with a real release zip, served from this computer:
//     python scripts/build_release.py --out <dir>  then  node tests/plugin/install.mjs <dir>/nighty_blender-<v>.zip
// A tampered copy is refused (nothing installed); the real one is downloaded, SHA-256 checked and installed with
// `blender --command extension install-file` into the newest Blender 4.2+ found, then checked. Blender's user folders
// point at a temp folder (BLENDER_USER_RESOURCES), so the person's own Blender is never touched.

import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { loadPlugin, panelText, until } from "./host.mjs";

const zipPath = process.argv[2];
if (!zipPath || !fs.existsSync(zipPath)) {
  console.log("usage: node tests/plugin/install.mjs <nighty_blender-x.y.z.zip>");
  process.exit(2);
}
const zip = fs.readFileSync(zipPath);
const version = /nighty_blender-(\d+\.\d+\.\d+)\.zip$/.exec(zipPath)[1];
const sha = crypto.createHash("sha256").update(zip).digest("hex");
const base = fs.mkdtempSync(path.join(os.tmpdir(), "nb-install-test-"));
const env = { BLENDER_USER_RESOURCES: path.join(base, "blender-user") };
let serve = zip;
const srv = http.createServer((q, res) => { res.end(serve); });
await new Promise((r) => srv.listen(0, "127.0.0.1", r));
const url = `http://127.0.0.1:${srv.address().port}/nighty_blender-${version}.zip`;
const pins = { addonVersion: version, addonUrl: url, addonSha256: sha, addonSize: zip.length };
let failed = 0;

async function attempt(name, data, expect) {
  serve = data;
  const p = loadPlugin({ dataDir: path.join(base, name, "data"), homeDir: path.join(base, "home"), ports: [1], env, pins });
  const t0 = Date.now();
  await p.click("install");
  await until(() => /Installed|Refused|stopped|couldn't|No Blender|Found only/.test(panelText(p.state)), 600000, name);
  const text = panelText(p.state);
  try {
    assert.match(text, expect);
    console.log(`  ok   ${name} (${Date.now() - t0} ms): ${text.split(" | ").filter((l) => /Installed|Refused|Blender/.test(l))[0]}`);
  } catch (e) {
    failed++;
    console.log(`  FAIL ${name}: ${text}`);
  }
  p.context.__NIGHTY_BLENDER_TEST__.exports.stop();
}

const tampered = Buffer.from(zip);
tampered[tampered.length - 100] ^= 0xff;
await attempt("a tampered zip is refused", tampered, /Refused: the downloaded add-on doesn't match the pinned SHA-256/);
const extDir = path.join(base, "blender-user", "extensions", "user_default", "nighty_blender");
assert.ok(!fs.existsSync(extDir), "nothing was installed");
await attempt("the real zip is checked and installed", zip, new RegExp(`Installed Nighty Blender ${version.replace(/\./g, "\\.")} in Blender`));
const manifest = fs.readFileSync(path.join(extDir, "blender_manifest.toml"), "utf8");
assert.match(manifest, new RegExp(`version = "${version}"`));
console.log(`\nplugin install: ${2 - failed} passed, ${failed} failed (installed into ${extDir})`);
srv.close();
fs.rmSync(base, { recursive: true, force: true });
process.exit(failed ? 1 : 0);
