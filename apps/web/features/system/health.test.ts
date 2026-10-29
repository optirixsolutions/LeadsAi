import { describe, expect, it } from "vitest";

import { parseResult } from "@/lib/api-result";

import { summarizeReadiness } from "./health";

describe("summarizeReadiness", () => {
  it("reports all components healthy", () => {
    const s = summarizeReadiness({
      ok: true,
      status: 200,
      data: {
        status: "ok",
        dependencies: {
          database: { status: "ok", latency_ms: 1.2 },
          redis: { status: "ok", latency_ms: 0.4 },
        },
      },
    });
    expect(s.overall).toBe("ok");
    expect(s.components.map((c) => c.name)).toEqual(["API", "PostgreSQL", "Redis"]);
  });

  it("marks degraded when a dependency fails", () => {
    const s = summarizeReadiness({
      ok: true,
      status: 503,
      data: {
        status: "degraded",
        dependencies: {
          database: { status: "error", error: "OperationalError" },
          redis: { status: "ok", latency_ms: 0.4 },
        },
      },
    });
    expect(s.overall).toBe("degraded");
    expect(s.components[1]).toMatchObject({ health: "down", detail: "Check failed (OperationalError)" });
  });

  it("reports the API as down when unreachable", () => {
    const s = summarizeReadiness({
      ok: false,
      status: null,
      code: "unreachable",
      message: "API unreachable",
      requestId: null,
    });
    expect(s.overall).toBe("down");
    expect(s.error).toBe("API unreachable");
  });
});

describe("parseResult", () => {
  it("unwraps the error envelope", () => {
    const r = parseResult(404, { error: { code: "not_found", message: "Nope", details: null, request_id: "r1" } }, "h");
    expect(r).toEqual({ ok: false, status: 404, code: "not_found", message: "Nope", requestId: "r1" });
  });

  it("falls back when the body is not an envelope", () => {
    const r = parseResult(502, null, "hdr");
    expect(r).toMatchObject({ ok: false, code: "http_error", requestId: "hdr" });
  });
});
