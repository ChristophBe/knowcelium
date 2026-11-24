import type { ChatMessage } from "@knowcel/chat-api/knowcel/chat/v1/chat_pb";
import { Badge, ChevronLeft } from "@knowcel/ui";
import { useId, useState } from "react";
import { connectorsUsed, messageAnchor } from "./retrieval.tsx";

/** Moves to an answer and puts keyboard focus on it. */
function goTo(messageId: string) {
  const answer = document.getElementById(messageAnchor(messageId));
  if (!answer) return;
  answer.tabIndex = -1;
  answer.scrollIntoView?.({ block: "start" });
  answer.focus({ preventScroll: true });
}

/** The connectors a conversation has used so far, from its saved answers, each linking to the answer that used it. */
export function SourcesInChat({ messages }: { messages: ChatMessage[] }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const used = connectorsUsed(messages);
  return (
    <section aria-label="Sources in this chat" className="text-xs">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen(!open)}
        className="flex min-h-11 items-center gap-1 text-fg-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-focus"
      >
        <ChevronLeft
          className={`size-4 transition-transform ${open ? "-rotate-90" : "rotate-180"}`}
          aria-hidden="true"
        />
        Sources in this chat
        {used.length > 0 && <Badge tone="info">{used.length}</Badge>}
      </button>
      <div id={listId} hidden={!open}>
        {used.length === 0 ? (
          <p className="pb-2 text-fg-muted">No connectors used yet</p>
        ) : (
          <ul className="space-y-1 pb-2">
            {used.map((u) => (
              <li key={u.connector}>
                <button
                  type="button"
                  onClick={() => goTo(u.messageId)}
                  className="min-h-11 text-left text-accent underline focus-visible:outline-2 focus-visible:outline-focus"
                >
                  {u.connector}
                  <span className="text-fg-muted">
                    {" "}
                    · {u.snippets} snippet{u.snippets === 1 ? "" : "s"}, first used in this answer
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
