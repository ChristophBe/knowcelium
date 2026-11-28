import { Badge, Check, ChevronLeft, cn, Spinner } from "@knowcel/ui";
import type { ReactNode } from "react";

/**
 * The pieces of the app's chat as the recordings show them. They mirror
 * modules/chat/ui (retrieval.tsx, Answer.tsx, Conversation.tsx), so the demos
 * look like the product: change them together.
 */

/** What the user typed, right-aligned on the accent tint. */
export function UserMessage({ children }: { children: ReactNode }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-card bg-accent-subtle px-4 py-2 text-base">
        {children}
      </div>
    </div>
  );
}

/** The answer's card: the steps, the text and the sources, as one message. */
export function AnswerCard({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col gap-3 rounded-card border border-border bg-surface px-4 py-2 text-base">
      {children}
    </div>
  );
}

export type Step = {
  /** "Your documents" or the connector's name. */
  name: string;
  query: string;
  /** "2 passages" or "1 result". */
  found: string;
  searching: boolean;
};

/** The sources searched for the answer, each with its state in words and an icon. */
export function RetrievalSteps({ steps }: { steps: Step[] }) {
  return (
    <ul
      aria-label="Sources searched"
      className="flex flex-col gap-1 border-t border-border pt-2 text-sm text-fg-muted first:border-t-0 first:pt-0"
    >
      {steps.map((s) => (
        <li key={s.name} className="flex items-center gap-2">
          {s.searching ? (
            <Spinner />
          ) : (
            <Check className="size-4 shrink-0 text-success" aria-hidden="true" />
          )}
          <span className="min-w-0 wrap-anywhere">
            {s.searching ? "Searching " : "Searched "}
            <span className="font-medium text-fg">{s.name}</span> for “{s.query}”
            {s.searching ? "…" : `: found ${s.found}`}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Answer text with its `[n]` markers: runs of text, and the number of a source. */
export type Run = string | number;

export function Prose({ runs, visible }: { runs: Run[]; visible?: number }) {
  let words = 0;
  return (
    <p className="min-w-0 break-words">
      {runs.flatMap((r, i) =>
        typeof r === "number"
          ? [
              <span
                key={i}
                className={cn(
                  "font-mono text-xs transition-opacity duration-300",
                  visible !== undefined && words++ >= visible && "opacity-0",
                )}
              >
                [{r}]
              </span>,
            ]
          : r.split(/(?= )/).map((w, j) => (
              <span
                key={`${i}-${j}`}
                className={cn(
                  "transition-opacity duration-300",
                  visible !== undefined && words++ >= visible && "opacity-0",
                )}
              >
                {w}
              </span>
            )),
      )}
    </p>
  );
}

/** Number of words and markers in `runs`, as `Prose` counts them. */
export function countWords(runs: Run[]) {
  return runs.reduce<number>(
    (n, r) => n + (typeof r === "number" ? 1 : r.split(/(?= )/).length),
    0,
  );
}

export type Group = {
  title: string;
  count: number;
  unit: string;
  live?: boolean;
  active?: boolean;
};

/** A list of sources, one collapsed row per document or connector, as in the answer. */
export function SourceGroups({ label, groups }: { label: string; groups: Group[] }) {
  return (
    <ul aria-label={label} className="space-y-1 border-t border-border pt-2">
      {groups.map((g) => (
        <li
          key={g.title}
          className={cn(
            "border-l-2 pl-3 text-xs transition-colors",
            g.active ? "border-accent" : "border-border",
          )}
        >
          <div className="flex min-h-9 items-center gap-2">
            <ChevronLeft className="size-4 shrink-0 rotate-180" aria-hidden="true" />
            <span className="min-w-0 flex-1 font-medium wrap-anywhere text-fg">
              {g.title}
              {g.live && (
                <>
                  {" "}
                  <Badge tone="info">Live</Badge>
                </>
              )}
            </span>
            <span className="shrink-0 font-mono text-fg-muted">
              {g.count} {g.unit}
              {g.count === 1 ? "" : "s"}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}
