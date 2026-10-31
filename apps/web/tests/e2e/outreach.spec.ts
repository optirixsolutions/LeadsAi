import { readFileSync } from "node:fs";

import { expect, type Page, test } from "@playwright/test";

import { signUpWithOrg, uniqueEmail } from "./helpers";
import { SINK_FILE } from "./global-setup";

async function leadWithEmail(page: Page, email: string): Promise<void> {
  await page.goto("/leads/new");
  await page.getByLabel("First name").fill("Tess");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Create lead" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /Tess/ })).toBeVisible();
}

async function configureSending(page: Page): Promise<void> {
  await page.goto("/outreach/settings");
  await page.getByLabel("Allow this organization to send approved email").check();
  await page.getByLabel("Sender name").fill("Sam Sender");
  await page.getByLabel("Sender email").fill("sam@salesiq.example.com");
  await page.getByLabel("Postal address").fill("1 Example Street");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByText("Settings saved.")).toBeVisible();
}

function received(address: string): { body: string; subject: string }[] {
  return readFileSync(SINK_FILE, "utf-8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as { to: string; subject: string; body: string })
    .filter((m) => m.to === address);
}

test("a draft goes through approval to a real mail server, and an opt-out sticks", async ({ page }) => {
  const address = uniqueEmail();
  await signUpWithOrg(page, "Outreach E2E");
  await configureSending(page);
  await leadWithEmail(page, address);

  await page.getByRole("button", { name: "Write a draft" }).click();
  await page.getByLabel("Subject").fill("Quick question");
  await page.getByLabel("Message").fill("Worth a short talk?");
  await page.getByRole("button", { name: "Save draft" }).click();

  await expect(page.getByText("Review the text, then ask for approval.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send email" })).toHaveCount(0);
  await page.getByRole("button", { name: "Ask for approval" }).click();
  await expect(page.getByText("Waiting for a decision")).toBeVisible();

  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Every check passes now")).toBeVisible();
  expect(received(address)).toHaveLength(0);

  await page.getByRole("button", { name: "Send email" }).click();
  await expect(page.getByText("Accepted by the mail server")).toBeVisible();
  await expect(page.getByText("does not prove it reached an inbox")).toBeVisible();

  const message = received(address)[0]!;
  expect(message.subject).toBe("Quick question");
  expect(message.body).toContain("Worth a short talk?");
  expect(message.body).toContain("1 Example Street");

  const link = /\/unsubscribe\/[\w-]+/.exec(message.body)?.[0];
  expect(link).toBeTruthy();
  const signedOut = await page.context().browser()!.newContext({ baseURL: "http://127.0.0.1:3100" });
  const visitor = await signedOut.newPage();
  await visitor.goto(link!);
  await visitor.getByRole("button", { name: "Unsubscribe" }).click();
  await expect(visitor.getByText("You will not get these emails again.")).toBeVisible();
  await signedOut.close();

  await page.goto("/outreach/suppressions");
  await expect(page.getByText(address)).toBeVisible();
  await expect(page.getByText("Opted out")).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove" })).toHaveCount(0);
});

test("an edit ends an approval, and blockers are explained", async ({ page }) => {
  await signUpWithOrg(page, "Blockers E2E");
  await leadWithEmail(page, uniqueEmail());
  await page.getByRole("button", { name: "Write a draft" }).click();
  await page.getByLabel("Subject").fill("First");
  await page.getByLabel("Message").fill("First words");
  await page.getByRole("button", { name: "Save draft" }).click();
  await page.getByRole("button", { name: "Ask for approval" }).click();
  await page.getByRole("button", { name: "Approve" }).click();

  await expect(page.getByText("Sending is turned off for this organization.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send email" })).toBeDisabled();

  await page.getByLabel("Body").fill("Other words");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Replaced by an edit")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send email" })).toHaveCount(0);
});

test("the suppression list stops a draft being written", async ({ page }) => {
  const address = uniqueEmail();
  await signUpWithOrg(page, "Suppression E2E");
  await leadWithEmail(page, address);
  const lead = page.url();
  await page.goto("/outreach/suppressions");
  await expect(page.getByText("Nobody on the list")).toBeVisible();
  await page.getByLabel("Address or domain").fill(address);
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByText("Added by a person")).toBeVisible();

  await page.goto(lead);
  await page.getByRole("button", { name: "Write a draft" }).click();
  await page.getByLabel("Subject").fill("Hello");
  await page.getByLabel("Message").fill("Hello there");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByText("This address must not be contacted")).toBeVisible();
});
