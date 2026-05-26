import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    exclude: ["**/node_modules/**", "**/dist/**", "**/.pytest_cache/**", "**/artifacts/**", "**/cache/**"],
    globals: true,
    include: ["frontend/src/**/*.test.ts", "frontend/src/**/*.test.tsx"],
    setupFiles: ["./frontend/src/test-setup.ts"],
  },
});
