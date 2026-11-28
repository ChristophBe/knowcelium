import {
  CurrentUserProvider,
  clearNotifications,
  defineNotifications,
  type NotificationEntry,
  restoreNotificationPreferences,
  setNotificationPreference,
  useNotificationPreferences,
  useNotifications,
} from "@knowcel/module-sdk";
import { act, cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  loadNotificationPreferences,
  loadNotifications,
  saveNotifications,
  useNotificationStorage,
} from "./notification-storage.ts";

const session = vi.hoisted(() => ({ current: null as { name: string; signOut(): void } | null }));
vi.mock("./auth/AuthGate.tsx", () => ({ useSession: () => session.current }));

const n = defineNotifications([{ id: "uploads", label: "Uploads" }]);

function Probe() {
  useNotificationStorage();
  return (
    <>
      <p data-testid="titles">
        {useNotifications()
          .map((e) => e.title)
          .join(",")}
      </p>
      <p data-testid="prefs">{JSON.stringify(useNotificationPreferences())}</p>
    </>
  );
}

const user = (id: string) => ({ id, email: `${id}@x`, displayName: id, platformAdmin: false });
const entry = (title: string): NotificationEntry => ({
  id: 1,
  category: "uploads",
  title,
  kind: "info",
  createdAt: 1,
  read: false,
});

function renderAs(id: string | null, children: ReactNode = <Probe />) {
  if (id) session.current = { name: id, signOut: () => {} };
  return render(<CurrentUserProvider user={id ? user(id) : null}>{children}</CurrentUserProvider>);
}

describe("notification storage", () => {
  beforeEach(() => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  });
  afterEach(() => {
    session.current = null;
    cleanup();
    act(() => {
      clearNotifications();
      restoreNotificationPreferences({});
    });
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("keeps entries across a reload, per user", () => {
    const first = renderAs("ann");
    act(() => n.notify({ category: "uploads", title: "ann's", kind: "info" }));
    first.unmount();
    act(() => clearNotifications());

    // Same browser, another user: nothing of ann's shows up.
    const bob = renderAs("bob");
    expect(screen.getByTestId("titles").textContent).toBe("");
    act(() => n.notify({ category: "uploads", title: "bob's", kind: "info" }));
    bob.unmount();
    act(() => clearNotifications());

    renderAs("ann");
    expect(screen.getByTestId("titles").textContent).toBe("ann's");
  });

  it("keeps preferences per user and ignores damaged ones", () => {
    const ann = renderAs("ann");
    act(() => setNotificationPreference("uploads", "off"));
    expect(loadNotificationPreferences("ann")).toEqual({ uploads: "off" });
    ann.unmount();
    renderAs("bob");
    expect(screen.getByTestId("prefs").textContent).toBe("{}");
    cleanup();
    renderAs("ann");
    expect(screen.getByTestId("prefs").textContent).toBe('{"uploads":"off"}');

    localStorage.setItem("knowcel.notification-preferences.ann", "{not json");
    expect(loadNotificationPreferences("ann")).toEqual({});
    localStorage.setItem("knowcel.notification-preferences.ann", "[1]");
    expect(loadNotificationPreferences("ann")).toEqual({});
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("full");
    });
    expect(() => act(() => setNotificationPreference("uploads", "app"))).not.toThrow();
  });

  it("neither reads nor writes while a signed-in user is unknown", () => {
    session.current = { name: "Ann", signOut: () => {} };
    saveNotifications("anonymous", [entry("old")]);
    renderAs(null);
    expect(screen.getByTestId("titles").textContent).toBe("");
    act(() => n.notify({ category: "uploads", title: "x", kind: "info" }));
    expect(loadNotifications("anonymous").map((e) => e.title)).toEqual(["old"]);
  });

  it("uses one list when the shell runs without sign-in", () => {
    saveNotifications("anonymous", [entry("old")]);
    renderAs(null);
    expect(screen.getByTestId("titles").textContent).toBe("old");
  });

  it("keeps what was recorded before the user became known", () => {
    saveNotifications("ann", [entry("saved")]);
    act(() => n.notify({ category: "uploads", title: "early", kind: "info" }));
    renderAs("ann");
    expect(screen.getByTestId("titles").textContent).toBe("saved,early");
  });

  it("drops the toast action and ignores damaged data", () => {
    saveNotifications("ann", [{ ...entry("a"), action: { label: "Undo", onSelect: () => {} } }]);
    expect(loadNotifications("ann")[0]).not.toHaveProperty("action");
    localStorage.setItem("knowcel.notifications.ann", "{not json");
    expect(loadNotifications("ann")).toEqual([]);
    localStorage.setItem("knowcel.notifications.ann", JSON.stringify([{ title: 1 }, "x", null]));
    expect(loadNotifications("ann")).toEqual([]);
    localStorage.setItem("knowcel.notifications.ann", '{"a":1}');
    expect(loadNotifications("ann")).toEqual([]);
  });

  it("survives a full or blocked storage", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("full");
    });
    expect(() => saveNotifications("ann", [entry("a")])).not.toThrow();
  });
});
