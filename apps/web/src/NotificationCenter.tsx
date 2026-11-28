import {
  clearNotifications,
  DEFAULT_NOTIFICATION_PREFERENCE,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationEntry,
  type NotificationPreference,
  onOpenNotificationLink,
  requestBrowserNotifications,
  setNotificationPreference,
  useBrowserNotificationState,
  useNotificationCategories,
  useNotificationPreferences,
  useNotifications,
} from "@knowcel/module-sdk";
import {
  AlertTriangle,
  Bell,
  Button,
  CheckCircle2,
  ConfirmDialog,
  cn,
  formatRelativeTime,
  IconButton,
  Info,
} from "@knowcel/ui";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router";

const PREFERENCE_LABELS: Record<NotificationPreference, string> = {
  all: "In app and browser",
  app: "In app only",
  off: "Off",
};

const icons = { success: CheckCircle2, info: Info, error: AlertTriangle };

/** The label of the bell: the count is part of its name, so it is announced with it. */
export function bellLabel(unread: number) {
  if (unread === 0) return "Notifications";
  return `${unread} unread ${unread === 1 ? "notification" : "notifications"}`;
}

/**
 * The bell in the shell with the number of unread notifications. It opens a
 * panel with the entries, newest first; selecting one opens what it is about
 * and marks it read. A non-modal dialog: focus moves into the panel, Tab stays
 * inside while it is open, and Esc or a click outside closes it.
 */
export function NotificationCenter() {
  const entries = useNotifications();
  const unread = entries.filter((e) => !e.read).length;
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [settings, setSettings] = useState(false);
  const bell = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) panel.current?.focus();
    else setSettings(false);
  }, [open]);

  // A browser notification's link opens in the app without a reload.
  useEffect(() => onOpenNotificationLink((link) => void navigate(link)), [navigate]);

  useEffect(() => {
    if (!open || confirming) return;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (!panel.current?.contains(target) && !bell.current?.contains(target)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open, confirming]);

  const close = () => {
    setOpen(false);
    bell.current?.focus();
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
      return;
    }
    if (e.key !== "Tab" || !panel.current) return;
    const items = [...panel.current.querySelectorAll<HTMLElement>("button, select")].filter(
      (el) => !el.hasAttribute("disabled"),
    );
    const first = items[0];
    const last = items.at(-1);
    const active = document.activeElement;
    if (e.shiftKey && (active === first || active === panel.current)) {
      e.preventDefault();
      last?.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first?.focus();
    }
  };
  const select = (entry: NotificationEntry) => {
    markNotificationRead(entry.id);
    setOpen(false);
    if (entry.link) navigate(entry.link);
    else bell.current?.focus();
  };

  return (
    <>
      <IconButton
        ref={bell}
        label={bellLabel(unread)}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => (open ? close() : setOpen(true))}
        className="relative"
      >
        <Bell className="size-5" />
        {unread > 0 && (
          <span className="-top-1 -right-1 absolute min-w-4 rounded-full bg-accent px-1 text-center font-medium text-on-accent text-xs leading-4">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </IconButton>
      {open &&
        createPortal(
          // The wrapper gives the panel the room below the header; the panel is as tall as its entries.
          <div className="pointer-events-none fixed inset-x-2 top-14 bottom-2 z-50 flex items-start md:inset-x-auto md:top-3 md:bottom-3 md:left-64 md:w-96">
            {/* biome-ignore lint/a11y/noNoninteractiveElementInteractions: handles Esc and the Tab loop for the dialog's controls. */}
            <div
              ref={panel}
              role="dialog"
              aria-label="Notifications"
              tabIndex={-1}
              onKeyDown={onKeyDown}
              className="glass-strong pointer-events-auto flex max-h-full w-full flex-col overflow-hidden rounded-card outline-none"
            >
              <div className="flex flex-wrap items-center justify-between gap-x-2 border-border border-b px-4 py-2">
                <h2 className="font-medium text-sm">{settings ? "Settings" : "Notifications"}</h2>
                <div className="flex items-center gap-1">
                  {!settings && (
                    <>
                      <Button
                        variant="ghost"
                        disabled={unread === 0}
                        onClick={markAllNotificationsRead}
                      >
                        Mark all as read
                      </Button>
                      <Button
                        variant="danger"
                        disabled={entries.length === 0}
                        onClick={() => setConfirming(true)}
                      >
                        Clear all
                      </Button>
                    </>
                  )}
                  <Button
                    variant="ghost"
                    aria-expanded={settings}
                    aria-controls="notification-settings"
                    onClick={() => setSettings(!settings)}
                  >
                    {settings ? "Back" : "Settings"}
                  </Button>
                </div>
              </div>
              {settings ? (
                <NotificationSettings />
              ) : entries.length === 0 ? (
                <p className="px-4 py-6 text-center text-fg-muted text-sm">
                  Finished uploads and answers show up here.
                </p>
              ) : (
                <ul className="min-h-0 flex-1 divide-y divide-border overflow-y-auto">
                  {[...entries].reverse().map((entry) => (
                    <li key={entry.id}>
                      <EntryRow entry={entry} onSelect={() => select(entry)} />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>,
          document.body,
        )}
      <ConfirmDialog
        open={confirming}
        title="Clear all notifications?"
        confirmLabel="Clear all"
        fallbackFocus={panel}
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          clearNotifications();
          setConfirming(false);
        }}
      >
        <p className="text-sm">All {entries.length} notifications will be removed.</p>
      </ConfirmDialog>
    </>
  );
}

function EntryRow({ entry, onSelect }: { entry: NotificationEntry; onSelect: () => void }) {
  const Icon = icons[entry.kind];
  const sentAt = { seconds: BigInt(Math.floor(entry.createdAt / 1000)) };
  return (
    <button
      type="button"
      onClick={onSelect}
      className="flex w-full items-start gap-3 px-4 py-3 text-left text-sm hover:bg-surface-muted"
    >
      <Icon
        className={cn("mt-0.5 size-4 shrink-0", entry.kind === "error" && "text-danger")}
        aria-hidden="true"
      />
      <span className="min-w-0 flex-1">
        <span className={cn("block break-words", !entry.read && "font-medium")}>{entry.title}</span>
        {entry.body && (
          <span className="block break-words text-fg-muted text-xs">{entry.body}</span>
        )}
        <span className="block text-fg-muted text-xs">{formatRelativeTime(sentAt)}</span>
      </span>
      {!entry.read && (
        <>
          <span className="mt-1.5 size-2 shrink-0 rounded-full bg-accent" aria-hidden="true" />
          <span className="sr-only">Unread</span>
        </>
      )}
    </button>
  );
}

/** The text under the permission: why browser notifications do or don't work. */
function permissionNote(state: ReturnType<typeof useBrowserNotificationState>) {
  switch (state) {
    case "unsupported":
      return "This browser can't show notifications here. You still get them here and as messages in the app.";
    case "denied":
      return "Browser notifications are blocked for this site. To get them, allow notifications for this site in your browser's settings.";
    case "granted":
      return "Browser notifications are allowed. They appear while this app is in a background tab.";
    default:
      return "Allow browser notifications to hear about finished work while this app is in a background tab.";
  }
}

/** The choice per category and the browser permission, inside the panel. */
function NotificationSettings() {
  const categories = useNotificationCategories();
  const preferences = useNotificationPreferences();
  const permission = useBrowserNotificationState();
  return (
    <div id="notification-settings" className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
      <div className="space-y-2">
        <p className="text-fg-muted text-sm">{permissionNote(permission)}</p>
        {permission === "default" && (
          <Button onClick={() => void requestBrowserNotifications()}>
            Allow browser notifications
          </Button>
        )}
      </div>
      {categories.length > 0 && (
        <ul className="space-y-3">
          {categories.map((category) => (
            <li key={category.id} className="flex items-center justify-between gap-3 text-sm">
              <label htmlFor={`notification-pref-${category.id}`}>{category.label}</label>
              <select
                id={`notification-pref-${category.id}`}
                value={preferences[category.id] ?? DEFAULT_NOTIFICATION_PREFERENCE}
                onChange={(e) =>
                  setNotificationPreference(category.id, e.target.value as NotificationPreference)
                }
                className="rounded-control border border-border-strong bg-surface px-2 py-1.5 text-sm hover:border-fg-muted"
              >
                {(Object.keys(PREFERENCE_LABELS) as NotificationPreference[]).map((value) => (
                  <option key={value} value={value}>
                    {PREFERENCE_LABELS[value]}
                  </option>
                ))}
              </select>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
