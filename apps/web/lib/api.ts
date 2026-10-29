import "server-only";

import type { components, ReadyResponse } from "@salesiq/contracts";
import { cookies } from "next/headers";

import { type ApiResult, parseResult } from "./api-result";

/**
 * Server-side API client. Forwards the caller's cookies so the API authenticates the same
 * session. The API base URL is a server-only env var and is never bundled to the browser.
 */
export const API_URL = process.env.SALESIQ_API_URL ?? "http://127.0.0.1:8000";

export type MeOut = components["schemas"]["MeOut"];

interface RawResponse {
  status: number;
  body: unknown;
  requestId: string | null;
}

async function request(path: string): Promise<RawResponse | ApiResult<never>> {
  try {
    const jar = await cookies();
    const res = await fetch(`${API_URL}${path}`, {
      cache: "no-store",
      headers: { cookie: jar.toString() },
      signal: AbortSignal.timeout(5000),
    });
    const body: unknown = await res.json().catch(() => null);
    return { status: res.status, body, requestId: res.headers.get("x-request-id") };
  } catch (err) {
    const timedOut = err instanceof Error && err.name === "TimeoutError";
    return {
      ok: false,
      status: null,
      code: "unreachable",
      message: timedOut ? "API timed out" : "API unreachable",
      requestId: null,
    };
  }
}

export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  const r = await request(path);
  return "ok" in r ? r : parseResult<T>(r.status, r.body, r.requestId);
}

/** Readiness answers 503 with a full per-dependency body when degraded; surface that body. */
export async function getReadiness(): Promise<ApiResult<ReadyResponse>> {
  const r = await request("/api/v1/health/ready");
  if ("ok" in r) return r;
  if (r.status === 503 && (r.body as ReadyResponse | null)?.dependencies) {
    return { ok: true, data: r.body as ReadyResponse, status: 503 };
  }
  return parseResult<ReadyResponse>(r.status, r.body, r.requestId);
}
