import { Code, ConnectError, createRouterTransport } from "@connectrpc/connect";
import {
  type ConnectorHealth,
  ConnectorHealth as Health,
  IngestionService,
} from "@knowcel/ingestion-api/knowcel/ingestion/v1/ingestion_pb";
import type { CurrentUser } from "@knowcel/module-sdk";
import { renderModule } from "@knowcel/module-sdk/testing";
import { expectNoAxeViolations } from "@knowcel/ui/testing";
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { REFRESH_MS } from "./Connectors.tsx";
import ingestion from "./index.tsx";
import manifest from "./manifest.ts";

const admin: CurrentUser = {
  id: "alice",
  email: "alice@example.com",
  displayName: "Alice",
  platformAdmin: true,
};
const user: CurrentUser = { ...admin, platformAdmin: false };

const hourAgo = { seconds: BigInt(Math.floor(Date.now() / 1000) - 3600) };

function connector(name: string, health: ConnectorHealth, extra = {}) {
  return {
    id: name,
    name,
    kind: "folder",
    enabled: true,
    health,
    intervalSeconds: 60,
    lastSuccessTime: hourAgo,
    documentsSynced: 1234,
    ...extra,
  };
}

const serving = (connectors: ReturnType<typeof connector>[]) => {
  const listConnectors = vi.fn(() => ({ connectors }));
  const transport = createRouterTransport(({ service }) =>
    service(IngestionService, { listConnectors }),
  );
  return { transport, listConnectors };
};

const states: [string, ConnectorHealth, string][] = [
  ["healthy", Health.HEALTHY, "Healthy"],
  ["degraded", Health.DEGRADED, "Degraded"],
  ["failing", Health.FAILING, "Failing"],
  ["stale", Health.STALE, "Stale"],
  ["unknown", Health.UNKNOWN, "Not synced yet"],
];

describe("Connectors", () => {
  it.each(states)("shows a %s connector with its own label and icon", async (name, h, label) => {
    const { transport } = serving([connector(name, h, { lastError: "3 files skipped" })]);
    const { container } = renderModule(ingestion, transport, "/connectors", admin);
    const row = within((await screen.findByRole("row", { name: new RegExp(name) })) as HTMLElement);
    expect(row.getByText(label)).toBeTruthy();
    expect(row.getByText(label).parentElement?.querySelector("svg")).toBeTruthy();
    expect(row.getByText("1,234")).toBeTruthy();
    expect(row.getByText("3 files skipped")).toBeTruthy();
    expect(row.getByText("1 hour ago")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("gives each state a different icon", async () => {
    const { transport } = serving(states.map(([n, h]) => connector(n, h)));
    renderModule(ingestion, transport, "/connectors", admin);
    await screen.findByRole("table", { name: "Connectors" });
    const icons = states.map(([, , label]) => {
      const svg = screen.getByText(label).parentElement?.querySelector("svg");
      return svg?.getAttribute("class")?.match(/lucide-[\w-]+/)?.[0];
    });
    expect(new Set(icons).size).toBe(states.length);
  });

  it("links unhealthy connectors, and only those, to what to do", async () => {
    const { transport } = serving(states.map(([n, h]) => connector(n, h)));
    renderModule(ingestion, transport, "/connectors", admin);
    await screen.findByRole("table", { name: "Connectors" });
    expect(screen.queryByRole("link", { name: "What to do about healthy" })).toBeNull();
    for (const [name] of states.slice(1)) {
      const link = screen.getByRole("link", { name: `What to do about ${name}` });
      expect(link.getAttribute("href")).toBe("/help/ingestion#fix-an-unhealthy-connector");
    }
  });

  it("says when a connector never synced, is disabled or has invalid settings", async () => {
    const { transport } = serving([
      connector("broken", Health.FAILING, {
        kind: "",
        enabled: false,
        lastSuccessTime: undefined,
        lastError: "no interval",
      }),
    ]);
    renderModule(ingestion, transport, "/connectors", admin);
    const row = within(await screen.findByRole("row", { name: /broken/ }));
    expect(row.getByText("Never")).toBeTruthy();
    expect(row.getByText(/Invalid settings/)).toBeTruthy();
    expect(row.getByText(/Disabled/)).toBeTruthy();
    expect(row.queryByRole("link", { name: /What to do/ })).toBeNull();
  });

  it("keeps the last list and offers to retry when a refresh fails", async () => {
    let fail = false;
    const listConnectors = vi.fn(() => {
      if (fail) throw new ConnectError("down", Code.Unavailable);
      return { connectors: [connector("a", Health.HEALTHY)] };
    });
    const transport = createRouterTransport(({ service }) =>
      service(IngestionService, { listConnectors }),
    );
    const { queryClient } = renderModule(ingestion, transport, "/connectors", admin);
    await screen.findByRole("table", { name: "Connectors" });
    fail = true;
    await queryClient.refetchQueries({ queryKey: ["connectors"] });
    expect(await screen.findByText(/may be out of date/)).toBeTruthy();
    expect(screen.getByRole("table", { name: "Connectors" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });

  it("keeps the table in its own scroll container", async () => {
    const { transport } = serving([connector("a", Health.HEALTHY)]);
    renderModule(ingestion, transport, "/connectors", admin);
    const table = await screen.findByRole("table", { name: "Connectors" });
    expect(table.parentElement?.className).toContain("overflow-x-auto");
  });

  it("explains connectors and links to the guide when there are none", async () => {
    const { transport } = serving([]);
    const { container } = renderModule(ingestion, transport, "/connectors", admin);
    expect(await screen.findByText(/No connectors yet/)).toBeTruthy();
    const link = screen.getByRole("link", { name: /connector guide/ });
    expect(link.getAttribute("href")).toMatch(/docs\/connectors\.md$/);
    await expectNoAxeViolations(container);
  });

  it("says so when the connectors are unavailable, and tries again", async () => {
    let fail = true;
    const listConnectors = vi.fn(() => {
      if (fail) throw new ConnectError("iam down", Code.Unavailable);
      return { connectors: [connector("a", Health.HEALTHY)] };
    });
    const transport = createRouterTransport(({ service }) =>
      service(IngestionService, { listConnectors }),
    );
    const { container } = renderModule(ingestion, transport, "/connectors", admin);
    expect(await screen.findByText(/Connectors are not available right now/)).toBeTruthy();
    await expectNoAxeViolations(container);
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("table", { name: "Connectors" })).toBeTruthy();
  });

  it("shows a loading state first", () => {
    const { transport } = serving([]);
    renderModule(ingestion, transport, "/connectors", admin);
    expect(screen.queryByText(/No connectors yet/)).toBeNull();
  });

  it("refreshes periodically", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { transport, listConnectors } = serving([connector("a", Health.HEALTHY)]);
      renderModule(ingestion, transport, "/connectors", admin);
      await screen.findByRole("table", { name: "Connectors" });
      expect(listConnectors).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(REFRESH_MS + 100);
      expect(listConnectors).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not show the list to anyone else, nor ask for it", () => {
    const { transport, listConnectors } = serving([connector("a", Health.HEALTHY)]);
    renderModule(ingestion, transport, "/connectors", user);
    expect(screen.getByText("Only platform admins can see the connectors.")).toBeTruthy();
    expect(screen.queryByRole("table", { name: "Connectors" })).toBeNull();
    expect(listConnectors).not.toHaveBeenCalled();
  });

  it("waits for the current user instead of denying", () => {
    const { transport, listConnectors } = serving([]);
    renderModule(ingestion, transport, "/connectors", null, "loading");
    expect(screen.queryByText("Only platform admins can see the connectors.")).toBeNull();
    expect(listConnectors).not.toHaveBeenCalled();
  });

  it("says the account could not be loaded", () => {
    const { transport } = serving([]);
    renderModule(ingestion, transport, "/connectors", null, "failed");
    expect(screen.getByText(/Your account could not be loaded/)).toBeTruthy();
  });
});

describe("the navigation", () => {
  it("offers the Connectors entry to platform admins only", () => {
    const entry = manifest.nav?.find((n) => n.path === "connectors");
    expect(entry?.requiresPlatformAdmin).toBe(true);
    expect(manifest.nav?.find((n) => n.path === "")?.requiresPlatformAdmin).toBeFalsy();
  });
});
