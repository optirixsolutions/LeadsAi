"use client";

import { CURRENT_ORG_COOKIE } from "./org-selection";

/** Remember the selected org (a UI preference; the server re-checks membership). */
export function rememberOrg(orgId: string): void {
  document.cookie = `${CURRENT_ORG_COOKIE}=${encodeURIComponent(orgId)}; path=/; samesite=lax; max-age=31536000`;
}
