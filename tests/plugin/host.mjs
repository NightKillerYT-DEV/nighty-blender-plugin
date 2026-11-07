// SPDX-License-Identifier: GPL-3.0-or-later
// A stand-in for Nighty Vault's plugin host, for the plugin's tests: loads plugin/main.js in its own VM context with
// a fake `nighty` (system.info / run, files in a temp folder, storage, panel, mcp.onCall, ui.toast) and Node's own
// WebSocket, fetch and WebCrypto. Every program the plugin runs gets the test's extra environment (a sandbox for
// Blender's user folders), so a test never touches the person's own Blender settings.

import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(HERE, "..", "..");

export function loadPlugin({ dataDir, homeDir, pluginDir = path.join(ROOT, "plugin"), ports, env = {}, pins, source,
  plainCrypto = false, os = "windows" }) {
  fs.mkdirSync(dataDir, { recursive: true });
  const state = { panel: null, panelHandler: null, mcp: null, toasts: [], storage: new Map(), runs: [] };
  const abs = (p) => (path.isAbsolute(p) ? p : path.join(dataDir, p));
  const nighty = {
    app: { version: "0.4.0-test", plugin: { id: "nighty-blender", name: "Nighty Blender", version: "2.0.0" } },
    system: {
      info: async () => ({ os, arch: "x64", homeDir, pluginDir, dataDir, vaultDir: path.join(homeDir, "vault"), appVersion: "0.4.0-test" }),
      run: (program, args = [], opts = {}) => new Promise((resolve) => {
        state.runs.push([program, ...args]);
        execFile(program, args, { cwd: opts.cwd || dataDir, env: { ...process.env, ...env, ...(opts.env || {}) },
          timeout: opts.timeoutMs || 60000, maxBuffer: 64 * 1024 * 1024, windowsHide: true },
        (err, stdout, stderr) => resolve({ code: err ? (typeof err.code === "number" ? err.code : -1) : 0,
          stdout: String(stdout || ""), stderr: String(stderr || (err && !stdout ? err.message : "")),
          timedOut: !!(err && err.killed), truncated: false }));
      }),
      open: async () => {},
    },
    files: {
      read: async (p, o = {}) => fs.readFileSync(abs(p), o.encoding === "base64" ? "base64" : "utf8"),
      write: async (p, data, o = {}) => {
        fs.mkdirSync(path.dirname(abs(p)), { recursive: true });
        const buf = typeof data === "string" ? data : Buffer.from(data instanceof ArrayBuffer ? new Uint8Array(data) : data);
        if (o.append) fs.appendFileSync(abs(p), buf); else fs.writeFileSync(abs(p), buf);
      },
      list: async (p) => fs.readdirSync(abs(p), { withFileTypes: true }).map((d) => {
        const full = path.join(abs(p), d.name);
        const st = fs.statSync(full);
        return { name: d.name, path: full, isDir: d.isDirectory(), size: st.size, modified: st.mtimeMs };
      }),
      stat: async (p) => { const st = fs.statSync(abs(p)); return { name: path.basename(p), path: abs(p), isDir: st.isDirectory(), size: st.size, modified: st.mtimeMs }; },
      exists: async (p) => fs.existsSync(abs(p)),
      mkdir: async (p) => { fs.mkdirSync(abs(p), { recursive: true }); },
      rename: async (a, b) => { fs.renameSync(abs(a), abs(b)); },
      remove: async (p) => {          // the real app sends it to the Recycle Bin; here: a trash folder
        const trash = path.join(dataDir, "..", "recycle-bin");
        fs.mkdirSync(trash, { recursive: true });
        fs.renameSync(abs(p), path.join(trash, path.basename(p) + "-" + Date.now()));
      },
    },
    storage: {
      get: async (k) => (state.storage.has(k) ? state.storage.get(k) : null),
      set: async (k, v) => { state.storage.set(k, v); },
      remove: async (k) => { state.storage.delete(k); },
      keys: async () => [...state.storage.keys()],
    },
    panel: {
      set: async (c) => { state.panel = c; },
      clear: async () => { state.panel = null; },
      onAction: (fn) => { state.panelHandler = fn; },
    },
    mcp: { onCall: (fn) => { if (state.mcp) throw new Error("onCall twice"); state.mcp = fn; } },
    ui: { toast: async (t) => { state.toasts.push(t); } },
    on: () => {},
  };
  const test = { ports, plainCrypto, pins };
  const context = vm.createContext({
    nighty, console, setTimeout, clearTimeout, setInterval, clearInterval, TextEncoder, TextDecoder, atob, btoa,
    crypto: globalThis.crypto, WebSocket: globalThis.WebSocket, fetch: globalThis.fetch, Promise, Uint8Array,
    __NIGHTY_BLENDER_TEST__: test,
  });
  context.globalThis = context;
  let code = source || fs.readFileSync(path.join(pluginDir, "main.js"), "utf8");
  if (pins) code = code.replace(/\/\*@pins\*\/\{[\s\S]*?\}\/\*@end\*\//, "/*@pins*/" + JSON.stringify(pins) + "/*@end*/");
  vm.runInContext(code, context, { filename: "main.js" });
  return { state, test, context, call: (tool, args) => state.mcp(tool, args || {}, { client: "test", sessionId: "t1" }),
    click: (action) => state.panelHandler(action) };
}

export async function until(pred, ms = 20000, what = "condition") {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (await pred()) return true;
    await new Promise((r) => setTimeout(r, 50));
  }
  throw new Error("timed out waiting for " + what);
}

export function panelText(state) {
  return (state.panel ? state.panel.items : []).map((i) => i.text || i.value || i.label || (i.items || []).join(" ")).join(" | ");
}
