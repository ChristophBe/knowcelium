import { defineManifest, lazySearch } from "@knowcel/module-sdk";
import { MessageSquare } from "@knowcel/ui";
import { useUnseenAnswers } from "./badge.ts";
import { chatNotifications } from "./notify.ts";

export default defineManifest({
  id: "chat",
  title: "Chat",
  icon: MessageSquare,
  notifications: chatNotifications.categories,
  nav: [{ path: "", label: "Chat", order: 10, useBadge: useUnseenAnswers }],
  search: lazySearch("Conversations", () =>
    import("./search.ts").then((m) => m.conversationSearch),
  ),
});
