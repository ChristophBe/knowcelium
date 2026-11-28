import { Badge, CheckCircle2, CircleHelp, cn, navItemClass, type Tone } from "@knowcel/ui";
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
import {
  AnswerCard,
  countWords,
  Prose,
  RetrievalSteps,
  type Run,
  SourceGroups,
  UserMessage,
} from "./AppChat.tsx";
import { ERP, PLM } from "./systems.ts";

/** The answer is text runs and citation numbers, so it can stream in word by word. */
const QUESTION = "Is the torque sensor v2 on track, and do we have enough sensors in stock?";
const ANSWER: Run[] = [
  "Not yet: v2 waits for prototype validation, and the prototypes from Sensora Precision are delayed ",
  1,
  ". Hamburg has 95 torque sensors on hand, with 120 reserved ",
  2,
  ". The next 300 are 7 days late because of a customs hold ",
  3,
  ".",
];

/** Where the answer's citations come from: synced documents, and a system asked live. */
export const SOURCES = [
  { title: "CR-3004 Replace torque sensor with v2", detail: `synced from ${PLM}`, cite: 1 },
  { title: "STK-4006 Torque sensor", detail: `synced from ${ERP}`, cite: 2 },
  { title: ERP, detail: `live from ${ERP}`, cite: 3, live: true },
];

/** What the model looks up before it answers, as the app's step list words it. */
export const SEARCH_STEPS = [
  { name: "Your documents", query: "torque sensor v2 status", found: "2 passages" },
  { name: ERP, query: "torque sensor shipments", found: "1 result" },
];

type Item = { name: string; icon: LucideIcon };

/** What the first scene uploads, and the connected systems the second one shows. */
const UPLOADS: Item[] = [
  { name: "handbook.pdf", icon: FileText },
  { name: "quality-manual.md", icon: FileText },
];
/** The Connectors page's rows: the connector's name and kind, and what its first sync brought in. */
const CONNECTORS = [
  { name: PLM, kind: "foundry_plm", documents: 84 },
  { name: ERP, kind: "stockwise_erp", documents: 31 },
];

const STEPS = [
  { label: "Upload", title: "Add your files", caption: "1 · Upload files" },
  { label: "Connectors", title: "Connect your systems", caption: "2 · Connect systems" },
  { label: "Ask", title: "Chat", caption: "3 · Ask, with live data" },
] as const;

/** The app's navigation; `scene` marks the page each scene shows. */
const NAV: { icon: LucideIcon; label: string; scene?: number }[] = [
  { icon: Search, label: "Search" },
  { icon: FileText, label: "Documents" },
  { icon: Upload, label: "Upload", scene: 0 },
  { icon: Plug, label: "Connectors", scene: 1 },
  { icon: MessageSquare, label: "Chat", scene: 2 },
];

/** Upload scene: each file appears, is processed for a while, then is ready. */
const FILE_STAGGER_MS = 350;
const QUEUED_MS = 250;
const FILE_PROCESS_MS = 700;
/** When a scene listing `count` items is over: the last one is ready, plus time to read. */
const itemsReadyMs = (count: number) => FILE_STAGGER_MS * (count - 1) + QUEUED_MS + FILE_PROCESS_MS;
const itemsEndMs = (count: number) => itemsReadyMs(count) + 1100;
const UPLOAD_END_MS = itemsEndMs(UPLOADS.length);
const CONNECT_END_MS = itemsEndMs(CONNECTORS.length);

/** Retrieval scene: when each search step shows, when the answer starts, how long each word takes, how long it stays. */
const STEP_MS = 600;
const STEP_START_MS = 400;
const WORD_MS = 40;
const ANSWER_START_MS = STEP_START_MS + STEP_MS * SEARCH_STEPS.length + 300;
const HOLD_MS = 3800;
const TICK_MS = 50;

const WORD_COUNT = countWords(ANSWER);
const ANSWER_END_MS = ANSWER_START_MS + WORD_MS * WORD_COUNT + HOLD_MS;
const SCENE_END_MS = [UPLOAD_END_MS, CONNECT_END_MS, ANSWER_END_MS] as const;

/**
 * A looping recording that tells what Knowcelium does: files are uploaded and
 * processed, then a question is answered with cited sources. It plays on its own
 * and can not be used: nothing in it takes focus or reacts to the pointer.
 * Before the page hydrates, and with reduced motion, it shows the answer done.
 */
export function ChatDemo() {
  const [playing, setPlaying] = useState(false);
  // Without motion (and before hydration) the recording rests on its answer, the part that matters.
  const [scene, setScene] = useState(2);
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

  return (
    <figure
      aria-label="Example of adding files and connected systems and asking a question, a recording"
      className="glass pointer-events-none relative flex flex-col overflow-hidden rounded-panel text-left select-none"
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

        {/*
          The frame's height comes from invisible copies of the finished scenes, and the
          recording is laid over them without taking part in the layout. So the height is
          constant whatever the recording shows, and nothing below it moves. Changing
          the scene cross-fades the finished one out and the next in.
        */}
        <div className="relative min-w-0 flex-1 text-sm">
          <div aria-hidden="true" inert className="invisible grid p-4">
            {STEPS.map((step, i) => (
              <div key={step.label} className="col-start-1 row-start-1 flex min-w-0 flex-col gap-3">
                <SceneView scene={i} t={SCENE_END_MS[i] ?? 0} playing={false} />
              </div>
            ))}
          </div>
          <div className="absolute inset-0 grid overflow-hidden p-4">
            {STEPS.map((step, i) => {
              const current = i === scene;
              return (
                <div
                  key={step.label}
                  aria-hidden={current ? undefined : true}
                  inert={!current}
                  className={cn(
                    "col-start-1 row-start-1 flex min-w-0 flex-col gap-3 transition-[opacity,visibility] duration-700 ease-in-out",
                    !current && "invisible opacity-0",
                  )}
                >
                  <SceneView
                    scene={i}
                    t={current ? t : (SCENE_END_MS[i] ?? 0)}
                    playing={current && playing}
                  />
                </div>
              );
            })}
          </div>
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

/** One page of the recording at time `t`. */
function SceneView({ scene, t, playing }: { scene: number; t: number; playing: boolean }) {
  if (scene === 0) {
    return (
      <>
        <p className="font-serif text-xl font-medium">{STEPS[0].title}</p>
        <UploadScene t={t} />
      </>
    );
  }
  return scene === 1 ? <ConnectorsScene t={t} /> : <AskScene t={t} playing={playing} />;
}

type Stage = { label: string; tone: Tone; progress: number };

const FILE_LABELS = ["Queued", "Processing", "Ready"] as const;
const CONNECTOR_LABELS = ["Waiting", "Syncing", "Healthy"] as const;

/** Where an item is at time `t`: waiting, being processed (or synced), or ready. */
function stage(i: number, t: number, labels: readonly [string, string, string]): Stage {
  const start = FILE_STAGGER_MS * i;
  if (t < start) return { label: "", tone: "neutral", progress: 0 };
  if (t < start + QUEUED_MS) return { label: labels[0], tone: "neutral", progress: 0 };
  if (t < start + QUEUED_MS + FILE_PROCESS_MS)
    return { label: labels[1], tone: "info", progress: (t - start - QUEUED_MS) / FILE_PROCESS_MS };
  return { label: labels[2], tone: "success", progress: 1 };
}

function UploadScene({ t }: { t: number }) {
  return (
    <>
      <div className="flex items-center gap-3 rounded-card border-2 border-dashed border-accent/40 bg-accent-subtle/50 px-4 py-3 text-sm text-fg-muted">
        <Upload className="size-6 shrink-0 text-accent" aria-hidden="true" />
        <span>Drop PDFs, Markdown or text files here</span>
      </div>
      <ItemGroup title="Uploaded files" items={UPLOADS} labels={FILE_LABELS} t={t} />
      <p
        className={cn(
          "mt-auto text-sm font-medium text-accent transition-opacity duration-500",
          t < itemsReadyMs(UPLOADS.length) && "opacity-0",
        )}
      >
        26 passages ready to search
      </p>
    </>
  );
}

/** The Connectors page as the app shows it: a table with each connector's health, last sync and documents. */
function ConnectorsScene({ t }: { t: number }) {
  return (
    <>
      <div>
        <p className="mb-1 font-mono text-xs tracking-wide text-accent uppercase">
          knowcelium / connectors
        </p>
        <p className="text-2xl font-semibold tracking-tight">Connectors</p>
        <p className="mt-1 text-sm text-fg-muted">
          The external systems whose content Knowcelium keeps in sync, and whether each one is
          working.
        </p>
      </div>
      <div className="overflow-hidden rounded-card border border-border bg-surface">
        <table aria-label="Connectors" className="w-full text-sm">
          <thead className="border-b border-border text-left text-xs text-fg-muted uppercase">
            <tr>
              <th scope="col" className="px-2 py-2 font-medium whitespace-nowrap">
                Connector
              </th>
              <th scope="col" className="px-2 py-2 font-medium whitespace-nowrap">
                Health
              </th>
              <th scope="col" className="hidden px-2 py-2 font-medium sm:table-cell">
                Last sync
              </th>
              <th scope="col" className="px-2 py-2 text-right font-medium whitespace-nowrap">
                Documents
              </th>
            </tr>
          </thead>
          <tbody>
            {CONNECTORS.map((c, i) => {
              const s = stage(i, t, CONNECTOR_LABELS);
              const healthy = s.progress === 1;
              return (
                <tr
                  key={c.name}
                  className={cn(
                    "border-b border-border align-top transition-opacity duration-300 last:border-0",
                    !s.label && "opacity-0",
                  )}
                >
                  <th scope="row" className="px-2 py-2 text-left font-medium">
                    {c.name}
                    <span className="block font-mono text-xs font-normal text-fg-muted">
                      {c.kind}
                    </span>
                  </th>
                  <td className="px-2 py-2 whitespace-nowrap">
                    <Badge tone={healthy ? "success" : "neutral"}>
                      <span className="inline-flex items-center gap-1 whitespace-nowrap">
                        {healthy ? (
                          <CheckCircle2 className="size-3.5" aria-hidden="true" />
                        ) : (
                          <CircleHelp className="size-3.5" aria-hidden="true" />
                        )}
                        {healthy ? "Healthy" : "Not synced yet"}
                      </span>
                    </Badge>
                  </td>
                  <td className="hidden px-2 py-2 whitespace-nowrap sm:table-cell">
                    {healthy ? "just now" : "Never"}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums">{healthy ? c.documents : 0}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p
        className={cn(
          "mt-auto text-sm font-medium text-accent transition-opacity duration-500",
          t < itemsReadyMs(CONNECTORS.length) && "opacity-0",
        )}
      >
        Synced documents are searchable. {ERP} is also asked live when a question needs it.
      </p>
    </>
  );
}

function ItemGroup({
  title,
  items,
  labels,
  t,
}: {
  title: string;
  items: Item[];
  labels: readonly [string, string, string];
  t: number;
}) {
  return (
    <section aria-label={title} className="space-y-1.5">
      <p aria-hidden="true" className="text-xs font-medium tracking-wide text-fg-muted uppercase">
        {title}
      </p>
      <ul className="space-y-2">
        {items.map(({ name, icon: Icon }, j) => {
          const s = stage(j, t, labels);
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
                <Badge tone={s.tone}>{s.label || labels[0]}</Badge>
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
    </section>
  );
}

function AskScene({ t, playing }: { t: number; playing: boolean }) {
  const visible = Math.max(0, Math.floor((t - ANSWER_START_MS) / WORD_MS));
  const done = visible >= WORD_COUNT;
  const typing = playing && t < ANSWER_START_MS - 200;
  const steps = SEARCH_STEPS.flatMap((step, i) => {
    const at = STEP_START_MS + STEP_MS * i;
    return t < at ? [] : [{ ...step, searching: t < at + STEP_MS }];
  });

  return (
    <>
      <UserMessage>{QUESTION}</UserMessage>

      <AnswerCard>
        <RetrievalSteps steps={steps} />
        <Prose runs={ANSWER} visible={visible} />
        {done && (
          <>
            <SourceGroups
              label="Sources"
              groups={SOURCES.filter((s) => !s.live).map((s) => ({
                title: s.title,
                count: 1,
                unit: "passage",
              }))}
            />
            <SourceGroups
              label="Connector sources"
              groups={SOURCES.filter((s) => s.live).map((s) => ({
                title: s.title,
                count: 1,
                unit: "snippet",
                live: true,
              }))}
            />
          </>
        )}
      </AnswerCard>

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
