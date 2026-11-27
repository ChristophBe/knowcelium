import { useSyncExternalStore } from "react";
import { type ToastAction, type ToastKind, toast } from "./toast.ts";

/** A kind of notification a module sends, e.g. finished uploads; users will set preferences per category. */
export interface NotificationCategory<Id extends string = string> {
  id: Id;
  /** Names the category for users, e.g. "Uploads". */
  label: string;
}

export interface NotificationInput<Category extends string = string> {
  category: Category;
  title: string;
  body?: string;
  kind: ToastKind;
  /** Absolute path in the app that opens what the notification is about, e.g. "/m/document/<id>". */
  link?: string;
  /** Shown on the toast only; the entry keeps its `link`. */
  action?: ToastAction;
  /** A newer notification with the same tag replaces the older entry. */
  tag?: string;
}

export interface NotificationEntry extends NotificationInput {
  id: number;
  createdAt: number;
  read: boolean;
}

/** Older entries make room; the list is a glance at what finished, not a log. */
const MAX_ENTRIES = 50;

const categories = new Map<string, NotificationCategory>();
let entries: readonly NotificationEntry[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function publish(next: readonly NotificationEntry[]) {
  entries = next;
  for (const listener of listeners) listener();
}

function register(declared: readonly NotificationCategory[]) {
  for (const category of declared) categories.set(category.id, category);
}

/**
 * Tells the user that something finished. Records an entry for the
 * notification center and, while the tab is visible, shows a toast. A plain
 * function, so it also works outside of render. The category must have been
 * declared with `defineNotifications`; prefer the `notify` it returns, which
 * checks the category at compile time.
 */
export function notify(notification: NotificationInput) {
  if (!categories.has(notification.category)) {
    throw new Error(`Unknown notification category "${notification.category}"`);
  }
  const { tag } = notification;
  const kept = tag === undefined ? entries : entries.filter((e) => e.tag !== tag);
  const entry: NotificationEntry = {
    ...notification,
    id: nextId++,
    createdAt: Date.now(),
    read: false,
  };
  publish([...kept, entry].slice(-MAX_ENTRIES));
  if (document.visibilityState === "visible") {
    const message = notification.body
      ? `${notification.title}: ${notification.body}`
      : notification.title;
    if (notification.kind === "error") toast.error(message);
    else toast[notification.kind](message, { action: notification.action });
  }
}

/**
 * Declares a module's notification categories, for its manifest
 * (`notifications: n.categories`), and returns a `notify` that only accepts
 * those. Call it at the top level of `manifest.ts`.
 */
export function defineNotifications<const Id extends string>(
  declared: readonly NotificationCategory<Id>[],
) {
  register(declared);
  return {
    categories: declared as readonly NotificationCategory[],
    notify: (notification: NotificationInput<Id>) => notify(notification),
  };
}

/** Empties the list. */
export function clearNotifications() {
  publish([]);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The recorded notifications, oldest first, for the shell's notification center. */
export function useNotifications(): readonly NotificationEntry[] {
  return useSyncExternalStore(subscribe, () => entries);
}
