import { expect, test } from "@playwright/test";

import { signUpWithOrg } from "./helpers";

test("agents list their limits, and a run reports what happened", async ({ page }) => {
  await signUpWithOrg(page, "Agents E2E");
  await page.goto("/agents");
  await expect(page.getByText("At most 6 tool calls and 5 model turns.").first()).toBeVisible();
  await expect(page.getByText("get_pipeline_summary", { exact: true })).toBeVisible();
  await expect(page.getByText("No runs yet")).toBeVisible();

  await page.getByRole("button", { name: "Run pipeline analyst" }).click();
  await expect(page.getByRole("heading", { name: "Agent run" })).toBeVisible();
  // This suite's model endpoint answers 404, so the run reports that plainly.
  await expect(page.getByText("The configured model is not installed")).toBeVisible({ timeout: 25_000 });

  await page.getByRole("link", { name: "← Agents" }).click();
  await expect(page.getByRole("link", { name: /Pipeline analyst/ })).toBeVisible();
});

test("a lead's page starts the agents bound to that lead", async ({ page }) => {
  await signUpWithOrg(page, "Lead Agents E2E");
  await page.goto("/leads/new");
  await page.getByLabel("First name").fill("Tess");
  await page.getByRole("button", { name: "Create lead" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /Tess/ })).toBeVisible();
  await page.getByRole("button", { name: "Run research agent" }).click();
  await expect(page.getByRole("heading", { name: "Agent run" })).toBeVisible();
  await expect(page.getByRole("link", { name: "View lead" })).toBeVisible();
});

test("a token is shown once and can be revoked", async ({ page }) => {
  await signUpWithOrg(page, "Tokens E2E");
  await page.goto("/settings/tokens");
  await expect(page.getByText("No tokens yet")).toBeVisible();

  await page.getByRole("button", { name: "Create token" }).click();
  await expect(page.getByText("Give the token a name")).toBeVisible();

  await page.getByLabel("Name").fill("My client");
  await page.getByRole("button", { name: "Create token" }).click();
  await expect(page.getByTestId("new-token")).toContainText("siq_");
  await expect(page.getByText("My client")).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("new-token")).toHaveCount(0);

  await page.getByRole("button", { name: "Revoke" }).click();
  await page.getByRole("button", { name: "Revoke My client" }).click();
  await expect(page.getByText(/revoked/)).toBeVisible();
});
