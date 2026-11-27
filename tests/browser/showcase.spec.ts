import { expect, type Page, test } from "@playwright/test";

// The cross-system questions of examples/showcase/README.md (#253). They need the showcase stack
// (task showcase:up) with the fake LLM provider (KNOWCEL_LLM_PROVIDER=fake), whose answer echoes
// the question and so cites the sources its [n] markers name; a real model decides for itself what
// to cite. With agentic chat on (the default), the fake model searches where the question says
// so, with [tool:NAME {json}] triggers, one after the other, and its answer echoes what the
// searches found; with it off the [n] markers do the same. Set KNOWCEL_E2E_SHOWCASE=1 and KNOWCEL_E2E_WEB to the running web shell; alice has to
// have signed in once and both showcase connectors to have synced (see connectors.spec.ts).
const MARKERS = "[1] [2] [3] [4] [5] [6] [7] [8]";

// Search the documents, or the connectors, as the fake model is scripted to.
const searchDocuments = (query: string) =>
  `[tool:search_knowledge_base ${JSON.stringify({ query })}]`;
const searchConnectors = (query: string) => `[tool:search_connectors ${JSON.stringify({ query })}]`;

/** Asks in a new chat and waits for the saved answer, whose sources are listed once it is. */
async function ask(page: Page, question: string) {
  await page.goto("/");
  await page.getByRole("button", { name: "New chat" }).first().click();
  await page.getByPlaceholder("Ask something…").fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const sources = page.getByRole("list", { name: "Sources", exact: true });
  await expect(sources).toBeVisible({ timeout: 90_000 });
  return sources;
}

const questions = [
  {
    // Synced documents of both systems.
    name: "from synced documents",
    question: "Which open change requests concern parts from our lowest-rated supplier?",
    documentQuery: "Which open change requests concern parts from our lowest-rated supplier?",
    connectorQuery: "",
    documents: [/CR-3001/, /SUP-1002/],
    live: false,
  },
  {
    // Engineering documents and the live shipment search of logistics.
    name: "from documents and live shipments",
    question: "Which open change requests affect parts whose supplier has a delayed shipment?",
    documentQuery: "Which open change requests affect parts whose supplier has a delayed shipment?",
    connectorQuery: "delayed",
    documents: [/CR-3001|CR-3004/],
    live: true,
  },
  {
    name: "from stock and live shipments",
    question: "How many torque sensors are in stock and when does Sensora Precision deliver more?",
    // The documents are matched word by word: the stock record says "Torque sensor".
    documentQuery: "torque sensor stock on hand",
    connectorQuery: "torque sensors",
    documents: [/STK-4006/],
    live: true,
  },
];

for (const { name, question, documentQuery, connectorQuery, documents, live } of questions) {
  test(`a cross-system question answered ${name} cites both systems`, async ({ page }) => {
    test.skip(!process.env.KNOWCEL_E2E_SHOWCASE, "needs the showcase stack (task showcase:up)");
    test.setTimeout(120_000);
    // The model searches the documents for the question and, when a live system is needed, asks it too.
    const searches = [
      searchDocuments(documentQuery),
      connectorQuery && searchConnectors(connectorQuery),
    ];
    const sources = await ask(page, `${question} ${searches.filter(Boolean).join(" ")} ${MARKERS}`);
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

test("an agentic answer shows what was searched, also after a reload", async ({ page }) => {
  test.skip(!process.env.KNOWCEL_E2E_SHOWCASE, "needs the showcase stack (task showcase:up)");
  test.skip(
    process.env.KNOWCEL_AGENTIC === "false",
    "needs agentic chat (KNOWCEL_AGENTIC, on by default)",
  );
  test.setTimeout(120_000);
  const question = "Which open change requests affect parts whose supplier has a delayed shipment?";
  const sources = await ask(
    page,
    `${question} ${searchDocuments(question)} ${searchConnectors("delayed")}`,
  );

  // The documents and the live system are both cited.
  await expect(sources).toContainText(/CR-3001|CR-3004/);
  const connector = page.getByRole("list", { name: "Connector sources" });
  await expect(connector).toContainText("showcase-logistics");
  await expect(connector).toContainText("Live");

  // The searches the model chose are kept under the answer, in the order it made them.
  const searched = async () => {
    const summary = page.getByText(/^Searched for /);
    await expect(summary).toContainText("Which open change requests affect parts");
    await expect(summary).toContainText("delayed");
    if (!(await page.getByRole("list", { name: "Searches" }).isVisible())) await summary.click();
    const steps = page.getByRole("list", { name: "Searches" }).getByRole("listitem");
    await expect(steps).toHaveCount(2);
    await expect(steps.nth(0)).toContainText(
      /Your documents.*Which open change requests.*found \d+ passage/,
    );
    await expect(steps.nth(1)).toContainText(/showcase-logistics.*“delayed”.*found \d+ result/);
  };
  await searched();

  await page.reload();
  await expect(page.getByRole("list", { name: "Connector sources" })).toContainText(
    "showcase-logistics",
  );
  await searched();
});
