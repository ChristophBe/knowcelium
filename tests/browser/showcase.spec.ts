import { expect, test } from "@playwright/test";

// The cross-system questions of examples/showcase/README.md (#253). They need the showcase stack
// (task showcase:up) with the fake LLM provider (KNOWCEL_LLM_PROVIDER=fake), whose answer echoes
// the question and so cites the sources its [n] markers name; a real model decides for itself what
// to cite. Set KNOWCEL_E2E_SHOWCASE=1 and KNOWCEL_E2E_WEB to the running web shell; alice has to
// have signed in once and both showcase connectors to have synced (see connectors.spec.ts).
const MARKERS = "[1] [2] [3] [4] [5] [6] [7] [8]";

const questions = [
  {
    // Synced documents of both systems.
    name: "from synced documents",
    question: "Which open change requests concern parts from our lowest-rated supplier?",
    documents: [/CR-3001/, /SUP-1002/],
    live: false,
  },
  {
    // Engineering documents and the live shipment search of logistics.
    name: "from documents and live shipments",
    question: "Which open change requests affect parts whose supplier has a delayed shipment?",
    documents: [/CR-3001|CR-3004/],
    live: true,
  },
  {
    name: "from stock and live shipments",
    question: "How many torque sensors are in stock and when does Sensora Precision deliver more?",
    documents: [/STK-4006/],
    live: true,
  },
];

for (const { name, question, documents, live } of questions) {
  test(`a cross-system question answered ${name} cites both systems`, async ({ page }) => {
    test.skip(!process.env.KNOWCEL_E2E_SHOWCASE, "needs the showcase stack (task showcase:up)");
    test.setTimeout(120_000);
    await page.goto("/");
    await page.getByRole("button", { name: "New chat" }).first().click();
    await page.getByPlaceholder("Ask something…").fill(`${question} ${MARKERS}`);
    await page.getByRole("button", { name: "Ask", exact: true }).click();

    // The answer arrives with its sources, which are only listed once it is saved.
    const sources = page.getByRole("list", { name: "Sources", exact: true });
    await expect(sources).toBeVisible({ timeout: 90_000 });
    for (const document of documents) await expect(sources).toContainText(document);

    const connector = page.getByRole("list", { name: "Connector sources" });
    let cited = (await sources.textContent()) ?? "";
    if (live) {
      await expect(connector).toContainText("showcase-logistics");
      await expect(connector).toContainText("Live");
      cited += await connector.textContent();
    }
    // Both systems are cited: the engineering documents, and the logistics ones or a live shipment.
    expect(cited).toMatch(/Change request|Part|Specification|CR-/);
    expect(cited).toMatch(/Supplier|Stock|Shipment|SUP-|STK-|SHP-/);
  });
}
