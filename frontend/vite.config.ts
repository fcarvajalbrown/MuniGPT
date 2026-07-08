import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend runs on http://127.0.0.1:8000. In dev we proxy the API routes so
// the app can call same-origin paths (/chat, /config, ...) with no CORS dance.
// In the packaged app the Electron shell serves these files and the backend is
// on the same host, so relative paths keep working. `base: "./"` makes the built
// asset URLs relative, which is required when Electron loads index.html via file://.
const API_TARGET = process.env.MUNIGPT_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/chat": { target: API_TARGET, changeOrigin: true },
      "/search": { target: API_TARGET, changeOrigin: true },
      "/status": { target: API_TARGET, changeOrigin: true },
      "/config": { target: API_TARGET, changeOrigin: true },
      "/ingest": { target: API_TARGET, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
