# MuniGPT — 1.0 Definition of Done (loop target)

Source of truth for the autonomous build loop. "Done" = every item in section A
checked and verified by the stated acceptance check. Section B is explicitly
OUT of the unattended loop's scope and requires Felipe's input or missing assets.

Grounded in `docs/MuniGPT_PRD_v0.1.pdf` (v0.2), milestones M1–M5 and FR-01…FR-15.
Nothing here is invented: items map to PRD requirement IDs.

---

## A. In scope for the unattended loop (buildable AND verifiable on this machine)

### A1. RAG / backend acceptance (M1 — mostly done, close it out)
- [x] `FR-07` local audit log for `/search`: append `{timestamp, query, resultCount}`
      to a local logfile. (Implemented in `main.py`: `_append_search_audit` ->
      `backend/logs/search_audit.log`, one JSON line per outbound query.)
- [x] M1 acceptance: a repeatable script that runs ~15 Spanish test queries through
      `retrieve()` and asserts non-empty, cited results. Committed under `backend/`.
      (`backend/acceptance_m1.py` — 15/15 PASS, exit 0.)
- [x] Minimal pytest suite for `rag.retrieve` dedup/merge + `ingest` chunking
      (no test suite exists today).
      Acceptance: `pytest` green; the 15-query script prints citations.
      (`backend/tests/` — 16 passed; acceptance script prints citations per query.)

### A2. Frontend (M2 — not started)
- [x] React + Vite + TypeScript app under `frontend/` per `scaffold.ini`
      (`.tsx` instead of `.jsx` since the checklist mandates TypeScript).
- [x] `FR-04` SSE streaming chat (consumes `/chat` token events) — `src/api.ts`
      `streamChat` (fetch + ReadableStream SSE parser), rendered in `Chat.tsx`.
- [x] `FR-03`/`FR-12` citation display (source filename + chunk) — `Message.tsx`.
- [x] `FR-05` web-search toggle pill — `SearchToggle.tsx`.
- [x] Municipality branding pulled from `GET /config` — `App.tsx`.
      Acceptance: `npm run build` clean (tsc + vite, 31 modules); preview server
      renders (`smoke:render` PASS: 200, #root, React bundle); scripted query
      against the running backend streams tokens + citations (`smoke:chat` PASS:
      5 citations, 330 tokens).

### A3. Electron shell (M3 — not started)
- [x] `electron/` main + preload + splash per `scaffold.ini` (`main.js`,
      `preload.js`, `splash.html`). contextIsolation on, nodeIntegration off.
- [x] Spawns/reaps the Python backend; polls `/status`; loads the built frontend.
      (`startBackend`/`stopBackend` kill the uvicorn+llama-server tree; `waitForBackend`
      polls `/status`; `createMainWindow` loads `frontend/dist` and injects the
      backend URL via preload `additionalArguments`.)
- [x] Root `package.json`; desktop-shortcut config (NSIS `createDesktopShortcut`).
      Acceptance (PARTIAL — headless): `electron-builder --dir` succeeds (exit 0,
      `electron/out/win-unpacked/MuniGPT.exe`) and the app boots to splash
      (verified via offscreen smoke: dev `SPLASH_OK` + packaged-exe marker file).
      Full GUI walkthrough is deferred to a manual check.
      Note: `win.signAndEditExecutable: false` is set because this machine is
      non-admin with Developer Mode off, so electron-builder's winCodeSign cache
      (macOS symlinks) cannot extract; disabling exe signing/rcedit editing skips
      it. The signed installer with icon/metadata is B3 (out of scope).

### A4. Docs + packaging prep
- [x] Author the Inno Setup `.iss` script (FR-14) — SCRIPT ONLY, see B3.
      (`installer/munigpt.iss`; git-tracked via a `!installer/munigpt.iss`
      exception to the `*.iss` ignore rule.)
- [x] Refresh `README.md` (it still says Ollama; the code uses bundled llama.cpp).
      Acceptance: `.iss` lints for obvious path errors; README matches the code.
      (ISCC.exe turned out to be installed, so the script was compile-validated for
      real: a temp copy with the multi-GB assets excluded compiled clean, exit 0 —
      all directives/paths valid. Building the full ~8 GB installer .exe remains B3,
      out of scope. README rewritten to bundled llama.cpp, real tree, model tiers,
      endpoints, and test commands.)

---

## B. OUT of the unattended loop — gated on Felipe or missing assets

### B1. Offline licensing (FR-08) — DONE (design decided with Felipe)
Resolved and implemented after an interactive design pass. The scheme was NOT
invented unattended: Felipe chose each axis. Shipped design:
- **Ed25519 signatures** (not the earlier HMAC sketch): the private signing key is
  held offline by Instituto Igualdad; only the public key ships in the client, so a
  reverse-engineered client cannot forge licenses.
- **No hardware binding** for 1.0 — avoids licenses bricking on reimage/hardware
  swaps; forgery is still impossible via the signature.
- **Soft enforcement** — status is surfaced (UI banner) but no endpoint blocks.
- **Verification in the Python backend** via `cryptography` (already a dep).
Components: `backend/license.py` (verifier, embedded public key),
`tools/issue_license.py` (issuer-only minting tool, NOT shipped in the installer),
`main.py` (verifies `config.json` `licenseKey` at startup; `/status` + `/config`
expose status), frontend banner in `App.tsx`, and `backend/tests/test_license.py`.
Acceptance: `pytest` green (29 passed); end-to-end mint→verify returns `valid`.
The issuing private key is held offline by Felipe and is not in the repo.

### B2. Real end-to-end chat verification
Default 4B model is not downloaded (only Qwen3-1.7B is present). The loop can
smoke-test generation on the 1.7B but cannot verify the shipping model.

### B3. Compiled installer .exe (FR-14) + M4 pilot
`iscc` (Inno Setup) is not installed and the 8 GB bundle assets aren't all present,
so the `.exe` can be scripted but not built/verified here. M4 (on-site pilot at
municipalities) is not a coding task.

---

## Definition of "done" for THIS loop
Section A fully checked and verified → this is a **1.0 release candidate
(code-complete for M2+M3, FR-07, tests, docs, installer script)**, explicitly
minus B1–B3. On completion: commit, then hibernate.
