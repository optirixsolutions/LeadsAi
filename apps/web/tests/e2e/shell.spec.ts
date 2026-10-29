import { expect, test } from "@playwright/test";

test("overview renders shell and honest empty state", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
  await expect(page.getByText("No pipeline data yet")).toBeVisible();
  await expect(page.getByText("Platform health")).toBeVisible();
  expect(errors).toEqual([]);
});

test("status page reports each component", async ({ page }) => {
  await page.goto("/status");
  await expect(page.getByRole("heading", { level: 1, name: "System status" })).toBeVisible();
  // API row is always present: either live, or reported unreachable with an alert.
  await expect(page.getByText("API", { exact: true })).toBeVisible();
});

test("navigation reaches status page", async ({ page, isMobile }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: isMobile ? "Mobile" : "Primary", exact: true });
  await nav.getByRole("link", { name: "System status" }).click();
  await expect(page).toHaveURL(/\/status$/);
});

test("unbuilt modules are not links", async ({ page, isMobile }) => {
  test.skip(isMobile, "sidebar hidden on mobile");
  await page.goto("/");
  const sidebar = page.getByRole("complementary", { name: "Sidebar" });
  await expect(sidebar.getByRole("link", { name: /Leads/ })).toHaveCount(0);
  await expect(sidebar.getByText("Leads")).toBeVisible();
});

test("sidebar collapses", async ({ page, isMobile }) => {
  test.skip(isMobile, "sidebar hidden on mobile");
  await page.goto("/");
  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  await expect(page.getByRole("button", { name: "Expand sidebar" })).toBeVisible();
});
