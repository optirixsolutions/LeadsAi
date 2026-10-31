import { expect, test } from "@playwright/test";

import { signUpWithOrg } from "./helpers";
import { SINK_PORT } from "./global-setup";

test("connect a real mail server, check it, and remove it", async ({ page }) => {
  await signUpWithOrg(page, "Integrations E2E");
  await page.goto("/integrations");
  await expect(page.getByRole("heading", { name: "AI models" })).toBeVisible();

  await page.getByRole("button", { name: "Connect" }).click();
  await expect(page.getByText("Enter the mail server's address.")).toBeVisible();

  await page.getByLabel("Mail server").fill("127.0.0.1");
  await page.getByLabel("Port").fill(String(SINK_PORT));
  await page.getByLabel("Use STARTTLS").uncheck();
  await page.getByRole("button", { name: "Connect" }).click();
  await expect(page.getByTestId("webhook-secret")).toContainText("whsec_");
  await expect(page.getByText("Not checked yet")).toBeVisible();

  await page.getByRole("button", { name: "Check connection" }).click();
  await expect(page.getByText("Working")).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("webhook-secret")).toHaveCount(0);

  await page.getByRole("button", { name: "Remove" }).click();
  await page.getByRole("button", { name: "Remove Email provider" }).click();
  await expect(page.getByLabel("Mail server")).toBeVisible();
});

test("a plan's limits are shown and enforced", async ({ page }) => {
  await signUpWithOrg(page, "Plans E2E");
  await page.goto("/settings/usage");
  await expect(page.getByRole("heading", { name: "Unlimited plan" })).toBeVisible();
  await expect(page.getByText("No payment provider is connected")).toBeVisible();

  await page.getByLabel("Plan (development only)").selectOption("free");
  await expect(page.getByRole("heading", { name: "Free plan" })).toBeVisible();
  await expect(page.getByText("1 of 3")).toBeVisible();

  await page.goto("/integrations");
  await expect(page.getByText("Your plan does not include integrations.")).toBeVisible();
  await expect(page.getByLabel("Mail server")).toHaveCount(0);
});
