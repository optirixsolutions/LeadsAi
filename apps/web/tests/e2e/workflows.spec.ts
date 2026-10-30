import { expect, test } from "@playwright/test";

import { signUpWithOrg } from "./helpers";

async function leadWithIcp(page: import("@playwright/test").Page, name: string) {
  await signUpWithOrg(page, `${name} E2E`);
  await page.goto("/settings/icp");
  await page.getByLabel("Target job titles").fill("VP Sales");
  await page.getByRole("button", { name: "Save new version" }).click();
  await expect(page.getByText("Saved as version 1")).toBeVisible();

  await page.goto("/leads/new");
  await page.getByLabel("First name").fill(name);
  await page.getByLabel("Title").fill("VP Sales");
  await page.getByRole("button", { name: "Create lead" }).click();
  await expect(page.getByRole("heading", { level: 1, name: new RegExp(name) })).toBeVisible();
}

test("a workflow runs in the background and its steps can be followed", async ({ page }) => {
  await leadWithIcp(page, "Ada");
  await page.getByLabel("Add a research finding").fill("They asked about lead scoring.");
  await page.getByRole("button", { name: "Save finding" }).click();
  await expect(page.getByText("Evidence saved.")).toBeVisible();

  await page.getByRole("button", { name: "Run workflow" }).click();
  const latest = page.getByTestId("latest-run");
  await expect(latest.getByText("Finished")).toBeVisible({ timeout: 25_000 });

  // The score it produced reaches the lead page without a manual reload.
  await expect(page.getByTestId("lead-score")).toContainText("/ 100");

  await latest.getByRole("link", { name: "View run" }).click();
  await expect(page.getByRole("heading", { name: "Workflow run" })).toBeVisible();
  await expect(page.getByText("Score the lead")).toBeVisible();
  // This suite's model endpoint answers 404, so the run says plainly that the brief failed.
  await expect(page.getByText("The model could not produce a usable brief")).toBeVisible();

  await page.getByRole("link", { name: "← Workflows" }).click();
  await expect(page.getByRole("link", { name: /Research and qualification/ })).toBeVisible();
});

test("the system status page reports the background worker", async ({ page }) => {
  await signUpWithOrg(page, "Worker E2E");
  await page.goto("/status");
  await expect(page.getByText("Background worker")).toBeVisible();
  // The page renders on the server once per load, and the worker may still be starting.
  await expect(async () => {
    await page.reload();
    await expect(page.getByText("Reported in within the last 30 seconds")).toBeVisible({ timeout: 1000 });
  }).toPass({ timeout: 20_000 });
});

test("the sidebar links to workflows", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "Sidebar navigation is desktop-only");
  await signUpWithOrg(page, "Nav E2E");
  await page.goto("/");
  await page.getByRole("link", { name: "Workflows" }).click();
  await expect(page.getByText("No runs yet")).toBeVisible();
});
