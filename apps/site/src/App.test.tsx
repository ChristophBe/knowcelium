import { expectNoAxeViolations } from "@knowcel/ui/testing";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App.tsx";
import { SEARCH_STEPS, SOURCES } from "./ChatDemo.tsx";
import { render as renderStatic } from "./entry-server.tsx";
import { REPO } from "./links.ts";

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
    expect(html).toContain("showcase-logistics");
    expect(html).toContain("from showcase-engineering");
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

  it("answers the demo question from two connected systems", () => {
    const [first, second] = SOURCES;
    expect(first?.detail).toContain("showcase-engineering");
    expect(second?.detail).toContain("showcase-logistics");
    expect(SOURCES).toHaveLength(2);
  });

  it("shows the searches the chat made before the answer", () => {
    const html = renderStatic();
    expect(SEARCH_STEPS.length).toBeGreaterThanOrEqual(2);
    expect(html).toContain("Search steps");
    for (const step of SEARCH_STEPS) expect(html).toContain(step.query);
    expect(html.indexOf("Search steps")).toBeLessThan(html.indexOf("Sources"));
    expect(html).toContain("decides for itself what to look up");
  });
});
