import { defineConfig, devices } from "@playwright/test";

// Runs a production web build against a real API and database. Locally this uses the
// docker compose Postgres/Redis; CI provides them as services. Tests create their own
// uniquely named users and organizations, so they never depend on existing data.
const apiUrl = new URL(process.env.SALESIQ_API_URL ?? "http://127.0.0.1:8000");
const apiEnv = {
  SALESIQ_ENVIRONMENT: "test",
  SALESIQ_MAILER: "disabled",
  SALESIQ_LOG_LEVEL: "WARNING",
  SALESIQ_WEB_BASE_URL: "http://127.0.0.1:3100",
  // Every e2e browser shares one IP; rate limiting itself is covered by API tests.
  SALESIQ_LOGIN_RATE_LIMIT_PER_MINUTE: "1000",
  ...(process.env.SALESIQ_DATABASE_URL ? { SALESIQ_DATABASE_URL: process.env.SALESIQ_DATABASE_URL } : {}),
  ...(process.env.SALESIQ_REDIS_URL ? { SALESIQ_REDIS_URL: process.env.SALESIQ_REDIS_URL } : {}),
};

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: "http://127.0.0.1:3100", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    {
      // Must match the URL the web build's rewrites were built with. If another project holds
      // :8000, build and test with SALESIQ_API_URL set to a free port; a server already on the
      // port is reused, so a stranger's would otherwise answer these tests.
      command: `uv run --project ../api uvicorn app.main:app --app-dir ../api --host 127.0.0.1 --port ${apiUrl.port}`,
      url: `${apiUrl.origin}/api/v1/health/live`,
      env: apiEnv,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: "pnpm exec next start --port 3100",
      url: "http://127.0.0.1:3100/login",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
