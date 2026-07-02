/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Phase 1: the backend (workstreams 2–6) is not wired yet, so `dev` proxies
// /api to a local FastAPI once it exists. Until then the UI runs against mock
// fixtures (see src/dev/mockApi.ts).
export default defineConfig({
  plugins: [react()],
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
