import { defineConfig, devices } from "@playwright/test";

// Runs against a production build. The API is optional: tests assert the UI reports
// its state honestly whether or not the API is up.
export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: "http://127.0.0.1:3100", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: "pnpm exec next start --port 3100",
    url: "http://127.0.0.1:3100/status",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
