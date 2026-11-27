import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearNotifications,
  defineNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  notify,
  offerBrowserNotifications,
  onNotificationPreferencesChange,
  onNotificationsChange,
  onOpenNotificationLink,
  requestBrowserNotifications,
  restoreNotificationPreferences,
  restoreNotifications,
  setNotificationPreference,
  useBrowserNotificationState,
  useNotificationCategories,
  useNotificationPreferences,
  useNotifications,
} from "./notifications.ts";
import { dismissToast, useToasts } from "./toast.ts";

const n = defineNotifications([
  { id: "uploads", label: "Uploads" },
  { id: "answers", label: "Answers" },
]);

function setVisibility(state: DocumentVisibilityState) {
  vi.spyOn(document, "visibilityState", "get").mockReturnValue(state);
}

describe("notify", () => {
  beforeEach(() => setVisibility("visible"));
  afterEach(() => {
    vi.restoreAllMocks();
    const { result } = renderHook(() => useToasts());
    act(() => {
      clearNotifications();
      for (const t of result.current) dismissToast(t.id);
    });
  });

  it("records an entry and shows a toast while the tab is visible", () => {
    const entries = renderHook(() => useNotifications());
    const toasts = renderHook(() => useToasts());
    act(() =>
      n.notify({
        category: "uploads",
        title: "a.pdf added",
        kind: "success",
        link: "/m/document/1",
      }),
    );
    expect(entries.result.current).toMatchObject([
      { category: "uploads", title: "a.pdf added", link: "/m/document/1", read: false },
    ]);
    expect(toasts.result.current.map((t) => [t.kind, t.message])).toEqual([
      ["success", "a.pdf added"],
    ]);
  });

  it("keeps the entry but shows no toast while the tab is hidden", () => {
    setVisibility("hidden");
    const entries = renderHook(() => useNotifications());
    const toasts = renderHook(() => useToasts());
    act(() => n.notify({ category: "answers", title: "Answer ready", kind: "info" }));
    expect(entries.result.current).toHaveLength(1);
    expect(toasts.result.current).toHaveLength(0);
  });

  it("works outside of render", () => {
    notify({ category: "uploads", title: "done", kind: "info" });
    const { result } = renderHook(() => useNotifications());
    expect(result.current.map((e) => e.title)).toEqual(["done"]);
  });

  it("leaves one entry for two notifications with the same tag", () => {
    const entries = renderHook(() => useNotifications());
    act(() => {
      n.notify({ category: "answers", title: "first", kind: "info", tag: "chat-1" });
      n.notify({ category: "answers", title: "other", kind: "info", tag: "chat-2" });
      n.notify({ category: "answers", title: "second", kind: "info", tag: "chat-1" });
    });
    expect(entries.result.current.map((e) => e.title)).toEqual(["other", "second"]);
  });

  it("scopes the replacement by tag to the category", () => {
    const entries = renderHook(() => useNotifications());
    act(() => {
      n.notify({ category: "answers", title: "answer", kind: "info", tag: "x" });
      n.notify({ category: "uploads", title: "upload", kind: "info", tag: "x" });
      n.notify({ category: "uploads", title: "upload 2", kind: "info", tag: "x" });
    });
    expect(entries.result.current.map((e) => e.title)).toEqual(["answer", "upload 2"]);
  });

  it("keeps the action on an error toast", () => {
    const toasts = renderHook(() => useToasts());
    const action = { label: "Retry", onSelect: () => {} };
    act(() => n.notify({ category: "uploads", title: "failed", kind: "error", action }));
    expect(toasts.result.current[0]?.action).toBe(action);
  });

  it("keeps the 50 newest entries", () => {
    const entries = renderHook(() => useNotifications());
    act(() => {
      for (let i = 1; i <= 52; i++) n.notify({ category: "uploads", title: `t${i}`, kind: "info" });
    });
    expect(entries.result.current).toHaveLength(50);
    expect(entries.result.current[0]?.title).toBe("t3");
  });

  it("rejects an undeclared category", () => {
    expect(() => notify({ category: "nope", title: "x", kind: "info" })).toThrow(
      'Unknown notification category "nope"',
    );
    // @ts-expect-error "nope" is not one of this module's categories
    expect(() => n.notify({ category: "nope", title: "x", kind: "info" })).toThrow();
  });
});

describe("read state and restoring", () => {
  beforeEach(() => setVisibility("hidden"));
  afterEach(() => {
    vi.restoreAllMocks();
    act(() => clearNotifications());
  });

  const add = (title: string) => n.notify({ category: "uploads", title, kind: "info" });

  it("marks one entry or all entries as read", () => {
    const entries = renderHook(() => useNotifications());
    act(() => {
      add("a");
      add("b");
      add("c");
    });
    const [a] = entries.result.current;
    act(() => markNotificationRead(a?.id ?? 0));
    expect(entries.result.current.map((e) => e.read)).toEqual([true, false, false]);
    act(() => markAllNotificationsRead());
    expect(entries.result.current.every((e) => e.read)).toBe(true);
  });

  it("does not notify when nothing changes", () => {
    act(() => add("a"));
    act(() => markAllNotificationsRead());
    const listener = vi.fn();
    const stop = onNotificationsChange(listener);
    markAllNotificationsRead();
    markNotificationRead(12345);
    stop();
    expect(listener).not.toHaveBeenCalled();
  });

  it("restores saved entries, optionally keeping the current ones, and caps them", () => {
    const entries = renderHook(() => useNotifications());
    act(() => add("now"));
    const saved = Array.from({ length: 50 }, (_, i) => ({
      id: i,
      createdAt: i,
      read: true,
      category: "uploads",
      title: `s${i}`,
      kind: "info" as const,
    }));
    act(() => restoreNotifications(saved.slice(0, 2), { keepCurrent: true }));
    expect(entries.result.current.map((e) => e.title)).toEqual(["s0", "s1", "now"]);
    expect(new Set(entries.result.current.map((e) => e.id)).size).toBe(3);
    act(() => restoreNotifications(saved));
    expect(entries.result.current).toHaveLength(50);
    act(() => restoreNotifications([], { keepCurrent: false }));
    expect(entries.result.current).toEqual([]);
  });

  it("reports changes until stopped", () => {
    const listener = vi.fn();
    const stop = onNotificationsChange(listener);
    act(() => add("a"));
    expect(listener).toHaveBeenLastCalledWith([expect.objectContaining({ title: "a" })]);
    stop();
    act(() => add("b"));
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

class FakeNotification {
  static permission: NotificationPermission = "granted";
  static requestPermission = vi.fn(async () => {
    FakeNotification.permission = "granted";
    return "granted" as NotificationPermission;
  });
  static instances: FakeNotification[] = [];
  onclick: (() => void) | null = null;
  close = vi.fn();
  constructor(
    public title: string,
    public options?: NotificationOptions,
  ) {
    FakeNotification.instances.push(this);
  }
}

describe("preferences and browser notifications", () => {
  beforeEach(() => {
    FakeNotification.permission = "granted";
    FakeNotification.instances = [];
    vi.stubGlobal("Notification", FakeNotification);
    setVisibility("hidden");
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    localStorage.clear();
    const { result } = renderHook(() => useToasts());
    act(() => {
      restoreNotificationPreferences({});
      clearNotifications();
      for (const t of result.current) dismissToast(t.id);
    });
  });

  it("raises a browser notification while the tab is hidden, with a category-scoped tag", () => {
    n.notify({ category: "uploads", title: "a.pdf added", body: "ok", kind: "success", tag: "t" });
    expect(FakeNotification.instances).toHaveLength(1);
    expect(FakeNotification.instances[0]).toMatchObject({
      title: "a.pdf added",
      options: { body: "ok", tag: "uploads:t" },
    });
  });

  it("raises none while the tab is visible, without permission or without support", () => {
    setVisibility("visible");
    n.notify({ category: "uploads", title: "visible", kind: "info" });
    setVisibility("hidden");
    FakeNotification.permission = "denied";
    n.notify({ category: "uploads", title: "denied", kind: "info" });
    vi.stubGlobal("Notification", undefined);
    expect(() =>
      n.notify({ category: "uploads", title: "unsupported", kind: "info" }),
    ).not.toThrow();
    expect(FakeNotification.instances).toHaveLength(0);
  });

  it("survives a browser that throws on new Notification", () => {
    vi.stubGlobal(
      "Notification",
      Object.assign(
        function Throwing() {
          throw new TypeError("Illegal constructor");
        },
        { permission: "granted" },
      ),
    );
    const entries = renderHook(() => useNotifications());
    expect(() =>
      act(() => n.notify({ category: "uploads", title: "x", kind: "info" })),
    ).not.toThrow();
    expect(entries.result.current).toHaveLength(1);
  });

  it("opens the link and focuses the window when the browser notification is clicked", () => {
    const open = vi.fn();
    const stop = onOpenNotificationLink(open);
    const focus = vi.spyOn(window, "focus").mockImplementation(() => {});
    const entries = renderHook(() => useNotifications());
    act(() => n.notify({ category: "uploads", title: "a", kind: "info", link: "/m/document/1" }));
    const raised = FakeNotification.instances[0];
    act(() => raised?.onclick?.());
    expect(focus).toHaveBeenCalled();
    expect(raised?.close).toHaveBeenCalled();
    expect(open).toHaveBeenCalledWith("/m/document/1");
    expect(entries.result.current[0]?.read).toBe(true);
    stop();
  });

  it("loads the link when the shell registered no opener", () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { assign });
    vi.spyOn(window, "focus").mockImplementation(() => {});
    n.notify({ category: "uploads", title: "a", kind: "info", link: "/m/x" });
    FakeNotification.instances[0]?.onclick?.();
    expect(assign).toHaveBeenCalledWith("/m/x");
  });

  it("Off drops the entry, toast and browser notification; In app only drops the browser one", () => {
    const entries = renderHook(() => useNotifications());
    const toasts = renderHook(() => useToasts());
    act(() => setNotificationPreference("uploads", "off"));
    setVisibility("visible");
    act(() => n.notify({ category: "uploads", title: "off", kind: "info" }));
    setVisibility("hidden");
    act(() => n.notify({ category: "uploads", title: "off", kind: "info" }));
    expect(entries.result.current).toHaveLength(0);
    expect(toasts.result.current).toHaveLength(0);
    expect(FakeNotification.instances).toHaveLength(0);

    act(() => setNotificationPreference("uploads", "app"));
    act(() => n.notify({ category: "uploads", title: "app", kind: "info" }));
    expect(entries.result.current).toHaveLength(1);
    expect(FakeNotification.instances).toHaveLength(0);
    setVisibility("visible");
    act(() => n.notify({ category: "uploads", title: "app", kind: "info" }));
    expect(toasts.result.current).toHaveLength(1);

    // Another category is unaffected.
    setVisibility("hidden");
    n.notify({ category: "answers", title: "all", kind: "info" });
    expect(FakeNotification.instances).toHaveLength(1);
  });

  it("reports, restores and ignores unknown preferences", () => {
    const hook = renderHook(() => useNotificationPreferences());
    const listener = vi.fn();
    const stop = onNotificationPreferencesChange(listener);
    act(() => setNotificationPreference("uploads", "app"));
    act(() => setNotificationPreference("uploads", "app"));
    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenLastCalledWith({ uploads: "app" });
    act(() => restoreNotificationPreferences({ answers: "off", uploads: "bogus" }));
    expect(hook.result.current).toEqual({ answers: "off" });
    stop();
  });

  it("lists the declared categories", () => {
    const { result } = renderHook(() => useNotificationCategories());
    expect(result.current.map((c) => c.id)).toEqual(expect.arrayContaining(["uploads", "answers"]));
  });

  it("requests the permission once and tells subscribers", async () => {
    FakeNotification.permission = "default";
    const state = renderHook(() => useBrowserNotificationState());
    expect(state.result.current).toBe("default");
    await act(() => requestBrowserNotifications());
    expect(state.result.current).toBe("granted");
    await requestBrowserNotifications();
    expect(FakeNotification.requestPermission).toHaveBeenCalledTimes(1);
  });

  it("copes with a failing permission request and with no support", async () => {
    FakeNotification.permission = "default";
    FakeNotification.requestPermission.mockRejectedValueOnce(new Error("blocked"));
    expect(await requestBrowserNotifications()).toBe("default");
    vi.stubGlobal("Notification", undefined);
    expect(await requestBrowserNotifications()).toBe("unsupported");
  });

  it("offers browser notifications once, as a toast whose button asks", async () => {
    FakeNotification.permission = "default";
    const toasts = renderHook(() => useToasts());
    act(() => offerBrowserNotifications());
    act(() => offerBrowserNotifications());
    expect(toasts.result.current).toHaveLength(1);
    await act(async () => toasts.result.current[0]?.action?.onSelect());
    expect(FakeNotification.requestPermission).toHaveBeenCalled();
  });

  it("makes no offer when the browser would not ask", () => {
    const toasts = renderHook(() => useToasts());
    act(() => offerBrowserNotifications());
    FakeNotification.permission = "default";
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    act(() => offerBrowserNotifications());
    act(() => offerBrowserNotifications());
    expect(toasts.result.current).toHaveLength(2);
  });
});
