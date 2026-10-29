import type { components } from "./openapi";

export type { components, paths } from "./openapi";

type Schemas = components["schemas"];

export type LiveResponse = Schemas["LiveResponse"];
export type ReadyResponse = Schemas["ReadyResponse"];
export type DependencyStatus = Schemas["DependencyStatus"];

/** Error envelope returned by every failing API call. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: unknown;
    request_id: string | null;
  };
}
