import { expect, type Page, test } from "@playwright/test";
import { users } from "./users.ts";

// Alice is the platform admin the dev stack bootstraps (KNOWCEL_IAM_BOOTSTRAP_ADMINS);
// bob is not (#260).
const sidebar = (p: Page) => p.getByRole("navigation").first();

test("platform admins find the Connectors page, other users never see it", async ({
  page,
  browser,
}) => {
  const bobContext = await browser.newContext({ storageState: users.bob.storageState });
  const bob = await bobContext.newPage();
  const registered = bob.waitForResponse((r) => r.url().includes("IamService/GetCurrentUser"));
  await bob.goto("/");
  await registered;
  await expect(sidebar(bob).getByRole("link", { name: "Upload" })).toBeVisible();
  await expect(sidebar(bob).getByRole("link", { name: "Connectors" })).toHaveCount(0);
  await bob.goto("/m/ingestion/connectors");
  await expect(bob.getByText("Only platform admins can see the connectors.")).toBeVisible();
  await expect(bob.getByRole("table", { name: "Connectors" })).toHaveCount(0);
  await bobContext.close();

  await page.goto("/");
  await sidebar(page).getByRole("link", { name: "Connectors" }).click();
  await expect(page).toHaveURL(/\/m\/ingestion\/connectors$/);
  await expect(page.getByRole("heading", { name: "Connectors" })).toBeVisible();
});

// Needs the showcase stack (task showcase:up): the mock systems and their connectors, whose
// owner alice has to have signed in once. Set KNOWCEL_E2E_SHOWCASE=1 and KNOWCEL_E2E_WEB
// to the running web shell. The connectors sync every minute and report after their first run.
test("the showcase connectors show as healthy", async ({ page }) => {
  test.skip(!process.env.KNOWCEL_E2E_SHOWCASE, "needs the showcase stack (task showcase:up)");
  test.setTimeout(180_000);
  await page.goto("/m/ingestion/connectors");
  for (const name of ["showcase-engineering", "showcase-logistics"]) {
    const row = page.getByRole("row", { name: new RegExp(name) });
    // The page refreshes every 30 seconds; wait for the first sync to be reported.
    await expect(row.getByText("Healthy")).toBeVisible({ timeout: 150_000 });
    await expect(row.getByRole("link", { name: /What to do/ })).toHaveCount(0);
  }
});
