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
function stateText({ state, results, kind }: RetrievalSource): string {
  if (state === RetrievalState.SEARCHING) return "searching…";
  if (state === RetrievalState.UNAVAILABLE) return "unavailable";
  return `found ${count(results, kind === RetrievalSourceKind.DOCUMENTS ? "passage" : "result")}`;
}

/** The step in words. A step the model chose a query for names it. */
function StepText({ step }: { step: RetrievalSource }) {
  const name = <span className="font-medium text-fg">{sourceName(step)}</span>;
  if (!step.query) {
    return (
      <>
        {name}: {stateText(step)}
      </>
    );
  }
  const query = `“${step.query}”`;
  if (step.state === RetrievalState.SEARCHING) {
    return (
      <>
        Searching {name} for {query}…
      </>
    );
  }
  return (
    <>
      Searched {name} for {query}: {stateText(step)}
    </>
  );
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
        // The steps only grow and never reorder, so their position is their identity.
        <li key={i} className="flex items-center gap-2">
          {s.state === RetrievalState.SEARCHING && <Spinner />}
          {s.state === RetrievalState.DONE && (
            <Check className="size-4 shrink-0 text-success" aria-hidden="true" />
          )}
          {s.state === RetrievalState.UNAVAILABLE && (
            <TriangleAlert className="size-4 shrink-0 text-warning" aria-hidden="true" />
          )}
          <span className="min-w-0 wrap-anywhere">
            <StepText step={s} />
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Whether the model chose what to search for, so that the steps are worth keeping. */
export const hasQueries = (steps: RetrievalSource[]) => steps.some((s) => s.query);

/** How many queries the collapsed summary names; the rest are in the list. */
const SUMMARY_QUERIES = 3;

/** What an answer searched for, collapsed to the queries until the user opens it. */
export function SearchedSummary({ steps }: { steps: RetrievalSource[] }) {
  if (!hasQueries(steps)) return null;
  const queries = [...new Set(steps.map((s) => s.query).filter(Boolean))];
  return (
    <details className="group text-sm text-fg-muted">
      <summary className="cursor-pointer rounded-control wrap-anywhere focus-visible:outline-2 focus-visible:outline-offset-2">
        {`Searched for ${queries
          .slice(0, SUMMARY_QUERIES)
          .map((q) => `“${q}”`)
          .join(
            ", ",
          )}${queries.length > SUMMARY_QUERIES ? ` and ${queries.length - SUMMARY_QUERIES} more` : ""}`}
      </summary>
      <ul aria-label="Searches" className="mt-2 flex flex-col gap-1">
        {steps.map((s, i) => (
          <li key={i} className="wrap-anywhere">
            <StepText step={s} />
          </li>
        ))}
      </ul>
    </details>
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
