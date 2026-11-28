import { expectNoAxeViolations } from "@knowcel/ui/testing";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App.tsx";
import { SEARCH_STEPS, SOURCES } from "./ChatDemo.tsx";
import { render as renderStatic } from "./entry-server.tsx";
import { REPO } from "./links.ts";
import { ERP, PLM } from "./systems.ts";

describe("marketing site", () => {
  it("has one title and a section for every nav link", async () => {
    const { container } = render(<App />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    const nav = screen.getByRole("navigation", { name: "Main" });
    for (const link of within(nav).getAllByRole("link")) {
      const href = link.getAttribute("href") ?? "";
      if (href.startsWith("#")) expect(container.querySelector(href)).not.toBeNull();
    }
    expect(container.querySelector("#quick-start")).not.toBeNull();
    await expectNoAxeViolations(container);
  });

  it("shows the demo as a recording nobody can interact with", () => {
    render(<App />);
    const demo = screen.getByRole("figure", { name: /recording/ });
    expect(within(demo).queryAllByRole("button")).toHaveLength(0);
    expect(within(demo).queryAllByRole("link")).toHaveLength(0);
    expect(demo.className).toContain("pointer-events-none");
    expect(within(demo).getByText("Demo recording")).not.toBeNull();
  });

  it("prerenders the content, so the page reads without JavaScript", () => {
    const html = renderStatic();
    expect(html).toContain("Everything your organization knows");
    for (const pillar of ["Absorb", "Connect", "Renew"]) expect(html).toContain(pillar);
    expect(html).toContain("On the roadmap");
    expect(html).toContain(ERP);
    expect(html).toContain("task up:release");
  });

  it("says Absorb takes in uploads and connectors, and links to the connector guide", () => {
    const { container } = render(<App />);
    const absorb = screen.getByRole("heading", { name: "Absorb" }).closest("li") as HTMLElement;
    expect(absorb.textContent).toMatch(/Upload/);
    expect(absorb.textContent).toMatch(/connect/);
    const hrefs = [...container.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(hrefs).toContain(`${REPO}/blob/main/docs/connectors.md`);
    expect(screen.getByRole("heading", { name: "Bring in your knowledge" })).not.toBeNull();
  });

  it("shows uploads in the first scene, apart from connected systems", () => {
    render(<App />);
    const uploads = screen.getByRole("region", { name: "Uploaded files" });
    expect(uploads.textContent).toContain("handbook.pdf");
    expect(uploads.textContent).not.toContain(PLM);
    expect(screen.queryByRole("region", { name: "Connected systems" })).toBeNull();
    expect(screen.getAllByRole("link", { name: /connectors/i }).length).toBeGreaterThan(0);
  });

  it("names the connected systems like real ones and says they are examples", () => {
    const html = renderStatic();
    expect(html).toContain("Connectors");
    expect(html).toContain(PLM);
    expect(html).not.toContain("showcase-");
    expect(html).toContain("not features of Knowcelium");
  });

  it("answers the demo question from synced documents and a live system", () => {
    expect(SOURCES).toHaveLength(3);
    expect(SOURCES.map((s) => s.detail)).toEqual([
      `synced from ${PLM}`,
      `synced from ${ERP}`,
      `live from ${ERP}`,
    ]);
    const html = renderStatic();
    expect(html).toContain("Connector sources");
    expect(html).toContain("Live");
  });

  it("shows the searches the chat made before the answer", () => {
    const html = renderStatic();
    expect(SEARCH_STEPS.length).toBeGreaterThanOrEqual(2);
    expect(html).toContain("Sources searched");
    for (const step of SEARCH_STEPS) expect(html).toContain(step.query);
    expect(html.indexOf("Sources searched")).toBeLessThan(html.indexOf('aria-label="Sources"'));
    expect(html).toContain("decides for itself what to look up");
  });
});
