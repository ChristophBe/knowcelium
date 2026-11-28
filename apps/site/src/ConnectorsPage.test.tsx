import { expectNoAxeViolations } from "@knowcel/ui/testing";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConnectorsPage } from "./ConnectorsPage.tsx";
import { render as renderStatic } from "./entry-server.tsx";
import { REPO } from "./links.ts";
import { ERP, PLM } from "./systems.ts";

describe("connectors page", () => {
  it("has one title and no accessibility violations", async () => {
    const { container } = render(<ConnectorsPage />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    await expectNoAxeViolations(container);
  });

  it("stresses live data, says what the examples provide and that they are examples", () => {
    render(<ConnectorsPage />);
    expect(screen.getByRole("heading", { name: "Live search" })).not.toBeNull();
    expect(screen.getByRole("heading", { name: "Sync" })).not.toBeNull();
    expect(
      screen.getByRole("heading", { name: "Extend static knowledge with live data" }),
    ).not.toBeNull();
    for (const name of [PLM, ERP]) expect(screen.getByRole("heading", { name })).not.toBeNull();
    expect(screen.getByText(/Shipments: status, delay in days/)).not.toBeNull();
    expect(document.body.textContent).toMatch(/not features of Knowcelium/);
    expect(screen.getAllByText("Example")).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "What you can ask now" })).not.toBeNull();
  });

  it("shows the live demo as a recording nobody can interact with", () => {
    render(<ConnectorsPage />);
    const demo = screen.getByRole("figure", { name: /recording/ });
    expect(demo.className).toContain("pointer-events-none");
    expect(within(demo).queryAllByRole("button")).toHaveLength(0);
    expect(within(demo).queryAllByRole("link")).toHaveLength(0);
    // At rest (before hydration) the recording shows the finished answer.
    const html = renderStatic("connectors");
    expect(html).toContain("affected");
    expect(html).toContain("Connector sources");
  });

  it("links the SDK guide and, from the nav, back to the home sections", () => {
    const { container } = render(<ConnectorsPage />);
    const hrefs = [...container.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(hrefs).toContain(`${REPO}/blob/main/docs/connectors.md`);
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Features" }).getAttribute("href")).toBe(
      "/#features",
    );
    expect(within(nav).getByRole("link", { name: "Connectors" }).getAttribute("aria-current")).toBe(
      "page",
    );
  });

  it("prerenders as its own page", () => {
    const html = renderStatic("connectors");
    expect(html).toContain("and what is true right now.");
    expect(html).toContain("list_changes");
  });
});
