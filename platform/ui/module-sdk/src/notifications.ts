import { useSyncExternalStore } from "react";
import { type ToastAction, type ToastKind, toast } from "./toast.ts";

/** A kind of notification a module sends, e.g. finished uploads; users set preferences per category. */
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
  /** A newer notification of the same category with the same tag replaces the older entry and browser notification. */
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
let categoryList: readonly NotificationCategory[] = [];
let entries: readonly NotificationEntry[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function publish(next: readonly NotificationEntry[]) {
  entries = next;
  for (const listener of listeners) listener();
}

function register(declared: readonly NotificationCategory[]) {
  for (const category of declared) categories.set(category.id, category);
  categoryList = [...categories.values()];
  for (const listener of preferenceListeners) listener();
}

/** Where a category's notifications go: the entry, toast and browser notification; the entry and toast only; or nowhere. */
export type NotificationPreference = "all" | "app" | "off";

/** What an unset category does. */
export const DEFAULT_NOTIFICATION_PREFERENCE: NotificationPreference = "all";

/** The permission as the settings explain it: "unsupported" when the browser has no `Notification`. */
export type BrowserNotificationState = NotificationPermission | "unsupported";

let preferences: Readonly<Record<string, NotificationPreference>> = {};
const preferenceListeners = new Set<() => void>();
const permissionListeners = new Set<() => void>();
let openLink: ((link: string) => void) | null = null;

const isPreference = (v: unknown): v is NotificationPreference =>
  v === "all" || v === "app" || v === "off";

function preferenceOf(category: string): NotificationPreference {
  return preferences[category] ?? DEFAULT_NOTIFICATION_PREFERENCE;
}

/** Sets what happens to a category's notifications; a no-op when unchanged. */
export function setNotificationPreference(category: string, preference: NotificationPreference) {
  if (preferenceOf(category) === preference) return;
  preferences = { ...preferences, [category]: preference };
  for (const listener of preferenceListeners) listener();
}

/** Replaces every preference with saved ones, for the shell once it knows whose they are; unknown values are ignored. */
export function restoreNotificationPreferences(saved: Readonly<Record<string, unknown>>) {
  preferences = Object.fromEntries(
    Object.entries(saved).filter(([, v]) => isPreference(v)),
  ) as Record<string, NotificationPreference>;
  for (const listener of preferenceListeners) listener();
}

/** Calls `listener` with the explicitly set preferences after every change, e.g. to save them; returns how to stop. */
export function onNotificationPreferencesChange(
  listener: (preferences: Readonly<Record<string, NotificationPreference>>) => void,
) {
  const run = () => listener(preferences);
  preferenceListeners.add(run);
  return () => {
    preferenceListeners.delete(run);
  };
}

function subscribePreferences(listener: () => void) {
  preferenceListeners.add(listener);
  return () => {
    preferenceListeners.delete(listener);
  };
}

/** The explicitly set preferences by category id; a category missing from it has the default. */
export function useNotificationPreferences(): Readonly<Record<string, NotificationPreference>> {
  return useSyncExternalStore(subscribePreferences, () => preferences);
}

/** Every declared category, in declaration order, for the preferences in the notification center. */
export function useNotificationCategories(): readonly NotificationCategory[] {
  return useSyncExternalStore(subscribePreferences, () => categoryList);
}

/** Whether the browser can raise notifications, and whether the user allowed them. */
export function browserNotificationState(): BrowserNotificationState {
  return typeof Notification === "undefined" ? "unsupported" : Notification.permission;
}

function subscribePermission(listener: () => void) {
  permissionListeners.add(listener);
  return () => {
    permissionListeners.delete(listener);
  };
}

/** The browser permission, re-rendering after `requestBrowserNotifications`. */
export function useBrowserNotificationState(): BrowserNotificationState {
  return useSyncExternalStore(subscribePermission, browserNotificationState);
}

/**
 * Asks the browser for permission to raise notifications. Browsers only show
 * the prompt for a user action, so call it from a click handler. Resolves with
 * the outcome and never rejects; does nothing once the user has decided.
 */
export async function requestBrowserNotifications(): Promise<BrowserNotificationState> {
  if (browserNotificationState() === "default") {
    try {
      await Notification.requestPermission();
    } catch {
      // Treated as undecided; the settings keep offering it.
    }
    for (const listener of permissionListeners) listener();
  }
  return browserNotificationState();
}

/** Set once the user was offered browser notifications, so the offer comes only once. */
const OFFERED_KEY = "knowcel.notifications.offered";

/**
 * Offers browser notifications once, as a toast whose button asks the browser,
 * and only while the browser would still ask. Call it after a user action that
 * starts something long-running. The same permission is always available in the
 * notification center's settings.
 */
export function offerBrowserNotifications() {
  if (browserNotificationState() !== "default") return;
  try {
    if (localStorage.getItem(OFFERED_KEY)) return;
    localStorage.setItem(OFFERED_KEY, "1");
  } catch {
    // Without storage the offer is shown every time; that is better than never.
  }
  toast.info("Want to leave while this finishes? Get a notification when it's ready.", {
    action: {
      label: "Enable notifications",
      onSelect: () => void requestBrowserNotifications(),
    },
  });
}

/**
 * Tells the shell how to open a notification's link, e.g. by navigating its
 * router; returns how to stop. Without one, the link is opened by loading it.
 */
export function onOpenNotificationLink(open: (link: string) => void) {
  openLink = open;
  return () => {
    if (openLink === open) openLink = null;
  };
}

function raiseBrowserNotification(entry: NotificationEntry) {
  if (browserNotificationState() !== "granted") return;
  try {
    const raised = new Notification(entry.title, {
      body: entry.body,
      // Scoped to the category, like the entry's replacement.
      tag: entry.tag === undefined ? undefined : `${entry.category}:${entry.tag}`,
    });
    raised.onclick = () => {
      window.focus();
      raised.close();
      markNotificationRead(entry.id);
      const { link } = entry;
      if (link) {
        if (openLink) openLink(link);
        else window.location.assign(link);
      }
    };
  } catch {
    // Some browsers (Android Chrome) only allow notifications through a service worker.
  }
}

/**
 * Tells the user that something finished, as the user's preference for the
 * category allows. Records an entry for the notification center and, while the
 * tab is visible, shows a toast; while it is hidden, also raises a browser
 * notification when the user allowed them. A plain function, so it also works
 * outside of render. The category must have been declared with
 * `defineNotifications`; prefer the `notify` it returns, which checks the
 * category at compile time.
 */
export function notify(notification: NotificationInput) {
  if (!categories.has(notification.category)) {
    throw new Error(`Unknown notification category "${notification.category}"`);
  }
  const preference = preferenceOf(notification.category);
  if (preference === "off") return;
  const { tag, category } = notification;
  const kept =
    tag === undefined ? entries : entries.filter((e) => e.category !== category || e.tag !== tag);
  const entry: NotificationEntry = {
    ...notification,
    id: nextId++,
    createdAt: Date.now(),
    read: false,
  };
  publish([...kept, entry].slice(-MAX_ENTRIES));
  if (typeof document !== "undefined" && document.visibilityState === "visible") {
    const message = notification.body
      ? `${notification.title}: ${notification.body}`
      : notification.title;
    toast[notification.kind](message, { action: notification.action });
  } else if (preference === "all") {
    raiseBrowserNotification(entry);
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

/** Marks one entry as read. */
export function markNotificationRead(id: number) {
  if (entries.some((e) => e.id === id && !e.read)) {
    publish(entries.map((e) => (e.id === id ? { ...e, read: true } : e)));
  }
}

/** Marks every entry as read. */
export function markAllNotificationsRead() {
  if (entries.some((e) => !e.read)) publish(entries.map((e) => ({ ...e, read: true })));
}

/**
 * Loads saved entries (oldest first), for the shell once it knows whose they
 * are. With `keepCurrent`, entries recorded in the meantime follow the saved
 * ones; otherwise they are dropped. Ids are assigned anew.
 */
export function restoreNotifications(
  saved: readonly NotificationEntry[],
  { keepCurrent = false }: { keepCurrent?: boolean } = {},
) {
  const all = keepCurrent ? [...saved, ...entries] : saved;
  publish(all.slice(-MAX_ENTRIES).map((e) => ({ ...e, id: nextId++ })));
}

/** Calls `listener` with the entries after every change, e.g. to save them; returns how to stop. */
export function onNotificationsChange(listener: (entries: readonly NotificationEntry[]) => void) {
  const run = () => listener(entries);
  listeners.add(run);
  return () => {
    listeners.delete(run);
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
