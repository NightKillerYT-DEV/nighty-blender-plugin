// SPDX-License-Identifier: GPL-3.0-or-later
// Nighty Blender 2 for Nighty Vault: one plugin with full access ("system").
//
//   AI app -> nighty-vault.exe --mcp -> Nighty Vault -> this plugin (nighty.mcp.onCall)
//          -> WebSocket ws://127.0.0.1:47871-47873, subprotocol nighty-blender.v2 -> the Blender add-on
//
// What it does:
//   - the 15 blender_* tools: forwarded to the paired Blender add-on; `job` { action: wait } waits here (45 s max)
//   - pairing in the Night Panel: a 6-digit code shown here, typed by the person in Blender's N panel; HMAC proofs
//     both ways (Blender proves first, so a fake listener is caught); the token is kept in this plugin's own data
//     folder outside the vault (never in the vault, which may sync)
//   - installs / updates the add-on: the pinned zip, SHA-256 checked, into the newest Blender 4.2+ with
//     `blender --command extension install-file`, then checked; the fallback is "drag the zip into Blender"
//   - "Install AI skills", "Get Instant Meshes" (pinned and hash-checked), and "Move from Nighty Blender 1.x"
// Models come from the person's file, an import, or code only when the person asks: Nighty Blender has no AI model.
// docs/PROTOCOL.md describes the wire; PLUGIN-MCP-CONTRACT.md the nighty.mcp side. One file, no imports.

"use strict";

// ---------------------------------------------------------------- pins (scripts/build_release.py fills these)

const PINS = /*@pins*/{
  "addonVersion": "2.0.0",
  "addonUrl": "https://github.com/NightKillerYT-DEV/nighty-blender-plugin/releases/download/v2.0.0/nighty_blender-2.0.0.zip",
  "addonSha256": "",
  "addonSize": 0
}/*@end*/;

const INSTANT_MESHES = {
  win32: {
    url: "https://instant-meshes.s3.eu-central-1.amazonaws.com/Release/instant-meshes-windows.zip",
    size: 1401791,
    sha256: "c9f6217e83ea90f98a8cd54cf82dac88420df20cf197e7a4ef2bef81c5ae068d",
    exe: "Instant Meshes.exe",
    exeSize: 3449856,
    exeSha256: "f1fe5b5f56d1002ae61dbd76a3fd646229fc1fe15322e7a3744f8ce442c76b2d",
  },
  page: "https://github.com/wjakob/instant-meshes",
  license: "BSD-3-Clause with an extra 'Enhancements' clause (Copyright 2015 Wenzel Jakob, Daniele Panozzo, Marco " +
    "Tarini, Olga Sorkine-Hornung). Downloaded unmodified from its official address; not bundled.",
};

const TEST = (typeof globalThis !== "undefined" && globalThis.__NIGHTY_BLENDER_TEST__) || null;
const PORTS = (TEST && TEST.ports) || [47871, 47872, 47873];
const SUBPROTOCOL = "nighty-blender.v2";
const WAIT_MAX_S = 45;
const CALL_TIMEOUT_MS = 55000;          // Nighty Vault gives a call 58 s
const RESULT_MAX_BYTES = 8 * 1024 * 1024;
const MIN_BLENDER = [4, 2];
const OLD_SERVER_NAME = "nighty-blender";
const OLD_REPO_ID = "nightycode";
const SKILL_MARK = "nighty-blender-v2";

// ---------------------------------------------------------------- small helpers

const enc = new TextEncoder();
const dec = new TextDecoder();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const hex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
const unhex = (s) => new Uint8Array(String(s).match(/../g).map((h) => parseInt(h, 16)));
const isHex = (s, n) => typeof s === "string" && s.length === n && /^[0-9a-f]+$/.test(s);
const join = (...parts) => parts.filter(Boolean).join("/").replace(/\\/g, "/").replace(/\/+/g, "/");
const errText = (e) => (e && e.message) || String(e);

function randomBytes(n) {
  const out = new Uint8Array(n);
  crypto.getRandomValues(out);
  return out;
}

function b64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function bytesToB64(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

// ---------------------------------------------------------------- SHA-256, HMAC, PBKDF2 (plain JS; crypto.subtle when there)

const K256 = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98,
  0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
  0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8,
  0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819,
  0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
  0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
  0xc67178f2]);
const H0 = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];

function compress(h, w, block, off) {
  for (let i = 0; i < 16; i++) {
    const j = off + i * 4;
    w[i] = (block[j] << 24) | (block[j + 1] << 16) | (block[j + 2] << 8) | block[j + 3];
  }
  for (let i = 16; i < 64; i++) {
    const a = w[i - 15], b = w[i - 2];
    const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
    const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
    w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
  }
  let a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], k = h[7];
  for (let i = 0; i < 64; i++) {
    const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
    const t1 = (k + S1 + ((e & f) ^ (~e & g)) + K256[i] + w[i]) | 0;
    const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
    const t2 = (S0 + ((a & b) ^ (a & c) ^ (b & c))) | 0;
    k = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
  }
  h[0] = (h[0] + a) | 0; h[1] = (h[1] + b) | 0; h[2] = (h[2] + c) | 0; h[3] = (h[3] + d) | 0;
  h[4] = (h[4] + e) | 0; h[5] = (h[5] + f) | 0; h[6] = (h[6] + g) | 0; h[7] = (h[7] + k) | 0;
}

function sha256Raw(data, start) {
  // start: an optional [state, bytes already hashed] (HMAC's precomputed key block)
  const h = start ? Int32Array.from(start[0]) : Int32Array.from(H0);
  const done = start ? start[1] : 0;
  const w = new Int32Array(64);
  const n = data.length;
  const full = n - (n % 64);
  for (let off = 0; off < full; off += 64) compress(h, w, data, off);
  const tail = new Uint8Array(((n % 64) + 9 > 64) ? 128 : 64);
  tail.set(data.subarray(full));
  tail[n - full] = 0x80;
  const bits = (n + done) * 8;
  const view = new DataView(tail.buffer);
  view.setUint32(tail.length - 8, Math.floor(bits / 0x100000000));
  view.setUint32(tail.length - 4, bits >>> 0);
  for (let off = 0; off < tail.length; off += 64) compress(h, w, tail, off);
  const out = new Uint8Array(32);
  const ov = new DataView(out.buffer);
  for (let i = 0; i < 8; i++) ov.setInt32(i * 4, h[i]);
  return out;
}

const sha256 = (data) => sha256Raw(data instanceof Uint8Array ? data : enc.encode(String(data)));

function hmacKeyState(key) {
  let k = key.length > 64 ? sha256(key) : key;
  const block = new Uint8Array(64);
  block.set(k);
  const ip = new Uint8Array(64), op = new Uint8Array(64);
  for (let i = 0; i < 64; i++) { ip[i] = block[i] ^ 0x36; op[i] = block[i] ^ 0x5c; }
  const w = new Int32Array(64);
  const hi = Int32Array.from(H0), ho = Int32Array.from(H0);
  compress(hi, w, ip, 0);
  compress(ho, w, op, 0);
  return { inner: [hi, 64], outer: [ho, 64] };
}

function hmacWith(state, msg) {
  return sha256Raw(sha256Raw(msg, state.inner), state.outer);
}

const hmac = (key, msg) => hmacWith(hmacKeyState(key), msg instanceof Uint8Array ? msg : enc.encode(msg));

async function pbkdf2(password, salt, iterations) {
  const subtle = typeof crypto !== "undefined" && crypto.subtle;
  if (subtle && !(TEST && TEST.plainCrypto)) {
    try {
      const base = await subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveBits"]);
      const bits = await subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt: enc.encode(salt), iterations },
        base, 256);
      return new Uint8Array(bits);
    } catch (e) { /* no WebCrypto here: plain JS below */ }
  }
  const state = hmacKeyState(enc.encode(password));
  const s = enc.encode(salt);
  const first = new Uint8Array(s.length + 4);
  first.set(s);
  first[s.length + 3] = 1;
  let u = hmacWith(state, first);
  const out = u.slice();
  for (let i = 1; i < iterations; i++) {
    u = hmacWith(state, u);
    for (let j = 0; j < 32; j++) out[j] ^= u[j];
    if (i % 5000 === 0) await sleep(0);       // never hold the worker for long
  }
  return out;
}

async function sha256Hex(bytes) {
  const subtle = typeof crypto !== "undefined" && crypto.subtle;
  if (subtle && !(TEST && TEST.plainCrypto)) {
    try { return hex(new Uint8Array(await subtle.digest("SHA-256", bytes))); } catch (e) { /* plain JS */ }
  }
  return hex(sha256(bytes));
}

// The proofs (docs/PROTOCOL.md section 3; the add-on's pairing.py computes the same)
const proof = (key, label, a, b) => hex(hmac(key, `${label}|${a}|${b}`));
const pairKey = (code, nc, ns) => pbkdf2(code, `nighty-blender.v2|${nc}|${ns}`, 100000);
const P = {
  serverPair: (key, nc, ns) => proof(key, "nb2/server-pair", nc, ns),
  clientPair: (key, nc, ns) => proof(key, "nb2/client-pair", ns, nc),
  serverAuth: (token, nc, ns) => proof(unhex(token), "nb2/server-auth", nc, ns),
  clientAuth: (token, nc, ns) => proof(unhex(token), "nb2/client-auth", ns, nc),
  openToken(key, box, nc, ns) {
    const pad = unhex(proof(key, "nb2/token-box", nc, ns)).subarray(0, 16);
    const b = unhex(box);
    return hex(b.map((x, i) => x ^ pad[i]));
  },
};

function sameText(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

function newCode() {
  // 6 digits, uniform (no modulo bias)
  const max = Math.floor(0xffffffff / 1000000) * 1000000;
  for (;;) {
    const v = new Uint32Array(1);
    crypto.getRandomValues(v);
    if (v[0] < max) return String(v[0] % 1000000).padStart(6, "0");
  }
}

// ---------------------------------------------------------------- state

const S = {
  info: null,                // nighty.system.info()
  token: null,               // the pairing, from <dataDir>/pairing.json
  ws: null,
  port: null,
  link: "off",               // off | connecting | hello | unpaired | pairing | connected
  hello: null,
  nonce: null,
  code: null,                // the code on show while pairing
  pairNote: null,
  warn: null,                // a red line (fake listener, locked, ...)
  ready: null,               // the add-on's ready message
  calls: new Map(),          // call id -> { resolve, timer }
  jobs: new Map(),           // job id -> snapshot
  jobWaiters: new Map(),     // job id -> [resolve]
  seq: 0,
  view: "main",              // main | install | move | skills
  busy: null,                // a long action running ("Installing the add-on…")
  progress: null,
  lines: [],                 // results of the last action (shown in the card)
  blenders: null,
  confirm: null,             // a pending second click: { action, until }
  move: null,                // what the 1.x check found
  imPath: null,
  retry: 0,
};

function say(...lines) {
  S.lines = lines.filter(Boolean).slice(0, 12);
  render();
}

// ---------------------------------------------------------------- the plugin's own files (outside the vault)

async function dataPath(...parts) {
  if (!S.info) S.info = await nighty.system.info();
  return join(S.info.dataDir, ...parts);
}

async function loadToken() {
  try {
    const path = await dataPath("pairing.json");
    if (!(await nighty.files.exists(path))) return null;
    const rec = JSON.parse(await nighty.files.read(path));
    return isHex(rec.token, 32) ? rec.token : null;
  } catch (e) {
    return null;
  }
}

async function saveToken(token) {
  const path = await dataPath("pairing.json");
  if (token) await nighty.files.write(path, JSON.stringify({ token, since: new Date().toISOString() }));
  else if (await nighty.files.exists(path)) await nighty.files.remove(path);
  S.token = token;
}

// ---------------------------------------------------------------- the link to Blender

function send(obj) {
  if (S.ws && S.ws.readyState === 1) {
    S.ws.send(JSON.stringify(obj));
    return true;
  }
  return false;
}

function dropSocket(reason) {
  const ws = S.ws;
  S.ws = null;
  if (ws) {
    ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
    try { ws.close(1000, reason || "bye"); } catch (e) { /* already closed */ }
  }
  for (const [id, call] of S.calls) {
    clearTimeout(call.timer);
    call.resolve(errorResult("Blender went away during the call. Is it still open?"));
    S.calls.delete(id);
  }
}

function linkDown(why) {
  dropSocket(why);
  if (S.link !== "off") S.link = "connecting";
  S.ready = null;
  render();
  scheduleConnect();
}

let connectTimer = null;
function scheduleConnect(soon) {
  if (connectTimer || S.link === "off") return;
  const delay = soon ? 50 : Math.min(10000, 1500 * Math.max(1, S.retry));
  connectTimer = setTimeout(() => { connectTimer = null; connect(); }, delay);
}

async function connect() {
  if (S.ws || S.link === "off") return;
  for (const port of PORTS) {
    const ok = await tryPort(port);
    if (ok) { S.retry = 0; return; }
  }
  S.retry += 1;
  S.link = "connecting";
  render();
  scheduleConnect();
}

function tryPort(port) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (v) => { if (!settled) { settled = true; resolve(v); } };
    let ws;
    try {
      ws = new WebSocket(`ws://127.0.0.1:${port}`, SUBPROTOCOL);
    } catch (e) {
      done(false);
      return;
    }
    const timer = setTimeout(() => { try { ws.close(); } catch (e) { /* */ } done(false); }, 3000);
    ws.onerror = () => { clearTimeout(timer); done(false); };
    ws.onclose = () => { clearTimeout(timer); if (!settled) done(false); else if (S.ws === ws) linkDown("closed"); };
    ws.onopen = () => {
      if (ws.protocol && ws.protocol !== SUBPROTOCOL) { clearTimeout(timer); ws.close(); done(false); return; }
      S.ws = ws;
      S.port = port;
      S.link = "hello";
      S.nonce = hex(randomBytes(16));
      ws.onmessage = (ev) => { onMessage(ev.data).catch((e) => console.warn("Nighty Blender:", e)); };
      send({ type: "hello", v: 2, nonce: S.nonce,
             client: { name: "Nighty Vault", version: (nighty.app && nighty.app.version) || "" } });
      clearTimeout(timer);
      done(true);
    };
  });
}

async function onMessage(raw) {
  let m;
  try { m = JSON.parse(raw); } catch (e) { return; }
  if (!m || typeof m.type !== "string") return;
  switch (m.type) {
    case "hello": return onHello(m);
    case "ready":
      S.ready = m;
      S.link = "connected";
      S.warn = null;
      S.code = null;
      S.pairNote = null;
      if (S.imPath) send({ type: "config", instantMeshes: S.imPath });
      render();
      return;
    case "pair_wait":
      S.pairNote = "Type this code in Blender: N panel → Nighty tab → Pairing.";
      render();
      return;
    case "pair_proof": return onPairProof(m);
    case "paired": return onPaired(m);
    case "result": {
      const call = S.calls.get(m.id);
      if (call) {
        clearTimeout(call.timer);
        S.calls.delete(m.id);
        call.resolve(cleanResult(m));
      }
      return;
    }
    case "job": {
      const snap = m.job;
      if (snap && typeof snap.id === "string") {
        S.jobs.set(snap.id, snap);
        if (snap.state !== "running") {
          const waiters = S.jobWaiters.get(snap.id) || [];
          S.jobWaiters.delete(snap.id);
          waiters.forEach((w) => w(snap));
        }
        if (S.jobs.size > 60) S.jobs.delete(S.jobs.keys().next().value);
        renderSoon();
      }
      return;
    }
    case "info":
      if (S.ready) S.ready.level = m.level;
      render();
      return;
    case "error": return onError(m);
    case "bye":
      if (m.reason === "unpaired") { await saveToken(null); S.link = "unpaired"; }
      if (m.reason === "replaced") {
        // another Nighty Vault (or window) took Blender over: don't fight it; the person can take it back
        S.link = "off";
        S.warn = "Another Nighty Vault connected to this Blender. Press Connect to use it here again.";
      }
      linkDown("bye");
      return;
    default:
  }
}

async function onHello(m) {
  if (m.v !== 2 || !isHex(m.nonce, 32)) {
    S.warn = "Something on port " + S.port + " isn't Nighty Blender 2. Update the Blender add-on.";
    return linkDown("version");
  }
  S.hello = m;
  if (S.token) {
    // fake-server detection: Blender must prove it knows our token before we say anything else
    if (!m.paired || !sameText(m.proof, P.serverAuth(S.token, S.nonce, m.nonce))) {
      S.link = "unpaired";
      S.warn = m.paired
        ? "The Blender on port " + S.port + " is paired with something else (or isn't Nighty Blender). " +
          "Pair again if it is yours."
        : "Blender forgot the pairing. Pair again.";
      render();
      return;
    }
    send({ type: "auth", proof: P.clientAuth(S.token, S.nonce, m.nonce) });
    return;
  }
  S.link = "unpaired";
  if (m.locked) S.warn = "Pairing is locked in Blender after 5 wrong codes. Press Unlock in Blender's Nighty panel.";
  render();
}

function startPairing() {
  if (!S.ws || !S.hello) {
    say("Blender isn't reachable yet: open Blender, press N, open the Nighty tab and press Connect to Nighty Vault.");
    return;
  }
  S.code = newCode();
  S.link = "pairing";
  S.warn = null;
  S.pairNote = "Waiting for Blender…";
  send({ type: "pair_request" });
  render();
}

async function onPairProof(m) {
  if (!S.code || !S.hello) return;
  const key = await pairKey(S.code, S.nonce, S.hello.nonce);
  if (!sameText(m.proof, P.serverPair(key, S.nonce, S.hello.nonce))) {
    send({ type: "pair_fail" });
    S.pairNote = "The code typed in Blender doesn't match. Type it again: " + spaced(S.code) + ".";
    render();
    return;
  }
  S.pairKey = key;
  send({ type: "pair_confirm", proof: P.clientPair(key, S.nonce, S.hello.nonce) });
}

async function onPaired(m) {
  if (!S.pairKey || !isHex(m.box, 32)) return;
  const token = P.openToken(S.pairKey, m.box, S.nonce, S.hello.nonce);
  S.pairKey = null;
  await saveToken(token);
  nighty.ui.toast("Paired with Blender.");
}

function onError(m) {
  const code = m.code;
  if (code === "wrong_code") S.pairNote = `Blender says the code doesn't match (${m.left} tries left). Type ${spaced(S.code || "")} again.`;
  else if (code === "locked") { S.warn = m.message; S.code = null; S.link = "unpaired"; }
  else if (code === "busy" || code === "pair_timeout") { S.warn = m.message; S.code = null; S.link = "unpaired"; }
  else if (code === "auth_failed") { S.warn = m.message; saveToken(null); S.link = "unpaired"; }
  else if (m.message) S.warn = m.message;
  render();
}

const spaced = (code) => (code ? code.slice(0, 3) + " " + code.slice(3) : "");

// ---------------------------------------------------------------- the AI tools

function errorResult(text) {
  return { content: [{ type: "text", text }], isError: true };
}

function cleanResult(m) {
  let content = Array.isArray(m.content) ? m.content.filter((b) => b && (b.type === "text" || b.type === "image")) : [];
  if (!content.length) content = [{ type: "text", text: "done" }];
  let size = JSON.stringify(content).length;
  if (size > RESULT_MAX_BYTES) {
    content = content.filter((b) => b.type === "text");
    content.push({ type: "text", text: "(The pictures were over 8 MB together and were left out: ask look for a smaller size.)" });
    size = JSON.stringify(content).length;
    if (size > RESULT_MAX_BYTES) content = [{ type: "text", text: content[0].text.slice(0, 200000) + "…" }];
  }
  return { content, isError: !!m.isError };
}

function forward(tool, args, ctx) {
  return new Promise((resolve) => {
    const id = "v" + (++S.seq);
    const timer = setTimeout(() => {
      S.calls.delete(id);
      resolve(errorResult("Blender didn't answer within 55 s. It may be busy (a long render or bake); try again, " +
        "or check Blender."));
    }, CALL_TIMEOUT_MS);
    S.calls.set(id, { resolve, timer });
    if (!send({ type: "call", id, tool, args: args || {}, client: (ctx && ctx.client) || "AI",
                sessionId: (ctx && ctx.sessionId) || "" })) {
      clearTimeout(timer);
      S.calls.delete(id);
      resolve(errorResult(notConnectedText()));
    }
  });
}

function notConnectedText() {
  if (S.link === "unpaired" || S.link === "pairing") {
    return "Blender is open but not paired with Nighty Vault yet. Ask the person to open the Nighty Blender card in " +
      "Nighty Vault's Night Panel, press Pair, and type the code in Blender (N panel → Nighty tab).";
  }
  return "Blender isn't connected. Ask the person to open Blender (4.2 or newer) with the Nighty Blender add-on " +
    "(N panel → Nighty tab → Connect to Nighty Vault). The Nighty Blender card in Nighty Vault installs the add-on.";
}

function jobContent(snap) {
  const r = snap.result;
  if (Array.isArray(r) && r.every((b) => b && typeof b.type === "string")) return r;
  if (r !== undefined && r !== null) return [{ type: "text", text: typeof r === "string" ? r : JSON.stringify(r) }];
  return [{ type: "text", text: JSON.stringify(snap) }];
}

async function jobTool(args, ctx) {
  if (!args || args.action !== "wait") return forward("job", args, ctx);
  const id = args.id;
  if (typeof id !== "string" || !id) return errorResult("Give the job `id`.");
  const seconds = Math.max(1, Math.min(WAIT_MAX_S, Number(args.seconds) || WAIT_MAX_S));
  let snap = S.jobs.get(id);
  if (!snap) {
    // not seen here (Nighty Vault restarted, say): ask Blender
    const got = await forward("job", { action: "get", id }, ctx);
    if (got.isError) return got;
    try { snap = JSON.parse(got.content[0].text); S.jobs.set(id, snap); } catch (e) { return got; }
  }
  if (snap.state === "running") {
    snap = await new Promise((resolve) => {
      const list = S.jobWaiters.get(id) || [];
      const timer = setTimeout(() => {
        S.jobWaiters.set(id, (S.jobWaiters.get(id) || []).filter((w) => w !== finish));
        resolve(S.jobs.get(id) || snap);
      }, seconds * 1000);
      const finish = (s) => { clearTimeout(timer); resolve(s); };
      list.push(finish);
      S.jobWaiters.set(id, list);
    });
  }
  if (snap.state === "done") return { content: jobContent(snap), isError: false };
  if (snap.state === "running") {
    const pct = Math.round((snap.progress || 0) * 100);
    return { content: [{ type: "text", text: JSON.stringify({ id, state: "running", progress: snap.progress,
      message: snap.message, next: `still running (${pct}%): call job { action: "wait", id: "${id}" } again` }) }] };
  }
  return { content: [{ type: "text", text: JSON.stringify(snap) }], isError: true };
}

async function onTool(tool, args, ctx) {
  if (tool === "job") return jobTool(args || {}, ctx);
  if (S.link !== "connected") {
    if (tool === "status") {
      return { content: [{ type: "text", text: JSON.stringify({
        paired: !!S.token, connected: false, link: S.link, port: S.port,
        addonPinned: PINS.addonVersion, note: notConnectedText(),
        models_come_from: "the person's file (import), a scene mesh, or code only when the person asks" }) }] };
    }
    return errorResult(notConnectedText());
  }
  return forward(tool, args, ctx);
}

// ---------------------------------------------------------------- finding Blender

async function run(program, args, opts) {
  try {
    return await nighty.system.run(program, args || [], opts || {});
  } catch (e) {
    return { code: -1, stdout: "", stderr: errText(e) };
  }
}

const versionOf = (text) => {
  const m = /Blender\s+(\d+)\.(\d+)(?:\.(\d+))?/.exec(text || "");
  return m ? [Number(m[1]), Number(m[2]), Number(m[3] || 0)] : null;
};
const cmpVersion = (a, b) => (a[0] - b[0]) || (a[1] - b[1]) || ((a[2] || 0) - (b[2] || 0));

async function listDir(path) {
  try { return await nighty.files.list(path); } catch (e) { return []; }
}

async function candidates() {
  const info = S.info || (S.info = await nighty.system.info());
  const out = new Set();
  const add = (p) => { if (p) out.add(p.replace(/\\/g, "/")); };
  if (info.os === "windows") {
    const home = info.homeDir.replace(/\\/g, "/");
    const roots = ["C:/Program Files/Blender Foundation", "C:/Program Files (x86)/Blender Foundation",
      home + "/AppData/Local/Programs/Blender Foundation", home + "/AppData/Local/Blender Foundation"];
    for (const root of roots) for (const e of await listDir(root)) if (e.isDir) add(e.path + "/blender.exe");
    for (const steam of ["C:/Program Files (x86)/Steam/steamapps/common/Blender", "C:/Program Files/Steam/steamapps/common/Blender"]) add(steam + "/blender.exe");
    for (const key of ["HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\blender.exe",
      "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\blender.exe", "HKCR\\blendfile\\shell\\open\\command"]) {
      const r = await run("reg", ["query", key, "/ve"], { timeoutMs: 8000 });
      const line = (r.stdout || "").split(/\r?\n/).find((l) => /REG_(EXPAND_)?SZ/.test(l));
      const m = line && /"?([A-Za-z]:\\[^"]*?blender(?:-launcher)?\.exe)"?/i.exec(line);
      if (m) add(m[1].replace(/blender-launcher\.exe$/i, "blender.exe"));
    }
    const w = await run("where", ["blender"], { timeoutMs: 8000 });
    for (const l of (w.stdout || "").split(/\r?\n/)) if (/blender\.exe$/i.test(l.trim())) add(l.trim());
  } else if (info.os === "macos") {
    for (const base of ["/Applications", info.homeDir + "/Applications"]) {
      for (const e of await listDir(base)) if (/^blender.*\.app$/i.test(e.name)) add(e.path + "/Contents/MacOS/Blender");
    }
  } else {
    const w = await run("which", ["-a", "blender"], { timeoutMs: 8000 });
    for (const l of (w.stdout || "").split(/\n/)) if (l.trim()) add(l.trim());
    add("/snap/bin/blender");
    for (const base of [info.homeDir, info.homeDir + "/.local/share", "/opt"]) {
      for (const e of await listDir(base)) if (e.isDir && /^blender/i.test(e.name)) add(e.path + "/blender");
    }
  }
  return [...out];
}

async function findBlenders() {
  const found = [];
  for (const exe of await candidates()) {
    if (!(await nighty.files.exists(exe).catch(() => false))) continue;
    const r = await run(exe, ["--factory-startup", "--version"], { timeoutMs: 60000 });
    const v = versionOf(r.stdout + "\n" + r.stderr);
    if (v) found.push({ exe, version: v, text: v.join(".") });
  }
  found.sort((a, b) => cmpVersion(b.version, a.version));
  S.blenders = found;
  return found;
}

async function newestBlender() {
  const all = S.blenders || (await findBlenders());
  return all.find((b) => cmpVersion(b.version, MIN_BLENDER) >= 0) || null;
}

// No --factory-startup here: the extension commands must see the person's own repositories and preferences (and a
// factory-startup run that enables an add-on could save factory preferences over theirs).
const blender = (b, args, timeoutMs) => run(b.exe, ["--command", "extension", ...args], { timeoutMs: timeoutMs || 180000 });

function parseRepoList(text) {
  const repos = [];
  let cur = null;
  for (const line of String(text || "").split(/\r?\n/)) {
    const start = /^([A-Za-z0-9_.-]+):\s*$/.exec(line);
    if (start) { cur = { id: start[1] }; repos.push(cur); continue; }
    const f = /^\s+(name|directory|url|source):\s*(.*)$/.exec(line);
    if (f && cur) cur[f[1]] = f[2].trim().replace(/^"(.*)"$/, "$1");
  }
  return repos;
}

async function installedCopies(b) {
  // every repository that holds a nighty_blender, with its version
  const r = await blender(b, ["repo-list"], 60000);
  const out = [];
  for (const repo of parseRepoList(r.stdout)) {
    if (!repo.directory) continue;
    const manifest = join(repo.directory, "nighty_blender", "blender_manifest.toml");
    if (!(await nighty.files.exists(manifest).catch(() => false))) continue;
    const text = await nighty.files.read(manifest).catch(() => "");
    const m = /^\s*version\s*=\s*"([^"]+)"/m.exec(text);
    out.push({ repo: repo.id, url: repo.url || "", directory: repo.directory, version: m ? m[1] : "?" });
  }
  return out;
}

async function isBlenderOpen() {
  const info = S.info || (S.info = await nighty.system.info());
  if (info.os === "windows") {
    const r = await run("tasklist", ["/FI", "IMAGENAME eq blender.exe", "/NH"], { timeoutMs: 15000 });
    return /blender\.exe/i.test(r.stdout || "");
  }
  const r = await run("pgrep", ["-x", "blender"], { timeoutMs: 10000 });
  return r.code === 0;
}

// ---------------------------------------------------------------- downloads (hash-checked)

async function download(url, dest, size) {
  // Its folder first: curl and files.write don't make missing folders (curl's "error 23" on a fresh install).
  const parent = dest.replace(/\\/g, "/").replace(/\/[^/]*$/, "");
  if (parent) await nighty.files.mkdir(parent);
  // The browser's fetch first (full access keeps it); curl when the server doesn't allow it.
  try {
    const res = await fetch(url, { redirect: "follow" });
    if (res.ok) {
      const bytes = new Uint8Array(await res.arrayBuffer());
      await nighty.files.write(dest, bytes);
      return bytes;
    }
  } catch (e) { /* CORS or no network through the worker: curl below */ }
  const r = await run("curl", ["-L", "--fail", "--silent", "--show-error", "--max-time", "300", "-o", dest, url],
    { timeoutMs: 320000 });
  if (r.code !== 0) throw new Error("the download failed (" + ((r.stderr || "").trim().split("\n").pop() || "curl " + r.code) + ")");
  const bytes = b64ToBytes(await nighty.files.read(dest, { encoding: "base64" }));
  if (size && bytes.length !== size) throw new Error(`the file has ${bytes.length} bytes, not ${size}`);
  return bytes;
}

// ---------------------------------------------------------------- install / update the add-on

async function installAddon() {
  if (!isHex(PINS.addonSha256, 64)) {
    return say("This copy of the plugin has no pinned add-on (a development build). Use a released " +
      ".nightyplugin, or drag nighty_blender-" + PINS.addonVersion + ".zip into Blender.");
  }
  S.busy = "Installing the Blender add-on";
  try {
    progress(0.05, "Finding Blender 4.2 or newer");
    S.blenders = null;
    const b = await newestBlender();
    if (!b) {
      const old = (S.blenders || []).map((x) => "Blender " + x.text).join(", ");
      return say(old ? `Found only ${old}: Nighty Blender needs Blender 4.2 or newer.` : "No Blender found on this computer.",
        "Install Blender 4.2 or newer from blender.org, then press Install again.");
    }
    progress(0.15, `Blender ${b.text}: checking for older copies`);
    const copies = await installedCopies(b);
    const old = copies.find((c) => /^1\./.test(c.version));
    if (old) {
      S.view = "move";
      return say(`Nighty Blender ${old.version} is installed in Blender ${b.text}. Remove it first (Move from 1.x), ` +
        "so the two copies don't clash.");
    }
    progress(0.25, "Downloading the add-on");
    const zip = await dataPath("downloads", `nighty_blender-${PINS.addonVersion}.zip`);
    const bytes = await download(PINS.addonUrl, zip, PINS.addonSize);
    progress(0.6, "Checking its SHA-256");
    const got = await sha256Hex(bytes);
    if (got !== PINS.addonSha256) {
      await nighty.files.remove(zip).catch(() => {});
      return say("Refused: the downloaded add-on doesn't match the pinned SHA-256 (nothing was installed).",
        "Expected " + PINS.addonSha256, "Got " + got);
    }
    progress(0.7, `Installing into Blender ${b.text}`);
    const r = await blender(b, ["install-file", "-r", "user_default", "-e", zip.replace(/\//g, S.info.os === "windows" ? "\\" : "/")]);
    if (r.code !== 0) {
      return say("Blender couldn't install it: " + ((r.stderr || r.stdout || "").trim().split("\n").pop() || "exit " + r.code),
        "Fallback: drag " + zip + " into the Blender window (or Edit → Preferences → Get Extensions → Install from Disk).");
    }
    progress(0.9, "Checking the install");
    const now = (await installedCopies(b)).find((c) => c.repo === "user_default");
    if (!now || now.version !== PINS.addonVersion) {
      return say(`Blender said it installed it, but its folder has ${now ? "version " + now.version : "no Nighty Blender"}.`,
        "Fallback: drag " + zip + " into the Blender window.");
    }
    const open = await isBlenderOpen();
    say(`Installed Nighty Blender ${PINS.addonVersion} in Blender ${b.text} (SHA-256 checked).`,
      open ? "Blender is open: save your work and restart it so it loads the add-on." : "Start Blender: it's there.",
      "Then press N in the 3D view, open the Nighty tab and press Connect to Nighty Vault.");
  } catch (e) {
    say("The install stopped: " + errText(e), "Fallback: download " + PINS.addonUrl + " and drag the zip into Blender.");
  } finally {
    S.busy = null;
    S.progress = null;
    render();
  }
}

function progress(value, label) {
  S.progress = { value, label };
  render();
}

// ---------------------------------------------------------------- Instant Meshes

async function getInstantMeshes() {
  const info = S.info || (S.info = await nighty.system.info());
  const pin = info.os === "windows" ? INSTANT_MESHES.win32 : null;
  if (!pin) return say("There is no checked Instant Meshes build for this system yet; Blender's own QuadriFlow is used.");
  S.busy = "Getting Instant Meshes";
  try {
    const dir = await dataPath("tools", "instant-meshes");
    await nighty.files.mkdir(dir);
    const exe = join(dir, pin.exe);
    if (await nighty.files.exists(exe)) {
      const have = await sha256Hex(b64ToBytes(await nighty.files.read(exe, { encoding: "base64" })));
      if (have === pin.exeSha256) return useInstantMeshes(exe, "Instant Meshes is already here (checked).");
    }
    progress(0.1, "Downloading Instant Meshes (1.4 MB)");
    const zip = join(dir, "instant-meshes-windows.zip");
    const bytes = await download(pin.url, zip, pin.size);
    if ((await sha256Hex(bytes)) !== pin.sha256) {
      await nighty.files.remove(zip).catch(() => {});
      return say("Refused: the Instant Meshes download doesn't match its pinned SHA-256 (nothing kept).");
    }
    progress(0.6, "Unpacking");
    const r = await run("tar", ["-xf", zip.replace(/\//g, "\\"), "-C", dir.replace(/\//g, "\\")], { timeoutMs: 60000 });
    if (r.code !== 0) return say("Couldn't unpack it: " + (r.stderr || "").trim());
    const got = await sha256Hex(b64ToBytes(await nighty.files.read(exe, { encoding: "base64" })));
    if (got !== pin.exeSha256) {
      await nighty.files.remove(exe).catch(() => {});
      return say("Refused: the unpacked program doesn't match its pinned SHA-256 (removed).");
    }
    await nighty.files.remove(zip).catch(() => {});
    await nighty.files.write(join(dir, "SOURCE.txt"), `Instant Meshes, unmodified, from ${pin.url}\n` +
      `SHA-256 ${pin.exeSha256}\nProject: ${INSTANT_MESHES.page}\nLicense: ${INSTANT_MESHES.license}\n`);
    return useInstantMeshes(exe, "Instant Meshes is installed (SHA-256 checked).");
  } catch (e) {
    say("Instant Meshes wasn't installed: " + errText(e));
  } finally {
    S.busy = null;
    S.progress = null;
    render();
  }
}

async function useInstantMeshes(exe, line) {
  S.imPath = exe.replace(/\//g, S.info.os === "windows" ? "\\" : "/");
  await nighty.storage.set("instantMeshes", S.imPath);
  const told = send({ type: "config", instantMeshes: S.imPath });
  say(line, told ? "Blender's retopo uses it now." : "Blender gets it when it connects.");
}

// ---------------------------------------------------------------- AI skills

async function bundledSkills() {
  const info = S.info || (S.info = await nighty.system.info());
  const root = join(info.pluginDir, "skills");
  const out = [];
  async function walk(dir, rel) {
    for (const e of await listDir(dir)) {
      if (e.isDir) await walk(e.path, join(rel, e.name));
      else out.push({ path: e.path, rel: join(rel, e.name) });
    }
  }
  await walk(root, "");
  return out;
}

async function skillTargets() {
  const info = S.info || (S.info = await nighty.system.info());
  const home = info.homeDir.replace(/\\/g, "/");
  return [{ app: "Claude Code", dir: home + "/.claude/skills" }, { app: "Codex and other agents", dir: home + "/.agents/skills" }];
}

async function installSkills(replace) {
  S.busy = "Installing AI skills";
  try {
    const files = await bundledSkills();
    const names = [...new Set(files.map((f) => f.rel.split("/")[0]))].filter(Boolean);
    if (!names.length) return say("This plugin has no skills bundled.");
    const kept = [];
    const wrote = [];
    for (const target of await skillTargets()) {
      for (const name of names) {
        const dest = join(target.dir, name);
        const skill = join(dest, "SKILL.md");
        if (await nighty.files.exists(skill).catch(() => false)) {
          const text = await nighty.files.read(skill).catch(() => "");
          if (!text.includes(SKILL_MARK) && !replace) { kept.push(`${target.app}: ${name}`); continue; }
          if (!text.includes(SKILL_MARK)) {
            const backup = await dataPath("backups", `skill-${name}-${Date.now()}.md`);
            await nighty.files.write(backup, text);
          }
        }
        for (const f of files.filter((x) => x.rel.split("/")[0] === name)) {
          await nighty.files.write(join(target.dir, f.rel), await nighty.files.read(f.path));
        }
        wrote.push(`${target.app}: ${name}`);
      }
    }
    const lines = [wrote.length ? "Installed: " + wrote.join(", ") + "." : "Nothing written."];
    if (kept.length) {
      lines.push("Kept your own skills with the same names: " + kept.join(", ") + ". Press Install AI skills " +
        "twice to replace them (a backup is kept in the plugin's folder).");
      S.confirm = { action: "skills-replace", until: Date.now() + 30000 };
    }
    lines.push("New chats in those apps pick them up.");
    say(...lines);
  } catch (e) {
    say("The skills weren't installed: " + errText(e));
  } finally {
    S.busy = null;
    render();
  }
}

// ---------------------------------------------------------------- Move from Nighty Blender 1.x

async function oldConfigFiles() {
  const info = S.info || (S.info = await nighty.system.info());
  const home = info.homeDir.replace(/\\/g, "/");
  const list = [
    { app: "Claude Code", path: home + "/.claude.json", kind: "json" },
    { app: "Cursor", path: home + "/.cursor/mcp.json", kind: "json" },
    { app: "Gemini CLI", path: home + "/.gemini/settings.json", kind: "json" },
    { app: "Codex", path: home + "/.codex/config.toml", kind: "toml" },
  ];
  if (info.os === "windows") {
    list.push({ app: "Claude Desktop", path: home + "/AppData/Roaming/Claude/claude_desktop_config.json", kind: "json" });
    for (const e of await listDir(home + "/AppData/Local/Packages")) {
      if (/^Claude_/i.test(e.name)) {
        list.push({ app: "Claude Desktop (Store)", kind: "json",
          path: e.path + "/LocalCache/Roaming/Claude/claude_desktop_config.json" });
      }
    }
  } else if (info.os === "macos") {
    list.push({ app: "Claude Desktop", path: home + "/Library/Application Support/Claude/claude_desktop_config.json", kind: "json" });
  } else {
    list.push({ app: "Claude Desktop", path: home + "/.config/Claude/claude_desktop_config.json", kind: "json" });
  }
  const out = [];
  for (const f of list) if (await nighty.files.exists(f.path).catch(() => false)) out.push(f);
  return out;
}

function tomlWithout(text, name) {
  const lines = text.split(/\r?\n/);
  const head = new RegExp(`^\\s*\\[\\s*mcp_servers\\.(?:"${name}"|${name})(?:\\.[^\\]]*)?\\s*\\]\\s*$`);
  const out = [];
  let skipping = false, removed = 0;
  for (const line of lines) {
    if (/^\s*\[/.test(line)) {
      skipping = head.test(line);
      if (skipping) removed++;
    }
    if (!skipping) out.push(line);
  }
  return { text: out.join("\n"), removed };
}

function jsonWithout(data, name) {
  let removed = 0;
  const strip = (obj) => {
    if (obj && typeof obj === "object" && obj.mcpServers && typeof obj.mcpServers === "object" && name in obj.mcpServers) {
      delete obj.mcpServers[name];
      removed++;
    }
  };
  strip(data);
  if (data && data.projects && typeof data.projects === "object") for (const p of Object.values(data.projects)) strip(p);
  return removed;
}

async function oldEngineFolders() {
  const info = S.info || (S.info = await nighty.system.info());
  const home = info.homeDir.replace(/\\/g, "/");
  const cfg = info.os === "windows" ? home + "/AppData/Roaming/NightyBlender"
    : info.os === "macos" ? home + "/Library/Application Support/NightyBlender" : home + "/.config/nighty-blender";
  let engine = info.os === "windows" ? home + "/AppData/Local/NightyBlender"
    : info.os === "macos" ? home + "/Library/Application Support/NightyBlender" : home + "/.local/share/NightyBlender";
  try {
    const conf = JSON.parse(await nighty.files.read(cfg + "/engine.json"));
    if (conf && typeof conf.folder === "string" && conf.folder) engine = conf.folder.replace(/\\/g, "/");
  } catch (e) { /* the default folder */ }
  const out = [];
  for (const [what, path] of [["the old AI engine (models and its runtime)", engine], ["the old engine settings and keys", cfg],
    ["the old MCP program's pairing folder", home + "/.nighty-blender-mcp"]]) {
    if (out.some((x) => x.path === path)) continue;
    if (await nighty.files.exists(path).catch(() => false)) out.push({ what, path });
  }
  return out;
}

async function checkOld() {
  S.busy = "Looking for Nighty Blender 1.x";
  try {
    const blenders = [];
    for (const b of S.blenders || (await findBlenders())) {
      const copies = (await installedCopies(b)).filter((c) => /^1\./.test(c.version));
      if (copies.length) blenders.push({ b, copies });
    }
    const configs = [];
    for (const f of await oldConfigFiles()) {
      const text = await nighty.files.read(f.path).catch(() => "");
      if (f.kind === "toml") {
        if (tomlWithout(text, OLD_SERVER_NAME).removed) configs.push(f);
      } else {
        try { if (jsonWithout(JSON.parse(text), OLD_SERVER_NAME)) configs.push(f); } catch (e) { /* not JSON */ }
      }
    }
    S.move = { blenders, configs, folders: await oldEngineFolders() };
    const lines = [];
    lines.push(blenders.length ? "Old add-on: " + blenders.map((x) => `Blender ${x.b.text} has ${x.copies.map((c) => c.version + " (" + c.repo + ")").join(", ")}`).join("; ")
      : "No Nighty Blender 1.x add-on in any Blender found.");
    lines.push(configs.length ? "Old AI-app entries (" + OLD_SERVER_NAME + "): " + configs.map((c) => c.app).join(", ")
      : "No old AI-app entries.");
    lines.push(S.move.folders.length ? "Old folders: " + S.move.folders.map((f) => f.path).join(", ") : "No old engine folders.");
    say(...lines);
  } catch (e) {
    say("The check stopped: " + errText(e));
  } finally {
    S.busy = null;
    render();
  }
}

async function removeOldAddon() {
  if (!S.move) await checkOld();
  S.busy = "Removing Nighty Blender 1.x";
  const lines = [];
  try {
    if (await isBlenderOpen()) lines.push("Blender is open: it keeps the old add-on loaded until you restart it.");
    for (const { b, copies } of S.move.blenders) {
      for (const c of copies) {
        const r = await blender(b, ["remove", `${c.repo}.nighty_blender`], 120000);
        lines.push(r.code === 0 ? `Removed ${c.version} from Blender ${b.text}.` : `Blender ${b.text} couldn't remove it: ${(r.stderr || r.stdout).trim().split("\n").pop()}`);
        if (c.repo === OLD_REPO_ID && /nightkilleryt\.com/i.test(c.url)) {
          const rr = await blender(b, ["repo-remove", OLD_REPO_ID], 60000);
          if (rr.code === 0) lines.push(`Removed the old update source from Blender ${b.text}.`);
        }
      }
    }
    if (!S.move.blenders.length) lines.push("No old add-on to remove.");
    lines.push("Next: Install the 2.0 add-on (Install / update add-on).");
    S.move.blenders = [];
    say(...lines);
  } finally {
    S.busy = null;
    render();
  }
}

async function cleanOldConfigs() {
  const lines = [];
  for (const f of (S.move && S.move.configs) || []) {
    try {
      const text = await nighty.files.read(f.path);
      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      const backup = await dataPath("backups", `${f.app.replace(/[^A-Za-z0-9]+/g, "-")}-${stamp}.bak`);
      await nighty.files.write(backup, text);
      let next;
      if (f.kind === "toml") next = tomlWithout(text, OLD_SERVER_NAME).text;
      else {
        const data = JSON.parse(text);
        jsonWithout(data, OLD_SERVER_NAME);
        next = JSON.stringify(data, null, 2) + "\n";
      }
      await nighty.files.write(f.path, next);
      lines.push(`${f.app}: removed "${OLD_SERVER_NAME}" (backup: ${backup}).`);
    } catch (e) {
      lines.push(`${f.app}: not changed (${errText(e)}).`);
    }
  }
  if (S.move) S.move.configs = [];
  lines.push("Restart those AI apps. Nighty Blender's tools now come through Nighty Vault (blender_*).");
  say(...lines);
}

async function recycleOldFolders() {
  const lines = [];
  for (const f of (S.move && S.move.folders) || []) {
    try {
      await nighty.files.remove(f.path);
      lines.push(`Sent to the Recycle Bin: ${f.path}.`);
    } catch (e) {
      lines.push(`Not removed: ${f.path} (${errText(e)}).`);
    }
  }
  if (S.move) S.move.folders = [];
  lines.push("Empty the Recycle Bin when you are sure, to get the space back.");
  say(...lines);
}

// ---------------------------------------------------------------- the Night Panel card

function needsConfirm(action, question) {
  if (S.confirm && S.confirm.action === action && S.confirm.until > Date.now()) {
    S.confirm = null;
    return false;
  }
  S.confirm = { action, until: Date.now() + 30000 };
  say(question, "Press the same button again within 30 s to go ahead.");
  return true;
}

let renderTimer = null;
function renderSoon() {
  if (!renderTimer) renderTimer = setTimeout(() => { renderTimer = null; render(); }, 300);
}

function linkLine() {
  switch (S.link) {
    case "connected": {
      const r = S.ready || {};
      return [{ type: "stat", label: "Blender", value: `Connected · ${r.blender || "?"}` },
        { type: "text", text: `Add-on ${r.addon || "?"} · safety level ${r.level || "?"} (set in Blender only)`, muted: true }];
    }
    case "pairing":
      return [{ type: "stat", label: "Pairing code", value: spaced(S.code) },
        { type: "text", text: S.pairNote || "Type this code in Blender: N panel → Nighty tab → Pairing." }];
    case "unpaired":
      return [{ type: "stat", label: "Blender", value: "Open, not paired" },
        { type: "text", text: "Press Pair, then type the code in Blender's N panel (Nighty tab).", muted: true }];
    case "off":
      return [{ type: "stat", label: "Blender", value: "Not connected" }];
    default:
      return [{ type: "stat", label: "Blender", value: "Not connected yet" },
        { type: "text", text: "Open Blender with the add-on: N panel → Nighty tab → Connect to Nighty Vault.", muted: true }];
  }
}

function render() {
  const items = [...linkLine()];
  if (S.warn) items.push({ type: "text", text: "⚠ " + S.warn });
  const running = [...S.jobs.values()].filter((j) => j.state === "running").slice(0, 3);
  for (const j of running) items.push({ type: "progress", value: j.progress || 0, label: `${j.tool}: ${j.message || "working"}` });
  if (S.busy) items.push({ type: "progress", value: S.progress ? S.progress.value : 0, label: S.progress ? S.progress.label : S.busy });
  for (const l of S.lines.slice(0, 8)) items.push({ type: "text", text: l });
  if (S.view === "main") {
    if (S.link === "unpaired" || (S.link === "pairing")) items.push({ type: "button", label: S.link === "pairing" ? "New code" : "Pair", action: "pair" });
    if (S.link === "off") items.push({ type: "button", label: "Connect", action: "reconnect" });
    items.push({ type: "button", label: "Install / update add-on", action: "install" });
    items.push({ type: "button", label: "Get Instant Meshes", action: "im" });
    items.push({ type: "button", label: "Install AI skills", action: "skills" });
    items.push({ type: "button", label: "Move from Nighty Blender 1.x", action: "move" });
    if (S.token) items.push({ type: "button", label: "Forget pairing", action: "forget" });
  } else if (S.view === "move") {
    items.push({ type: "text", text: "Moving from 1.x: remove the old add-on, then install 2.0. The old AI-app entries and the " +
      "old engine folder (about 23 GB) are only touched when you press their buttons twice.", muted: true });
    items.push({ type: "button", label: "Check again", action: "move-check" });
    items.push({ type: "button", label: "Remove the 1.x add-on", action: "move-addon" });
    items.push({ type: "button", label: "Install the 2.0 add-on", action: "install" });
    items.push({ type: "button", label: "Clean old AI-app entries…", action: "move-config" });
    items.push({ type: "button", label: "Old engine folder → Recycle Bin…", action: "move-folders" });
    items.push({ type: "button", label: "Back", action: "back" });
  }
  nighty.panel.set({ title: "Nighty Blender", items: items.slice(0, 30) }).catch(() => {});
}

async function onAction(action) {
  if (S.busy && !["back", "pair"].includes(action)) return say("Wait for “" + S.busy + "” to finish.");
  switch (action) {
    case "pair": return startPairing();
    case "reconnect": S.link = "connecting"; S.warn = null; S.retry = 0; render(); return connect();
    case "install": return installAddon();
    case "im": return getInstantMeshes();
    case "skills": {
      const replace = !!(S.confirm && S.confirm.action === "skills-replace" && S.confirm.until > Date.now());
      S.confirm = null;
      return installSkills(replace);
    }
    case "move": S.view = "move"; return checkOld();
    case "move-check": return checkOld();
    case "move-addon": return removeOldAddon();
    case "move-config":
      if (!S.move) await checkOld();
      if (!S.move.configs.length) return say("No old AI-app entries to clean.");
      if (needsConfirm("move-config", `Remove "${OLD_SERVER_NAME}" from ${S.move.configs.map((c) => c.app + " (" + c.path + ")").join(", ")}? ` +
        "A backup of each file is kept in the plugin's own folder first.")) return null;
      return cleanOldConfigs();
    case "move-folders":
      if (!S.move) await checkOld();
      if (!S.move.folders.length) return say("No old engine folders found.");
      if (needsConfirm("move-folders", "Send to the Recycle Bin: " + S.move.folders.map((f) => f.path + " (" + f.what + ")").join("; ") + "?")) return null;
      return recycleOldFolders();
    case "forget":
      if (needsConfirm("forget", "Forget the pairing with Blender? Pairing again needs a new code.")) return null;
      send({ type: "forget" });
      await saveToken(null);
      S.link = "unpaired";
      return say("Forgot the pairing.");
    case "back": S.view = "main"; S.lines = []; return render();
    default:
  }
  return null;
}

// ---------------------------------------------------------------- start

nighty.mcp.onCall((tool, args, ctx) => onTool(tool, args, ctx));
nighty.panel.onAction((action) => { onAction(action).catch((e) => say("That stopped: " + errText(e))); });
render();

(async () => {
  try {
    S.info = await nighty.system.info();
    S.token = await loadToken();
    S.imPath = await nighty.storage.get("instantMeshes");
  } catch (e) {
    S.warn = "Couldn't read the plugin's folder: " + errText(e);
  }
  S.link = "connecting";
  render();
  connect();
})();

// for the tests (tests/plugin): the pure parts
if (TEST) {
  TEST.exports = { sha256, hmac, pbkdf2, P, proof, newCode, tomlWithout, jsonWithout, parseRepoList, versionOf,
    cleanResult, S, onTool, stop() { S.link = "off"; clearTimeout(connectTimer); connectTimer = null; dropSocket("stop"); } };
}
