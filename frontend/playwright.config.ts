import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  timeout: 30000,
  retries: 0,
  use: {
    baseURL: "http://localhost:3000",
    headless: true,
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { browserName: "chromium" } },
  ],
  // Start both backend API and frontend dev server
  webServer: [
    {
      command: "cd .. && .venv/bin/python -m uvicorn nuri.api.main:app --host 0.0.0.0 --port 8001",
      port: 8001,
      timeout: 15000,
      reuseExistingServer: true,
    },
    {
      command: "npm run dev",
      port: 3000,
      timeout: 30000,
      reuseExistingServer: true,
    },
  ],
});
