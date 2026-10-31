"use client";

import { type ApiResult, parseResult } from "./api-result";

/**
 * Browser-side API client. Requests go to the same origin (`/api/v1/...`), which Next
 * rewrites to the API, so the HttpOnly session cookie is sent automatically and never
 * exposed to scripts. Mutations echo the CSRF cookie in the `x-csrf-token` header.
 */
function readCookie(name: string): string | null {
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

export async function apiRequest<T>(
  path: string,
  init: { method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE"; body?: unknown } = {},
): Promise<ApiResult<T>> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = {};
  if (init.body !== undefined) headers["content-type"] = "application/json";
  if (method !== "GET") {
    const csrf = readCookie("__Host-salesiq_csrf") ?? readCookie("salesiq_csrf");
    if (csrf) headers["x-csrf-token"] = csrf;
  }
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, {
      method,
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      credentials: "same-origin",
    });
  } catch {
    return {
      ok: false,
      status: null,
      code: "unreachable",
      message: "Could not reach the server. Check your connection and try again.",
      requestId: null,
    };
  }
  const body: unknown = res.status === 204 ? null : await res.json().catch(() => null);
  return parseResult<T>(res.status, body, res.headers.get("x-request-id"));
}
