// preload.js — runs in an isolated context before the frontend loads.
//
// Exposes a tiny, read-only surface to the renderer via contextBridge. The
// renderer talks to the backend over HTTP; in the packaged app it is loaded from
// file:// and therefore needs the absolute local backend URL (relative paths
// only work behind the Vite dev proxy). We pass that URL in as a command-line
// argument from main.js (webPreferences.additionalArguments) and read it here.
// nodeIntegration stays off and contextIsolation stays on (see main.js).

const { contextBridge } = require("electron");

function argValue(prefix) {
  const found = process.argv.find((a) => a.startsWith(prefix));
  return found ? found.slice(prefix.length) : "";
}

contextBridge.exposeInMainWorld("munigpt", {
  // "" in dev (relative paths via the Vite proxy); absolute local URL when packaged.
  apiBase: argValue("--munigpt-api-base="),
  version: argValue("--munigpt-version="),
});
