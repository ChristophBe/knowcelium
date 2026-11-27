import { Badge, cn, navItemClass, SourceNote, type Tone } from "@knowcel/ui";
import {
  ArrowUp,
  FileText,
  type LucideIcon,
  MessageSquare,
  PlayCircle,
  Plug,
  Search,
  Upload,
} from "lucide-react";
import { useEffect, useState } from "react";

type Source = { title: string; detail: string; snippet: string };

/** The answer is text runs and citation numbers, so it can stream in word by word. */
const QUESTION = "Is the torque sensor v2 on track, and do we have enough sensors in stock?";
const ANSWER: (string | number)[] = [
  "Not yet: v2 waits for prototype validation, and the prototypes from Sensora Precision are delayed",
  1,
  ". Hamburg has 95 torque sensors on hand, with 120 reserved",
  2,
  ".",
];
export const SOURCES: Source[] = [
  {
    title: "CR-3004 Replace torque sensor with v2",
    detail: "from showcase-engineering",
    snippet:
      "v2 doubles the resolution. Depends on prototype validation; delivery of prototypes from SUP-1004 is delayed…",
  },
  {
    title: "STK-4006 Torque sensor",
    detail: "from showcase-logistics",
    snippet: "On hand 95, reserved 120, reorder level 100, warehouse Hamburg…",
  },
];

/** What the model searches for before it answers, worded as in the app's step list. */
export const SEARCH_STEPS = [
  { source: "showcase-engineering", query: "torque sensor v2 status", found: "1 result" },
  { source: "showcase-logistics", query: "torque sensor stock Hamburg", found: "1 result" },
];

/** What the first scene adds: an uploaded file and two connected systems. */
const FILES = [
  { name: "handbook.pdf", icon: FileText },
  { name: "showcase-engineering", icon: Plug },
  { name: "showcase-logistics", icon: Plug },
];

const STEPS = [
  { label: "Upload", title: "Add your sources", caption: "1 · Files and systems" },
  { label: "Ask", title: "Chat", caption: "2 · Ask, with sources" },
] as const;

/** The app's navigation; `scene` marks the page each scene shows. */
const NAV: { icon: LucideIcon; label: string; scene?: number }[] = [
  { icon: Search, label: "Search" },
  { icon: FileText, label: "Documents" },
  { icon: Upload, label: "Upload", scene: 0 },
  { icon: MessageSquare, label: "Chat", scene: 1 },
];

/** Upload scene: each file appears, is processed for a while, then is ready. */
const FILE_STAGGER_MS = 900;
const FILE_PROCESS_MS = 1500;
const UPLOAD_END_MS = FILE_STAGGER_MS * (FILES.length - 1) + FILE_PROCESS_MS + 900 + 1800;

/** Retrieval scene: when each search step shows, when the answer starts, how long each word takes, how long it stays. */
const STEP_MS = 800;
const STEP_START_MS = 600;
const WORD_MS = 55;
const ANSWER_START_MS = STEP_START_MS + STEP_MS * SEARCH_STEPS.length + 500;
const HOLD_MS = 4200;
const FADE_MS = 500;
const TICK_MS = 50;

type Word = { text: string; cite?: number };

/** Splits an answer into the words that appear one by one; a citation is a word of its own. */
function toWords(answer: (string | number)[]): Word[] {
  return answer.flatMap((part) =>
    typeof part === "number"
      ? [{ text: `[${part}]`, cite: part }]
      : part.split(/(?= )/).map((text) => ({ text })),
  );
}

const WORDS = toWords(ANSWER);
const ANSWER_END_MS = ANSWER_START_MS + WORD_MS * WORDS.length + HOLD_MS;
const SCENE_END_MS = [UPLOAD_END_MS, ANSWER_END_MS] as const;

/**
 * A looping recording that tells what Knowcelium does: files are uploaded and
 * processed, then a question is answered with cited sources. It plays on its own
 * and can not be used: nothing in it takes focus or reacts to the pointer.
 * Before the page hydrates, and with reduced motion, it shows the answer done.
 */
export function ChatDemo() {
  const [playing, setPlaying] = useState(false);
  // Without motion (and before hydration) the recording rests on its answer, the part that matters.
  const [scene, setScene] = useState(1);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    setPlaying(true);
    setScene(0);
    setElapsed(0);
    const id = setInterval(() => setElapsed((t) => t + TICK_MS), TICK_MS);
    return () => clearInterval(id);
  }, []);

  const end = SCENE_END_MS[scene] ?? UPLOAD_END_MS;

  useEffect(() => {
    if (playing && elapsed >= end) {
      setScene((i) => (i + 1) % STEPS.length);
      setElapsed(0);
    }
  }, [playing, elapsed, end]);

  const t = playing ? elapsed : end;
  const leaving = playing && t > end - FADE_MS;

  return (
    <figure
      aria-label="Example of adding files and connected systems and asking a question, a recording"
      className="glass pointer-events-none relative flex h-[40rem] flex-col sm:h-[32rem] overflow-hidden rounded-panel text-left select-none"
    >
      <figcaption className="flex items-center gap-2 border-b border-border px-4 py-2.5 font-mono text-xs text-fg-muted">
        <span className="flex gap-1" aria-hidden="true">
          <span className="size-2.5 rounded-full bg-border" />
          <span className="size-2.5 rounded-full bg-border" />
          <span className="size-2.5 rounded-full bg-border" />
        </span>
        <span className="ml-2 min-w-0 flex-1 truncate">knowcelium</span>
        <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-accent-subtle px-2 py-0.5 text-accent">
          <PlayCircle className="size-3.5" aria-hidden="true" />
          Demo recording
        </span>
      </figcaption>

      <div className="flex min-h-0 flex-1">
        {/* The app's sidebar: logo, navigation with the current page tinted. */}
        <div
          aria-hidden="true"
          className="glass-area hidden w-36 shrink-0 flex-col border-r border-border xl:flex"
        >
          <ul className="flex flex-col gap-0.5 px-2 pt-4">
            {NAV.map((n) => (
              <li
                key={n.label}
                className={navItemClass(n.scene === scene, "px-2.5 py-1.5 text-xs")}
              >
                <n.icon className="size-3.5" />
                {n.label}
              </li>
            ))}
          </ul>
        </div>

        {/* Remounting on the scene restarts the entrance animations. */}
        <div
          key={scene}
          className={cn(
            "flex min-w-0 flex-1 flex-col gap-3 p-4 text-sm transition-opacity duration-500",
            leaving && "opacity-0",
          )}
        >
          <p className="font-serif text-xl font-medium">{STEPS[scene]?.title}</p>
          {scene === 0 ? <UploadScene t={t} /> : <AskScene t={t} playing={playing} />}
        </div>
      </div>

      <div
        aria-hidden="true"
        className="glass-subtle flex items-center justify-center gap-3 border-t border-border py-2.5 text-xs"
      >
        {STEPS.map((s, i) => (
          <span
            key={s.label}
            className={cn(
              "inline-flex items-center gap-2 transition-colors duration-500",
              i === scene ? "text-accent" : "text-fg-muted",
            )}
          >
            <span
              className={cn(
                "h-1.5 rounded-full transition-all duration-500",
                i === scene ? "w-8 bg-accent" : "w-1.5 bg-border",
              )}
            />
            {s.caption}
          </span>
        ))}
      </div>
    </figure>
  );
}

type Stage = { label: string; tone: Tone; progress: number };

/** Where a file is at time `t`: waiting, being processed, or ready. */
function stage(i: number, t: number): Stage {
  const start = FILE_STAGGER_MS * i;
  if (t < start) return { label: "", tone: "neutral", progress: 0 };
  if (t < start + 500) return { label: "Queued", tone: "neutral", progress: 0 };
  if (t < start + 500 + FILE_PROCESS_MS)
    return { label: "Processing", tone: "info", progress: (t - start - 500) / FILE_PROCESS_MS };
  return { label: "Ready", tone: "success", progress: 1 };
}

function UploadScene({ t }: { t: number }) {
  const allReady = t >= FILE_STAGGER_MS * (FILES.length - 1) + 500 + FILE_PROCESS_MS;
  return (
    <>
      <div className="flex items-center gap-3 rounded-card border-2 border-dashed border-accent/40 bg-accent-subtle/50 px-4 py-4 text-sm text-fg-muted">
        <Upload className="size-6 shrink-0 text-accent" aria-hidden="true" />
        <span>Drop PDFs, Markdown or text files here, or connect a system</span>
      </div>
      <ul className="space-y-2">
        {FILES.map(({ name, icon: Icon }, i) => {
          const s = stage(i, t);
          return (
            <li
              key={name}
              className={cn(
                "rounded-card border border-border bg-surface px-3 py-2 transition-opacity duration-300",
                !s.label && "opacity-0",
              )}
            >
              <div className="flex items-center gap-3">
                <Icon className="size-5 shrink-0 text-accent" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate font-mono text-sm">{name}</span>
                <Badge tone={s.tone}>{s.label || "Queued"}</Badge>
              </div>
              <div className="mt-2 h-1 overflow-hidden rounded-full bg-border">
                <div
                  className="h-full rounded-full bg-accent"
                  style={{ width: `${Math.round(s.progress * 100)}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
      <p
        className={cn(
          "mt-auto text-sm font-medium text-accent transition-opacity duration-500",
          !allReady && "opacity-0",
        )}
      >
        42 passages ready to search
      </p>
    </>
  );
}

function AskScene({ t, playing }: { t: number; playing: boolean }) {
  const visible = Math.max(0, Math.floor((t - ANSWER_START_MS) / WORD_MS));
  const done = visible >= WORDS.length;
  const lastCite = WORDS.slice(0, visible).findLast((w) => w.cite)?.cite;
  const active = done ? null : (lastCite ?? null);
  const typing = playing && t < ANSWER_START_MS - 200;

  return (
    <>
      <div className="flex justify-end">
        <p className="max-w-[90%] animate-rise rounded-card bg-accent-subtle px-3 py-2 text-sm">
          {QUESTION}
        </p>
      </div>

      <ul aria-label="Search steps" className="space-y-1 text-xs text-fg-muted">
        {SEARCH_STEPS.map((step, i) => (
          <li
            key={step.source}
            className={cn(
              "flex items-center gap-2 transition-opacity duration-300",
              t < STEP_START_MS + STEP_MS * i && "opacity-0",
            )}
          >
            <Search className="size-3.5 shrink-0 text-accent" aria-hidden="true" />
            <span className="min-w-0">
              Searched {step.source} for “{step.query}”: found {step.found}
            </span>
          </li>
        ))}
      </ul>

      <div className="@container rounded-card border border-border bg-surface px-3 py-2.5 text-sm">
        <div className="grid gap-x-6 gap-y-4 @2xl:grid-cols-[minmax(0,1fr)_12rem]">
          <p className="min-w-0">
            {WORDS.map((w, i) => (
              <span
                key={i}
                className={cn(
                  "transition-opacity duration-300",
                  i >= visible && "opacity-0",
                  w.cite !== undefined && "mx-0.5 font-mono text-xs text-accent",
                )}
              >
                {w.text}
              </span>
            ))}
          </p>
          <ul
            aria-label="Sources"
            className={cn("space-y-3 transition-opacity duration-500", !done && "opacity-30")}
          >
            {SOURCES.map((s, i) => (
              <SourceNote
                key={s.title}
                n={i + 1}
                title={s.title}
                detail={s.detail}
                snippet={s.snippet}
                active={active === i + 1}
              />
            ))}
          </ul>
        </div>
      </div>

      <div
        aria-hidden="true"
        className="glass-strong mt-auto flex items-center gap-3 rounded-panel py-1.5 pr-1.5 pl-4 text-sm text-fg-muted"
      >
        <span className="flex-1">
          {typing ? (
            <span className="inline-block h-5 w-px animate-caret bg-fg align-middle" />
          ) : (
            "Ask something…"
          )}
        </span>
        <span className="inline-flex size-8 items-center justify-center rounded-full bg-accent text-on-accent">
          <ArrowUp className="size-4" />
        </span>
      </div>
    </>
  );
}
