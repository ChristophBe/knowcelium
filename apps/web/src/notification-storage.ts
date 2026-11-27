import {
  type NotificationEntry,
  onNotificationsChange,
  restoreNotifications,
  useCurrentUser,
} from "@knowcel/module-sdk";
import { useEffect, useRef } from "react";
import { useSession } from "./auth/AuthGate.tsx";

const KEY_PREFIX = "knowcel.notifications.";
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
 * Keeps the notification center's entries in this browser, one list per user.
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
    return stop;
  }, [key]);
}
