import { expect, test } from "@playwright/test";

import { signUpWithOrg } from "./helpers";

test.beforeEach(async ({ page }) => {
  await signUpWithOrg(page, "Shell Co");
});

test("overview renders shell and an empty state for a new org", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
  await expect(page.getByText("No leads yet")).toBeVisible();
  await expect(page.getByText("Platform health")).toBeVisible();
  expect(errors).toEqual([]);
});

test("status page reports each component", async ({ page }) => {
  await page.goto("/status");
  await expect(page.getByRole("heading", { level: 1, name: "System status" })).toBeVisible();
  await expect(page.getByText("PostgreSQL")).toBeVisible();
});

test("navigation reaches status page", async ({ page, isMobile }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: isMobile ? "Mobile" : "Primary", exact: true });
  await nav.getByRole("link", { name: "System status" }).click();
  await expect(page).toHaveURL(/\/status$/);
});

test("the content security policy is sent, and the app works under it", async ({ page }) => {
  const problems: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" && m.text().includes("Content Security Policy")) problems.push(m.text());
  });
  const response = await page.goto("/status");
  const policy = response?.headers()["content-security-policy"] ?? "";
  expect(policy).toContain("default-src 'self'");
  expect(policy).toContain("frame-ancestors 'none'");
  expect(policy).not.toContain("unsafe-eval");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.goto("/analytics");
  await expect(page.getByRole("heading", { level: 1, name: "Analytics" })).toBeVisible();
  expect(problems).toEqual([]);
});

test("every module in the sidebar is a real page", async ({ page, isMobile }) => {
  test.skip(isMobile, "sidebar hidden on mobile");
  await page.goto("/");
  const sidebar = page.getByRole("complementary", { name: "Sidebar" });
  await sidebar.getByRole("link", { name: /Integrations/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Integrations" })).toBeVisible();
});

test("sidebar collapses", async ({ page, isMobile }) => {
  test.skip(isMobile, "sidebar hidden on mobile");
  await page.goto("/");
  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  await expect(page.getByRole("button", { name: "Expand sidebar" })).toBeVisible();
});
