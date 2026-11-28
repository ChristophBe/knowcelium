import { cn } from "@knowcel/ui";
import { PlayCircle } from "lucide-react";
import { useEffect, useState } from "react";
import {
  AnswerCard,
  countWords,
  Prose,
  RetrievalSteps,
  type Run,
  SourceGroups,
  UserMessage,
} from "./AppChat.tsx";
import { ERP } from "./systems.ts";

/** One question that needs both kinds of knowledge, as the app's chat answers it. */
export const QUESTION =
  "Which open change requests affect parts whose supplier has a delayed shipment?";
export const ANSWER: Run[] = [
  "CR-3001 (second source for 21700 cells) is affected: its supplier's shipment SHP-5002 is 12 days late because of a cell shortage ",
  2,
  ". So is CR-3004 (torque sensor v2): SHP-5004 is 7 days late because of a customs hold ",
  2,
  ". Both change requests are open ",
  1,
  ".",
];

/** When each step starts, and how long it searches before it has found something. */
const STEPS = [
  { name: "Your documents", query: "open change requests", found: "4 passages", at: 1000 },
  { name: ERP, query: "delayed shipments", found: "2 results", at: 2000 },
];
const SEARCH_MS = 1100;
const ANSWER_AT_MS = 3600;
const WORD_MS = 45;
const WORD_COUNT = countWords(ANSWER);
const SOURCES_AT_MS = ANSWER_AT_MS + WORD_MS * WORD_COUNT + 300;
const END_MS = SOURCES_AT_MS + 4500;
const FADE_MS = 400;
const TICK_MS = 50;

/**
 * A looping recording of the app's chat on a question that synced documents
 * answer in part and a live system answers in the rest. Like the demo on the
 * home page it plays by itself and can't be used. Before hydration and with
 * reduced motion it rests on the finished answer.
 */
function Chat({ t }: { t: number }) {
  const steps = STEPS.flatMap((s) => (t < s.at ? [] : [{ ...s, searching: t < s.at + SEARCH_MS }]));
  const visible = Math.max(0, Math.floor((t - ANSWER_AT_MS) / WORD_MS));
  return (
    <div className="flex flex-col gap-4">
      <UserMessage>{QUESTION}</UserMessage>
      <AnswerCard>
        <RetrievalSteps steps={steps} />
        {t >= ANSWER_AT_MS && <Prose runs={ANSWER} visible={visible} />}
        {t >= SOURCES_AT_MS && (
          <>
            <SourceGroups
              label="Sources"
              groups={[
                { title: "CR-3001 Second source for 21700 cells", count: 1, unit: "passage" },
                { title: "CR-3004 Replace torque sensor with v2", count: 1, unit: "passage" },
              ]}
            />
            <SourceGroups
              label="Connector sources"
              groups={[{ title: ERP, count: 2, unit: "snippet", live: true }]}
            />
          </>
        )}
      </AnswerCard>
    </div>
  );
}

export function LiveDemo() {
  const [playing, setPlaying] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    setPlaying(true);
    const id = setInterval(
      () => setElapsed((t) => (t + TICK_MS >= END_MS ? 0 : t + TICK_MS)),
      TICK_MS,
    );
    return () => clearInterval(id);
  }, []);

  const t = playing ? elapsed : END_MS;
  const leaving = playing && t > END_MS - FADE_MS;

  return (
    <figure
      aria-label="Example of the chat answering from documents and a live system, a recording"
      className="glass pointer-events-none relative overflow-hidden rounded-panel text-left select-none"
    >
      <figcaption className="flex items-center gap-2 border-b border-border px-4 py-2.5 font-mono text-xs text-fg-muted">
        <span className="min-w-0 flex-1 truncate">knowcelium · chat</span>
        <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-accent-subtle px-2 py-0.5 text-accent">
          <PlayCircle className="size-3.5" aria-hidden="true" />
          Demo recording
        </span>
      </figcaption>

      {/*
        The height comes from an invisible copy of the finished chat; the recording is laid
        over it without taking part in the layout, so it can't change the height.
      */}
      <div className="relative">
        <div aria-hidden="true" inert className="invisible p-4 sm:p-6">
          <Chat t={END_MS} />
        </div>
        <div
          className={cn(
            "absolute inset-0 overflow-hidden p-4 transition-opacity duration-300 sm:p-6",
            leaving && "opacity-0",
          )}
        >
          <Chat t={t} />
        </div>
      </div>
    </figure>
  );
}
