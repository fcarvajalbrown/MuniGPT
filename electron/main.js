// main.js — MuniGPT desktop shell.
//
// Responsibilities:
//   1. Show a splash window immediately.
//   2. Spawn the local Python backend (uvicorn) and reap it on exit.
//   3. Poll GET /status until the backend reports ready.
//   4. Load the built frontend (frontend/dist) into the main window, close splash.
//
// Security: the main window runs with contextIsolation on and nodeIntegration
// off; the renderer only receives the backend URL via preload additionalArguments.
//
// Headless smoke mode (MUNIGPT_SMOKE=1): load the splash in an offscreen window,
// print SPLASH_OK once it renders, then quit — no backend, no visible GUI. This
// is the automated "boots to splash" acceptance check.

const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");
const fs = require("fs");

const BACKEND_HOST = "127.0.0.1";
const BACKEND_PORT = Number(process.env.MUNIGPT_PORT || 8000);
const API_BASE = `http://${BACKEND_HOST}:${BACKEND_PORT}`;
const SMOKE = process.env.MUNIGPT_SMOKE === "1";

let splashWin = null;
let mainWin = null;
let backendProc = null;

// ── Path resolution (dev tree vs packaged app) ───────────────────────────────────

function backendDir() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "backend")
    : path.join(__dirname, "..", "backend");
}

function frontendIndex() {
  // frontend/dist is bundled into the app (asar) via the electron-builder "files"
  // globs, so it sits next to electron/ in both the dev tree and the packaged app.
  return path.join(__dirname, "..", "frontend", "dist", "index.html");
}

function splashFile() {
  return path.join(__dirname, "splash.html");
}

// ── Splash ───────────────────────────────────────────────────────────────────────

function createSplash() {
  splashWin = new BrowserWindow({
    width: 440,
    height: 300,
    frame: false,
    resizable: false,
    center: true,
    show: !SMOKE, // offscreen in smoke mode
    backgroundColor: "#0f1420",
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  return splashWin.loadFile(splashFile());
}

function setSplashStatus(text) {
  if (splashWin && !splashWin.isDestroyed()) {
    const safe = JSON.stringify(text);
    splashWin.webContents
      .executeJavaScript(`{const el=document.getElementById("status"); if(el) el.textContent=${safe};}`)
      .catch(() => {});
  }
}

// ── Backend process ──────────────────────────────────────────────────────────────

function startBackend() {
  const py = process.env.MUNIGPT_PYTHON || "python";
  backendProc = spawn(
    py,
    ["-m", "uvicorn", "main:app", "--host", BACKEND_HOST, "--port", String(BACKEND_PORT)],
    { cwd: backendDir(), stdio: "ignore", windowsHide: true },
  );
  backendProc.on("error", (err) => {
    setSplashStatus(`No se pudo iniciar el backend: ${err.message}`);
  });
}

function stopBackend() {
  if (backendProc && !backendProc.killed) {
    // Kill the process tree (uvicorn spawns llama-server children).
    if (process.platform === "win32") {
      spawn("taskkill", ["/pid", String(backendProc.pid), "/T", "/F"], { stdio: "ignore" });
    } else {
      try {
        process.kill(-backendProc.pid, "SIGTERM");
      } catch {
        backendProc.kill("SIGTERM");
      }
    }
    backendProc = null;
  }
}

function checkStatusOnce() {
  return new Promise((resolve) => {
    const req = http.get(`${API_BASE}/status`, { timeout: 3000 }, (res) => {
      let body = "";
      res.on("data", (c) => (body += c));
      res.on("end", () => {
        try {
          const j = JSON.parse(body);
          resolve(j.status === "ok" && j.ready === true);
        } catch {
          resolve(false);
        }
      });
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitForBackend(timeoutMs = 180000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await checkStatusOnce()) return true;
    setSplashStatus("Cargando el modelo local, esto puede tardar...");
    await new Promise((r) => setTimeout(r, 1500));
  }
  return false;
}

// ── Main window ────────────────────────────────────────────────────────────────

function createMainWindow() {
  mainWin = new BrowserWindow({
    width: 1100,
    height: 760,
    minWidth: 720,
    minHeight: 480,
    backgroundColor: "#0f1420",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      additionalArguments: [
        `--munigpt-api-base=${API_BASE}`,
        `--munigpt-version=${app.getVersion()}`,
      ],
    },
  });

  mainWin.once("ready-to-show", () => {
    mainWin.show();
    if (splashWin && !splashWin.isDestroyed()) splashWin.close();
    splashWin = null;
  });

  mainWin.on("closed", () => {
    mainWin = null;
  });

  return mainWin.loadFile(frontendIndex());
}

// ── Lifecycle ──────────────────────────────────────────────────────────────────

async function boot() {
  await createSplash();

  if (SMOKE) {
    // Splash rendered in an offscreen window -> acceptance signal, then quit.
    // Packaged GUI apps don't attach stdout, so also drop a marker file when a
    // path is provided (used by the packaged-exe boot check).
    console.log("SPLASH_OK");
    const marker = process.env.MUNIGPT_SMOKE_FILE;
    if (marker) {
      try {
        fs.writeFileSync(marker, "SPLASH_OK\n");
      } catch {}
    }
    setTimeout(() => app.quit(), 300);
    return;
  }

  startBackend();
  const ok = await waitForBackend();
  if (!ok) {
    setSplashStatus("El backend no respondió a tiempo. Revisa la instalación.");
    return; // leave splash up with the error; user can close the app
  }
  await createMainWindow();
}

app.whenReady().then(boot);

app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", stopBackend);
app.on("quit", stopBackend);

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) boot();
});
