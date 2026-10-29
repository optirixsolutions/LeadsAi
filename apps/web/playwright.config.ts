import { defineConfig, devices } from "@playwright/test";

// Runs a production web build against a real API and database. Locally this uses the
// docker compose Postgres/Redis; CI provides them as services. Tests create their own
// uniquely named users and organizations, so they never depend on existing data.
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
      // The web build's rewrites point at :8000 (the default SALESIQ_API_URL).
      command: "uv run --project ../api uvicorn app.main:app --app-dir ../api --host 127.0.0.1 --port 8000",
      url: "http://127.0.0.1:8000/api/v1/health/live",
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
