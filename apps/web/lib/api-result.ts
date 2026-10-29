import type { ApiErrorBody } from "@salesiq/contracts";

export type ApiResult<T> =
  | { ok: true; data: T; status: number }
  | {
      ok: false;
      status: number | null;
      code: string;
      message: string;
      requestId: string | null;
      details?: unknown;
    };

/** Normalize an HTTP response into a typed result using the API's error envelope. */
export function parseResult<T>(
  status: number,
  body: unknown,
  requestId: string | null,
): ApiResult<T> {
  if (status >= 200 && status < 300) return { ok: true, data: body as T, status };
  const err = (body as ApiErrorBody | null)?.error;
  return {
    ok: false,
    status,
    code: err?.code ?? "http_error",
    message: err?.message ?? `Request failed with status ${status}`,
    requestId: err?.request_id ?? requestId,
    ...(err?.details != null ? { details: err.details } : {}),
  };
}
