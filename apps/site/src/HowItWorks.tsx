import { Card } from "@knowcel/ui";
import {
  ArrowRight,
  Contrast,
  Download,
  type LucideIcon,
  MessageSquare,
  Plug,
  ScanText,
  ShieldCheck,
  Upload,
  WifiOff,
} from "lucide-react";
import { SectionTitle } from "./Features.tsx";
import { CONNECTORS_URL } from "./Nav.tsx";

type Source = { icon: LucideIcon; title: string; text: string; href?: string };

/** Uploads and connectors are equal ways in; both end up as documents. */
const SOURCES: Source[] = [
  {
    icon: Upload,
    title: "Upload files",
    text: "Drop PDFs, Markdown and text files onto the upload area.",
  },
  {
    icon: Plug,
    title: "Connect systems",
    text: "A connector looks things up in your systems live when you ask, or syncs what they hold, so answers combine your documents with current data.",
    href: CONNECTORS_URL,
  },
];

const STEPS: { icon: LucideIcon; title: string; text: string; sources?: Source[] }[] = [
  {
    icon: Download,
    title: "Bring in your knowledge",
    text: "Add content from either source. Both end up as documents and are treated the same from here on.",
    sources: SOURCES,
  },
  {
    icon: ScanText,
    title: "Knowcelium reads them",
    text: "Each document is split into passages, and a model you choose, local by default, captures what every passage means.",
  },
  {
    icon: MessageSquare,
    title: "Ask and search",
    text: "Search by meaning or exact words, or ask in plain language, follow-ups included. The chat works out what to look up, shows what it searched, and every answer comes with its sources.",
  },
];

const PROMISES: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: WifiOff,
    title: "You decide what leaves your machine",
    text: "Documents, passages and conversations stay in your own deployment. With the default local models nothing is sent out; if you choose a hosted provider, only what that model needs to answer goes to it. Even the fonts are self-hosted.",
  },
  {
    icon: ShieldCheck,
    title: "Open and inspectable",
    text: "Every line of Knowcelium is on GitHub. Run it, read it, change it.",
  },
  {
    icon: Contrast,
    title: "Built for everyone",
    text: "Light and dark mode, full keyboard use, and colours that meet WCAG 2.2 AA in both.",
  },
];

/** The three steps from sources to answer, and why it is safe to give Knowcelium your documents. */
export function HowItWorks() {
  return (
    <section id="how-it-works" aria-labelledby="how-title" className="px-4 py-24 sm:px-8">
      <div className="mx-auto max-w-6xl">
        <SectionTitle
          id="how-title"
          eyebrow="How it works"
          title="From files and systems to answers in three steps"
        />
        <ol className="grid gap-4 lg:grid-cols-[1fr_auto_1fr_auto_1fr] lg:items-center">
          {STEPS.map((s, i) => (
            <Step key={s.title} n={i + 1} {...s} last={i === STEPS.length - 1} />
          ))}
        </ol>

        <div className="glass mt-16 rounded-panel p-6 sm:p-10">
          <h3 className="max-w-3xl text-3xl font-bold text-balance sm:text-4xl lg:text-5xl">
            Private by design. Your knowledge, on your hardware.
          </h3>
          <ul className="mt-8 grid gap-6 md:grid-cols-3">
            {PROMISES.map((p) => (
              <li key={p.title} className="flex gap-3">
                <p.icon className="mt-0.5 size-5 shrink-0 text-accent" aria-hidden="true" />
                <div>
                  <p className="text-lg font-semibold">{p.title}</p>
                  <p className="mt-1 text-base text-fg-muted">{p.text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

function Step({
  n,
  icon: Icon,
  title,
  text,
  last,
  sources,
}: {
  n: number;
  icon: LucideIcon;
  title: string;
  text: string;
  last: boolean;
  sources?: Source[];
}) {
  return (
    <>
      <li className="h-full">
        <Card className="flex h-full flex-col gap-3 p-5">
          <div className="flex items-center justify-between">
            <span className="inline-flex size-10 items-center justify-center rounded-card bg-accent-subtle text-accent">
              <Icon className="size-5" aria-hidden="true" />
            </span>
            <span className="font-mono text-3xl font-bold text-accent/40">0{n}</span>
          </div>
          <h3 className="text-xl font-semibold tracking-tight">{title}</h3>
          <p className="text-base text-fg-muted">{text}</p>
          {sources && (
            <ul className="mt-auto grid gap-2">
              {sources.map((src) => (
                <li
                  key={src.title}
                  className="flex gap-2 rounded-control border border-border bg-canvas p-3"
                >
                  <src.icon className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden="true" />
                  <div>
                    <p className="text-sm font-medium">{src.title}</p>
                    <p className="text-sm text-fg-muted">{src.text}</p>
                    {src.href && (
                      <a href={src.href} className="text-sm text-accent underline">
                        How live data works
                      </a>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </li>
      {!last && (
        <li aria-hidden="true" className="hidden justify-center text-fg-muted lg:flex">
          <ArrowRight className="size-7 animate-pulse-node text-accent" />
        </li>
      )}
    </>
  );
}
