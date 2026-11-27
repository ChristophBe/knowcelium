import {
  type NotificationEntry,
  type NotificationPreference,
  onNotificationPreferencesChange,
  onNotificationsChange,
  restoreNotificationPreferences,
  restoreNotifications,
  useCurrentUser,
} from "@knowcel/module-sdk";
import { useEffect, useRef } from "react";
import { useSession } from "./auth/AuthGate.tsx";

const KEY_PREFIX = "knowcel.notifications.";
const PREFERENCES_PREFIX = "knowcel.notification-preferences.";
const KINDS = ["success", "info", "error"];

/** Reads a user's saved entries; anything unreadable counts as none. */
export function loadNotifications(key: string): NotificationEntry[] {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(KEY_PREFIX + key) ?? "[]");
    if (!Array.isArray(saved)) return [];
    return saved.filter(
      (e): e is NotificationEntry =>
        typeof e === "object" &&
        e !== null &&
        typeof e.category === "string" &&
        typeof e.title === "string" &&
        typeof e.createdAt === "number" &&
        typeof e.read === "boolean" &&
        KINDS.includes(e.kind),
    );
  } catch {
    return [];
  }
}

/** Saves a user's entries. A toast's action is a function and stays out; storage may be full or blocked. */
export function saveNotifications(key: string, entries: readonly NotificationEntry[]) {
  try {
    const plain = entries.map(({ action: _action, ...rest }) => rest);
    localStorage.setItem(KEY_PREFIX + key, JSON.stringify(plain));
  } catch {
    // The list then lives for this page only.
  }
}

/** Reads a user's saved preferences by category; anything unreadable counts as none. */
export function loadNotificationPreferences(key: string): Record<string, NotificationPreference> {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(PREFERENCES_PREFIX + key) ?? "{}");
    if (typeof saved !== "object" || saved === null || Array.isArray(saved)) return {};
    return saved as Record<string, NotificationPreference>;
  } catch {
    return {};
  }
}

/** Saves a user's preferences; storage may be full or blocked. */
export function saveNotificationPreferences(
  key: string,
  preferences: Readonly<Record<string, NotificationPreference>>,
) {
  try {
    localStorage.setItem(PREFERENCES_PREFIX + key, JSON.stringify(preferences));
  } catch {
    // The preferences then hold for this page only.
  }
}

/**
 * Whose notifications these are: the signed-in user's id, "anonymous" when the
 * shell runs without sign-in, and null while the user is not known (or could
 * not be loaded), when nothing is read or written so that no one sees or
 * overwrites another user's list.
 */
function useStorageKey(): string | null {
  const session = useSession();
  const user = useCurrentUser();
  if (!session) return "anonymous";
  return user?.id ?? null;
}

/**
 * Keeps the notification center's entries and preferences in this browser, one set per user.
 * Mount it once, in the shell.
 */
export function useNotificationStorage() {
  const key = useStorageKey();
  const first = useRef(true);
  useEffect(() => {
    if (key === null) return;
    // Saves every change, including the restore below, which merges what was recorded before.
    const stop = onNotificationsChange((entries) => saveNotifications(key, entries));
    // Entries recorded before the user was known are theirs; after a change of user they are not.
    restoreNotifications(loadNotifications(key), { keepCurrent: first.current });
    first.current = false;
    // Unknown values are dropped on restore; the saved list is rewritten with the next change.
    restoreNotificationPreferences(loadNotificationPreferences(key));
    const stopPreferences = onNotificationPreferencesChange((p) =>
      saveNotificationPreferences(key, p),
    );
    return () => {
      stop();
      stopPreferences();
    };
  }, [key]);
}
