/// <reference types="vitest/config" />
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `dev` proxies /api to the local FastAPI (real mode: VITE_USE_MOCK=false); until a
// backend is up the UI runs against mock fixtures (src/dev/mockApi.ts).
export default defineConfig({
  plugins: [react()],
  // Two HTML entries: the builder studio (index.html) and the operations dashboard
  // (dashboard.html). Both must be emitted so the header cross-links resolve in a
  // production build, not just under the dev server.
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        dashboard: resolve(__dirname, "dashboard.html"),
      },
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
