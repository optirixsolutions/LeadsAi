import { expect, test } from "@playwright/test";

import { signUpWithOrg, uniqueEmail } from "./helpers";

test("analytics count what happened, and Overview shows what is waiting", async ({ page }) => {
  await signUpWithOrg(page, "Analytics E2E");
  await page.goto("/analytics");
  await expect(page.getByText("Nothing to count yet")).toBeVisible();

  await page.goto("/leads/new");
  await page.getByLabel("First name").fill("Tess");
  await page.getByLabel("Email").fill(uniqueEmail());
  await page.getByRole("button", { name: "Create lead" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /Tess/ })).toBeVisible();
  await page.getByRole("button", { name: "Write a draft" }).click();
  await page.getByLabel("Subject").fill("Hello");
  await page.getByLabel("Message").fill("A short note");
  await page.getByRole("button", { name: "Save draft" }).click();
  await page.getByRole("button", { name: "Ask for approval" }).click();
  await expect(page.getByText("Waiting for a decision")).toBeVisible();

  await page.goto("/analytics?days=7");
  await expect(page.getByRole("link", { name: "7 days" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("figure").getByText("Leads added").first()).toBeVisible();
  await expect(page.getByText("Not scored yet")).toBeVisible();
  await expect(page.getByText("Not proof they reached an inbox")).toBeVisible();
  await expect(page.getByText("Awaiting approval")).toBeVisible();

  await page.goto("/");
  await page.getByRole("link", { name: /draft waiting for approval/ }).click();
  await expect(page).toHaveURL(/\/outreach\/approvals$/);
});

test("the leads table offers a fit filter", async ({ page }) => {
  await signUpWithOrg(page, "Fit E2E");
  await page.goto("/leads/new");
  await page.getByLabel("First name").fill("Tess");
  await page.getByRole("button", { name: "Create lead" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /Tess/ })).toBeVisible();
  await page.goto("/leads");
  await page.getByLabel("Fit").selectOption("high");
  await expect(page).toHaveURL(/fit=high/);
  await expect(page.getByRole("link", { name: /Tess/ })).toHaveCount(0);
  await page.getByLabel("Fit").selectOption("none");
  await expect(page.getByRole("link", { name: /Tess/ })).toBeVisible();
});
