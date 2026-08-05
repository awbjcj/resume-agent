import path from "node:path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // Unit tests live under src/; e2e/ is Playwright's and must not run in vitest.
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    // Vitest's 5s default is sized for pure unit tests. The heavy tests here
    // drive Base UI portals through `userEvent`, which yields to the event loop
    // on every interaction — so their wall clock tracks worker contention, not
    // their own work: ChatSessionHistory takes ~1.4s alone and ~3.8s under a
    // full parallel run. Measured worst cases under load were SourceManager
    // 4043ms, ChatSessionHistory 3767ms, ModelPicker 3371ms, with a long tail
    // at 2-3s, so roughly ten tests sat close enough to 5s that whichever one
    // drew the unlucky scheduling failed — ChatSessionHistory did so on about
    // one run in three. This budget keeps ~3.7x headroom over that worst case
    // while still failing a genuinely hung test, just later.
    testTimeout: 15000,
  },
});
