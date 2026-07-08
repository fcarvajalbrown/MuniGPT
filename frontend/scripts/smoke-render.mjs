// smoke-render.mjs — A2 "dev server renders" acceptance (headless).
//
// Run against a RUNNING dev or preview server (default http://localhost:4173):
//
//   npm run preview -- --port 4173 --strictPort   # in one terminal
//   node scripts/smoke-render.mjs                  # in another
//
// Confirms the served document mounts the React root (#root) and that its entry
// bundle is served and looks like the built app (contains createRoot). A full
// visual walkthrough in a real window is a manual check.
//
// Note: uses "localhost" (not 127.0.0.1) because Vite's preview binds to the
// hostname, which on Windows resolves to IPv6 ::1.

const base = process.argv[2] ?? "http://localhost:4173";

let code = 0;
try {
  const res = await fetch(base + "/");
  const html = await res.text();
  const hasRoot = /id="root"/.test(html);
  const bundle = html.match(/assets\/index-[^"]+\.js/)?.[0];
  console.log(`GET / -> ${res.status}; hasRoot=${hasRoot}; bundle=${bundle ?? "none"}`);

  if (!res.ok || !hasRoot || !bundle) {
    console.error("FAIL: served HTML missing #root or entry bundle");
    code = 1;
  } else {
    const js = await fetch(`${base}/${bundle}`);
    const body = await js.text();
    const reactApp = body.includes("createRoot");
    console.log(`GET /${bundle} -> ${js.status}; bytes=${body.length}; reactApp=${reactApp}`);
    if (!js.ok || !reactApp) {
      console.error("FAIL: entry bundle not served or not the built app");
      code = 1;
    } else {
      console.log("A2 render smoke: PASS");
    }
  }
} catch (err) {
  console.error("FAIL:", err.message);
  code = 1;
}

// Let the process exit naturally (undici keep-alive sockets close on their own);
// forcing process.exit() here races libuv teardown on Windows.
process.exitCode = code;
