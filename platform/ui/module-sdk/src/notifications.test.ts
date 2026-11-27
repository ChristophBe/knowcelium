import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearNotifications,
  defineNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  notify,
  onNotificationsChange,
  restoreNotifications,
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
