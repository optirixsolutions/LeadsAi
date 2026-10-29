import { randomUUID } from "node:crypto";

import { expect, type Page } from "@playwright/test";

export const PASSWORD = "correct horse battery staple";

export function uniqueEmail(): string {
  return `e2e-${randomUUID().slice(0, 8)}@example.com`;
}

async function csrf(page: Page): Promise<string> {
  const cookie = (await page.context().cookies()).find((c) => c.name === "salesiq_csrf");
  if (!cookie) throw new Error("no CSRF cookie; is the user signed in?");
  return cookie.value;
}

/** Register and create an org through the same-origin API, sharing the page's cookies. */
export async function signUpWithOrg(page: Page, orgName = "E2E Org"): Promise<string> {
  const email = uniqueEmail();
  const r = await page.request.post("/api/v1/auth/register", {
    data: { email, password: PASSWORD, display_name: "E2E User" },
  });
  expect(r.status(), await r.text()).toBe(201);
  const org = await page.request.post("/api/v1/organizations", {
    data: { name: orgName },
    headers: { "x-csrf-token": await csrf(page) },
  });
  expect(org.status(), await org.text()).toBe(201);
  return email;
}
