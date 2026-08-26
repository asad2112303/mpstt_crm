import { expect, test } from "@playwright/test";

test.describe("MPSTT CRM shell smoke", () => {
  test("login page renders the MPSTT brand and form", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByText("MPSTT CRM")).toBeVisible();
    await expect(page.getByLabel("Email")).toBeVisible();
    await expect(page.getByLabel("Password")).toBeVisible();
    // Without Supabase configured the page must say so rather than break.
    await expect(page.getByText("Supabase is not configured")).toBeVisible();
    await expect(page.getByText("no public\n            signup", { exact: false }))
      .toBeVisible();
  });

  test("app pages render their shells (backend offline tolerated)", async ({ page }) => {
    for (const path of ["/dashboard", "/prospects", "/quotations", "/inventory"]) {
      await page.goto(path);
      // Sidebar brand always present; page must not white-screen.
      await expect(page.getByText("Prospect to payment")).toBeVisible();
    }
  });

  test("unauthorized page offers a way back", async ({ page }) => {
    await page.goto("/unauthorized");
    await expect(page.getByText("Not authorized")).toBeVisible();
    await expect(page.getByRole("link", { name: "Back to dashboard" })).toBeVisible();
  });
});
