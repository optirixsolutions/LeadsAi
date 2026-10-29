import { expect, test } from "@playwright/test";

import { PASSWORD, signUpWithOrg, uniqueEmail } from "./helpers";

test("signed-out visitors are sent to sign in, keeping their destination", async ({ page }) => {
  await page.goto("/settings/team");
  await expect(page).toHaveURL(/\/login\?next=%2Fsettings%2Fteam$/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("register, create an organization, and land on the overview", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Your name").fill("Riley Rep");
  await page.getByLabel("Work email").fill(uniqueEmail());
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByLabel("Organization name").fill("Northwind Traders");
  await page.getByRole("button", { name: "Create organization" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
  await expect(page.getByLabel("Organization").first()).toHaveValue(/.+/);
  await expect(page.locator("#org-switcher option:checked").first()).toHaveText(
    "Northwind Traders",
  );
});

test("client-side validation blocks weak passwords", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Work email").fill(uniqueEmail());
  await page.getByLabel("Password").fill("short");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("Use at least 12 characters")).toBeVisible();
  await expect(page).toHaveURL(/\/register$/);
});

test("wrong password shows an error and stays on sign in", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(uniqueEmail());
  await page.getByLabel("Password").fill("not the right one");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Email or password is incorrect" }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
});

test("sign out, then sign back in", async ({ page }) => {
  const email = await signUpWithOrg(page);
  await page.goto("/settings/account");
  await page.getByRole("button", { name: "Sign out", exact: true }).first().click();
  await expect(page).toHaveURL(/\/login$/);

  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
});

test("owner sees themselves on the team page and can send and revoke an invite", async ({
  page,
}) => {
  await signUpWithOrg(page, "Team Co");
  await page.goto("/settings/team");
  const members = page.getByRole("table");
  await expect(members.getByText("E2E User")).toBeVisible();
  await expect(members.getByText("Owner (you)")).toBeVisible();

  const invitee = uniqueEmail();
  await page.getByLabel("Email").fill(invitee);
  await page.getByLabel("Role", { exact: true }).selectOption("sales_rep");
  await page.getByRole("button", { name: "Send invite" }).click();
  await expect(page.getByText(`Invitation sent to ${invitee}.`)).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: invitee })).toBeVisible();

  await page.getByRole("button", { name: `Revoke invitation for ${invitee}` }).click();
  await page.getByRole("button", { name: "Confirm revoke" }).click();
  await expect(page.getByText(`Revoked invitation for ${invitee}.`)).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: invitee })).toHaveCount(0);
});

test("organization rename persists and is audited", async ({ page }) => {
  await signUpWithOrg(page, "Old Name");
  await page.goto("/settings/organization");
  const name = page.getByLabel("Organization name");
  await name.fill("New Name");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Saved.")).toBeVisible();
  await page.reload();
  await expect(name).toHaveValue("New Name");
  await expect(page.getByText("Organization renamed")).toBeVisible();
});
