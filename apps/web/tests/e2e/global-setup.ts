import { spawn } from "node:child_process";
import { resolve } from "node:path";

/**
 * Runs a real background worker for the suite. It has no port for Playwright's `webServer` to
 * watch. The API has no model routes, so model calls get a real 404 at once, which keeps these
 * tests quick and independent of a model server. The Python API tests cover real models.
 */
export default function globalSetup(): () => void {
  const api = resolve(__dirname, "../../../api");
  const python = process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python";
  const apiUrl = process.env.SALESIQ_API_URL ?? "http://127.0.0.1:8000";
  const worker = spawn(resolve(api, python), ["-m", "app.tasks.worker"], {
    cwd: api,
    stdio: "ignore",
    env: {
      ...process.env,
      SALESIQ_ENVIRONMENT: "test",
      SALESIQ_MAILER: "disabled",
      SALESIQ_LOG_LEVEL: "WARNING",
      SALESIQ_OLLAMA_BASE_URL: `${apiUrl}/v1`,
      SALESIQ_WORKER_POLL_SECONDS: "0.5",
    },
  });
  return () => {
    worker.kill();
  };
}
