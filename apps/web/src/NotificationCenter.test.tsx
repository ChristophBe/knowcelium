import {
  clearNotifications,
  defineNotifications,
  dismissToast,
  restoreNotificationPreferences,
  restoreNotifications,
} from "@knowcel/module-sdk";
import { expectNoAxeViolations } from "@knowcel/ui/testing";
import { polyfillDialog } from "@knowcel/ui/testing/dialog";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NotificationCenter } from "./NotificationCenter.tsx";

polyfillDialog();

const n = defineNotifications([
  { id: "uploads", label: "Uploads" },
  { id: "answers", label: "Answers" },
]);

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function renderCenter() {
  return render(
    <MemoryRouter>
      <NotificationCenter />
      <Where />
    </MemoryRouter>,
  );
}

const add = (title: string, link?: string) =>
  act(() => n.notify({ category: "uploads", title, kind: "success", link }));

describe("NotificationCenter", () => {
  beforeEach(() => {
    // No toasts: they would need the host and are not under test.
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  });
  afterEach(() => {
    cleanup();
    act(() => {
      clearNotifications();
      restoreNotificationPreferences({});
    });
    vi.unstubAllGlobals();
    for (let id = 1; id < 100; id++) dismissToast(id);
    vi.restoreAllMocks();
  });

  it("names the bell with the unread count", () => {
    renderCenter();
    expect(screen.getByRole("button", { name: "Notifications" })).toBeTruthy();
    add("a");
    expect(screen.getByRole("button", { name: "1 unread notification" })).toBeTruthy();
    add("b");
    add("c");
    const bell = screen.getByRole("button", { name: "3 unread notifications" });
    expect(bell.textContent).toBe("3");
  });

  it("lists the newest first and shows the empty state", () => {
    renderCenter();
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    const dialog = screen.getByRole("dialog", { name: "Notifications" });
    expect(within(dialog).getByText("Finished uploads and answers show up here.")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Clear all" }).hasAttribute("disabled")).toBe(
      true,
    );
    add("first");
    add("second");
    const items = within(dialog).getAllByRole("listitem");
    expect(items.map((i) => i.textContent)).toEqual([
      expect.stringContaining("second"),
      expect.stringContaining("first"),
    ]);
  });

  it("moves focus into the panel and back to the bell on Escape", () => {
    renderCenter();
    const bell = screen.getByRole("button", { name: "Notifications" });
    fireEvent.click(bell);
    const dialog = screen.getByRole("dialog");
    expect(document.activeElement).toBe(dialog);
    expect(bell.getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(bell);
  });

  it("closes on a click outside", () => {
    renderCenter();
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    fireEvent.pointerDown(screen.getByTestId("where"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens the link of the selected entry and marks it read", () => {
    renderCenter();
    add("a.pdf added", "/m/document/1");
    add("no link");
    fireEvent.click(screen.getByRole("button", { name: "2 unread notifications" }));
    fireEvent.click(screen.getByRole("button", { name: /a\.pdf added/ }));
    expect(screen.getByTestId("where").textContent).toBe("/m/document/1");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "1 unread notification" })).toBeTruthy();
    // An entry without a link is marked read and the panel closes without navigating.
    fireEvent.click(screen.getByRole("button", { name: "1 unread notification" }));
    fireEvent.click(screen.getByRole("button", { name: /no link/ }));
    expect(screen.getByTestId("where").textContent).toBe("/m/document/1");
    expect(screen.getByRole("button", { name: "Notifications" })).toBeTruthy();
  });

  it("marks all as read", () => {
    renderCenter();
    add("a");
    add("b");
    fireEvent.click(screen.getByRole("button", { name: "2 unread notifications" }));
    fireEvent.click(screen.getByRole("button", { name: "Mark all as read" }));
    expect(screen.getByRole("button", { name: "Notifications" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Mark all as read" }).hasAttribute("disabled")).toBe(
      true,
    );
  });

  it("asks before clearing all, and keeps the list on cancel", () => {
    renderCenter();
    add("a");
    fireEvent.click(screen.getByRole("button", { name: "1 unread notification" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    const confirm = screen.getByRole("dialog", { name: "Clear all notifications?" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Clear all notifications?" })).getByRole("button", {
        name: "Clear all",
      }),
    );
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.getByText("Finished uploads and answers show up here.")).toBeTruthy();
  });

  it("keeps Tab inside the open panel", () => {
    renderCenter();
    add("a");
    fireEvent.click(screen.getByRole("button", { name: "1 unread notification" }));
    const dialog = screen.getByRole("dialog");
    const buttons = within(dialog).getAllByRole("button");
    (buttons.at(-1) as HTMLElement).focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(document.activeElement).toBe(buttons[0]);
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(buttons.at(-1));
  });

  it("has no axe violations, closed or open", async () => {
    const { container } = renderCenter();
    restoreNotifications([]);
    add("a.pdf added");
    await expectNoAxeViolations(container);
    fireEvent.click(screen.getByRole("button", { name: "1 unread notification" }));
    await expectNoAxeViolations(document.body);
  });

  describe("settings", () => {
    const openSettings = () => {
      renderCenter();
      fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
      fireEvent.click(screen.getByRole("button", { name: "Settings" }));
      return screen.getByRole("dialog", { name: "Notifications" });
    };

    it("sets a preference per category, defaulting to in app and browser", () => {
      vi.stubGlobal("Notification", { permission: "granted" });
      const dialog = openSettings();
      const select = within(dialog).getByRole("combobox", { name: "Uploads" }) as HTMLSelectElement;
      expect(select.value).toBe("all");
      expect([...select.options].map((o) => o.textContent)).toEqual([
        "In app and browser",
        "In app only",
        "Off",
      ]);
      fireEvent.change(select, { target: { value: "off" } });
      expect(
        (within(dialog).getByRole("combobox", { name: "Uploads" }) as HTMLSelectElement).value,
      ).toBe("off");
      expect(
        (within(dialog).getByRole("combobox", { name: "Answers" }) as HTMLSelectElement).value,
      ).toBe("all");
      add("suppressed");
      expect(screen.queryByRole("button", { name: /unread/ })).toBeNull();
      fireEvent.click(within(dialog).getByRole("button", { name: "Back" }));
      expect(within(dialog).getByText("Finished uploads and answers show up here.")).toBeTruthy();
    });

    it("asks for the permission after a click, once", async () => {
      const requestPermission = vi.fn(async () => {
        N.permission = "granted";
        return "granted";
      });
      const N = Object.assign(function N() {}, { permission: "default", requestPermission });
      vi.stubGlobal("Notification", N);
      const dialog = openSettings();
      expect(requestPermission).not.toHaveBeenCalled();
      await act(async () => {
        fireEvent.click(
          within(dialog).getByRole("button", { name: "Allow browser notifications" }),
        );
      });
      expect(requestPermission).toHaveBeenCalledTimes(1);
      expect(
        within(dialog).queryByRole("button", { name: "Allow browser notifications" }),
      ).toBeNull();
      expect(within(dialog).getByText(/Browser notifications are allowed/)).toBeTruthy();
    });

    it("explains a denied permission and a missing support", () => {
      vi.stubGlobal("Notification", { permission: "denied" });
      const dialog = openSettings();
      expect(within(dialog).getByText(/blocked for this site/)).toBeTruthy();
      expect(within(dialog).queryByRole("button", { name: /Allow browser/ })).toBeNull();
      cleanup();
      vi.stubGlobal("Notification", undefined);
      const again = openSettings();
      expect(within(again).getByText(/can't show notifications/)).toBeTruthy();
    });

    it("keeps Tab inside the panel across the selects", () => {
      vi.stubGlobal("Notification", { permission: "granted" });
      const dialog = openSettings();
      const last = within(dialog).getByRole("combobox", { name: "Answers" });
      last.focus();
      fireEvent.keyDown(dialog, { key: "Tab" });
      expect(document.activeElement).toBe(within(dialog).getAllByRole("button")[0]);
    });

    it("has no axe violations", async () => {
      vi.stubGlobal("Notification", { permission: "default", requestPermission: vi.fn() });
      openSettings();
      await expectNoAxeViolations(document.body);
    });
  });
});
