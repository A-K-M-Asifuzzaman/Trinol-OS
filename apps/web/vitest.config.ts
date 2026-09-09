import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    // Matches lib/api/client.ts's browser path: a relative fetch("/api/...")
    // resolves against this origin, same as it would resolve against the
    // real app's own origin in production (ARCHITECTURE.md §1 — the whole
    // point of the same-origin /api/* rewrite).
    environmentOptions: {
      jsdom: { url: "http://localhost:3000" },
    },
    setupFiles: ["./tests/setup.ts"],
    globals: true,
    // e2e/ is Playwright's own suite (playwright.config.ts), a different
    // test runner and global `test` function — vitest's default include
    // glob would otherwise pick up e2e/*.spec.ts too and fail immediately.
    exclude: ["**/node_modules/**", "e2e/**"],
  },
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "."),
    },
  },
});
