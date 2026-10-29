import { expect, test } from "@playwright/test";

import { signUpWithOrg } from "./helpers";

test.beforeEach(async ({ page }) => {
  await signUpWithOrg(page, "Leads E2E");
});

test("create a lead, add a note, and open an opportunity", async ({ page }) => {
  await page.goto("/leads");
  await expect(page.getByText("No leads yet")).toBeVisible();
  await page.getByRole("link", { name: "New lead" }).click();

  await page.getByLabel("First name").fill("Ada");
  await page.getByLabel("Last name").fill("Lovelace");
  await page.getByLabel("Email").fill("ada@engines.example.com");
  await page.getByLabel("Company").fill("Analytical Engines");
  await page.getByRole("button", { name: "Create lead" }).click();

  await expect(page.getByRole("heading", { level: 1, name: /Ada Lovelace/ })).toBeVisible();
  await expect(page.getByText("Lead created")).toBeVisible();

  await page.getByLabel("Add a note").fill("Asked for pricing");
  await page.getByRole("button", { name: "Add note" }).click();
  await expect(page.getByText("Asked for pricing")).toBeVisible();

  await page.getByRole("button", { name: "New opportunity" }).click();
  await page.getByLabel("Amount").fill("12500");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByText("Opportunity created")).toBeVisible();

  // The new deal appears on the board, and moving it records a stage change.
  await page.goto("/pipeline");
  const card = page.getByRole("listitem", { name: "Analytical Engines", exact: true });
  await expect(card).toBeVisible();
  await card.getByLabel(/Stage for/).selectOption({ label: "Proposal" });
  await expect(
    page.getByRole("listitem", { name: "Proposal" }).getByRole("listitem", { name: "Analytical Engines" }),
  ).toBeVisible();

  await page.goto("/");
  await expect(page.getByText("Open pipeline", { exact: true })).toBeVisible();
  await expect(page.getByText("$12,500").first()).toBeVisible();
});

test("duplicate email links to the existing lead", async ({ page }) => {
  for (let i = 0; i < 2; i++) {
    await page.goto("/leads/new");
    await page.getByLabel("Email").fill("dup@example.com");
    await page.getByRole("button", { name: "Create lead" }).click();
    if (i === 0) await expect(page.getByRole("heading", { level: 1 })).toContainText("dup@example.com");
  }
  await expect(page.getByText("A lead with this email already exists")).toBeVisible();
  await page.getByRole("link", { name: "Open the existing lead" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("dup@example.com");
});

test("import a CSV, review results, filter, and bulk-tag", async ({ page }) => {
  const csv = [
    "Name,Email,Company,Title",
    "Grace Hopper,grace@navy.example.com,Navy,Admiral",
    "Alan Turing,alan@bletchley.example.com,Bletchley,Researcher",
    "Bad Row,not-an-email,,",
  ].join("\n");

  await page.goto("/leads/import");
  await page.getByLabel("CSV file").setInputFiles({ name: "people.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await expect(page.getByText("3 rows found")).toBeVisible();
  await expect(page.getByLabel("Field for column Email")).toHaveValue("email");
  await page.getByRole("button", { name: "Import 3 rows" }).click();

  await expect(page.getByRole("heading", { name: "Imported people.csv" })).toBeVisible();
  await expect(page.getByText("Row 4")).toBeVisible();
  await page.getByRole("link", { name: "View imported leads" }).click();
  await expect(page.getByText("2 leads")).toBeVisible();

  await page.getByLabel("Select all leads on this page").check();
  await page.locator("#bulk-tag").fill("conference");
  await page.getByRole("button", { name: "Add tag" }).click();
  await expect(page.getByText("Updated 2 of 2 selected leads.")).toBeVisible();

  await page.goto("/leads");
  await page.getByLabel("Search").fill("navy");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page).toHaveURL(/q=navy/);
  await expect(page.getByRole("link", { name: "Grace Hopper" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Alan Turing" })).toHaveCount(0);
});

test("export downloads a CSV", async ({ page }) => {
  await page.goto("/leads");
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export CSV" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^leads-.*\.csv$/);
});
