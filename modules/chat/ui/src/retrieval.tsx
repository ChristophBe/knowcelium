import {
  type ChatMessage,
  type RetrievalSource,
  RetrievalSourceKind,
  RetrievalState,
} from "@knowcel/chat-api/knowcel/chat/v1/chat_pb";
import { Check, Spinner, TriangleAlert } from "@knowcel/ui";

const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;

/** What a searched source is called; connectors are named once they have answered. */
function sourceName({ kind, connector }: RetrievalSource): string {
  if (kind === RetrievalSourceKind.DOCUMENTS) return "Your documents";
  return connector || "Connectors";
}

/** The state in words, so that no step relies on its icon or colour. */
function stateText({ state, results }: RetrievalSource): string {
  if (state === RetrievalState.SEARCHING) return "searching…";
  if (state === RetrievalState.UNAVAILABLE) return "unavailable";
  return `found ${count(results, "result")}`;
}

/** The sources searched for the answer being prepared, each with its state. */
export function RetrievalSteps({ sources }: { sources: RetrievalSource[] }) {
  return (
    <ul
      role="status"
      aria-label="Sources searched"
      className="flex flex-col gap-1 border-t border-border pt-2 text-sm text-fg-muted"
    >
      {sources.map((s, i) => (
        // The list is replaced as a whole, and an entry's place is its identity.
        // biome-ignore lint/suspicious/noArrayIndexKey: see above
        <li key={i} className="flex items-center gap-2">
          {s.state === RetrievalState.SEARCHING && <Spinner />}
          {s.state === RetrievalState.DONE && (
            <Check className="size-4 shrink-0 text-success" aria-hidden="true" />
          )}
          {s.state === RetrievalState.UNAVAILABLE && (
            <TriangleAlert className="size-4 shrink-0 text-warning" aria-hidden="true" />
          )}
          <span className="min-w-0 wrap-anywhere">
            <span className="font-medium text-fg">{sourceName(s)}</span>: {stateText(s)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** A connector that answered in the conversation, with the answer that used it first. */
export interface ConnectorUse {
  connector: string;
  /** The first answer that used it. */
  messageId: string;
  /** Snippets of it across the conversation. */
  snippets: number;
}

/** The connectors the conversation drew on, in order of first use, from the saved citations. */
export function connectorsUsed(messages: ChatMessage[]): ConnectorUse[] {
  const used = new Map<string, ConnectorUse>();
  for (const m of messages) {
    for (const c of m.citations) {
      if (!c.connector) continue;
      const known = used.get(c.connector);
      if (known) known.snippets += 1;
      else used.set(c.connector, { connector: c.connector, messageId: m.id, snippets: 1 });
    }
  }
  return [...used.values()];
}

/** The DOM id of an answer, for links to it. */
export const messageAnchor = (id: string) => `message-${id}`;
