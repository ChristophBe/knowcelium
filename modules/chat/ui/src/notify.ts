import { defineNotifications } from "@knowcel/module-sdk";

/** The chat module's notification categories; the manifest declares them. */
export const chatNotifications = defineNotifications([{ id: "answers", label: "Answers" }]);

/** Tells the user that an answer finished; selecting the notification opens the conversation. */
export function notifyAnswerReady(conversationId: string, title: string) {
  chatNotifications.notify({
    category: "answers",
    title: "Answer ready",
    body: title || "New conversation",
    kind: "success",
    link: `/m/chat/${conversationId}`,
    // One entry per conversation, wherever the end was noticed first.
    tag: conversationId,
  });
}
