import { Badge, buttonClass, Card } from "@knowcel/ui";
import {
  ArrowDown,
  ArrowRight,
  Database,
  FlaskConical,
  type LucideIcon,
  Plug,
  Radio,
} from "lucide-react";
import { SectionTitle } from "./Features.tsx";
import { DotGrid } from "./Graphics.tsx";
import { LiveDemo } from "./LiveDemo.tsx";
import { repoPath } from "./links.ts";
import { BASE } from "./Nav.tsx";
import { Page } from "./Page.tsx";
import { ERP, PLM } from "./systems.ts";

const MODES: { icon: LucideIcon; title: string; method: string; text: string; flow: string[] }[] = [
  {
    icon: Radio,
    title: "Live search",
    method: "search",
    text: "When someone asks a question, chat asks the connected system at that moment and cites what it returns next to document passages. Nothing is copied, so the answer is as current as the system. This is what connectors are for.",
    flow: ["question", "connector", "your system", "cited answer"],
  },
  {
    icon: Database,
    title: "Sync",
    method: "list_changes",
    text: "On a schedule the connector copies what the system holds into documents, which then work like uploads. A good fit for content that changes slowly. A connector can do both.",
    flow: ["your system", "connector", "documents", "search and chat"],
  },
];

const PROVIDES: {
  name: string;
  repo: string;
  kind: string;
  synced: string[];
  live?: string[];
}[] = [
  {
    name: PLM,
    repo: "showcase-engineering",
    kind: "An engineering system: product lifecycle and change management",
    synced: [
      "Parts, with status and supplier",
      "Specifications per part",
      "Change requests: what, why and which parts",
    ],
  },
  {
    name: ERP,
    repo: "showcase-logistics",
    kind: "A logistics system: suppliers, warehouse and shipments",
    synced: ["Suppliers, with their rating", "Stock per part: on hand, reserved, reorder level"],
    live: ["Shipments: status, delay in days and the reason, asked when you ask"],
  },
];

const QUESTIONS: { q: string; from: string; live: boolean }[] = [
  {
    q: "Which open change requests affect parts whose supplier has a delayed shipment?",
    from: "Change requests from documents, delays live from the logistics system",
    live: true,
  },
  {
    q: "How many torque sensors are in stock and when does Sensora Precision deliver more?",
    from: "Stock from documents, the delivery and its delay live",
    live: true,
  },
  {
    q: "Is the torque sensor v2 on track, and do we have enough sensors in stock?",
    from: "Change request and stock from documents, shipment status live",
    live: true,
  },
  {
    q: "Which open change requests concern parts from our lowest-rated supplier, and why was the change requested?",
    from: "Synced documents from both systems, no live lookup needed",
    live: false,
  },
];

/** What connectors are, why live data matters, and what the two example systems provide. */
export function ConnectorsPage() {
  return (
    <Page page="connectors">
      <header className="relative isolate px-4 pt-16 pb-12 sm:px-8 sm:pt-24">
        <DotGrid />
        <div className="mx-auto grid max-w-6xl gap-12 lg:grid-cols-2 lg:items-center">
          <div>
            <p className="mb-3 font-mono text-sm tracking-wide text-accent uppercase">Connectors</p>
            <h1 className="font-bold text-balance text-fg text-3xl sm:text-4xl lg:text-5xl">
              What you know, <span className="text-gradient">and what is true right now.</span>
            </h1>
            <p className="mt-6 text-lg text-pretty text-fg-muted sm:text-xl">
              Documents hold what changes slowly. A connector gives Knowcelium access to another
              system, such as an ERP, a ticket tracker or a wiki, and asks it live when someone
              needs an answer. One question can use both: the manual, and the shipment that is late
              today.
            </p>
          </div>
          <div className="min-w-0">
            <LiveDemo />
          </div>
        </div>
      </header>

      <section aria-labelledby="modes-title" className="px-4 py-16 sm:px-8">
        <div className="mx-auto max-w-6xl">
          <SectionTitle
            id="modes-title"
            eyebrow="Concept"
            title="Extend static knowledge with live data"
            text="Uploads and synced systems give Knowcelium a base of knowledge. Live search adds what only the source system knows at this moment. You write a small Python class; the ingestion worker handles scheduling, settings, documents and status."
          />
          <ul className="grid gap-6 lg:grid-cols-2">
            {MODES.map((m) => (
              <li key={m.title} className="min-w-0">
                <Card className="flex h-full flex-col gap-3 p-6">
                  <div className="flex items-center gap-3">
                    <span className="inline-flex size-10 items-center justify-center rounded-card bg-accent-subtle text-accent">
                      <m.icon className="size-5" aria-hidden="true" />
                    </span>
                    <h3 className="text-2xl font-semibold tracking-tight">{m.title}</h3>
                    <Badge>
                      <code>{m.method}</code>
                    </Badge>
                  </div>
                  <p className="flex-1 text-base text-fg-muted">{m.text}</p>
                  <Flow steps={m.flow} />
                </Card>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section aria-labelledby="examples-title" className="px-4 py-16 sm:px-8">
        <div className="mx-auto max-w-6xl">
          <SectionTitle
            id="examples-title"
            eyebrow="Examples"
            title="Two example systems, and what they provide"
            text="The recordings connect two mock systems of Velora Mobility, a fictional e-bike maker. They show what the connector SDK can do: they are examples, not features of Knowcelium, and they are not part of the main stack."
          />
          <ul className="grid gap-6 lg:grid-cols-2">
            {PROVIDES.map((s) => (
              <li key={s.name} className="min-w-0">
                <Card className="flex h-full flex-col gap-4 p-6">
                  <div className="flex flex-wrap items-center gap-3">
                    <Plug className="size-5 text-accent" aria-hidden="true" />
                    <h3 className="text-xl font-semibold">{s.name}</h3>
                    <Badge tone="info">Example</Badge>
                  </div>
                  <p className="text-base text-fg-muted">{s.kind}</p>
                  <div>
                    <p className="mb-1 text-sm font-medium">Synced into documents</p>
                    <ul className="list-disc space-y-0.5 pl-5 text-base text-fg-muted">
                      {s.synced.map((p) => (
                        <li key={p}>{p}</li>
                      ))}
                    </ul>
                  </div>
                  {s.live && (
                    <div>
                      <p className="mb-1 flex items-center gap-2 text-sm font-medium">
                        Looked up live <Badge tone="info">Live</Badge>
                      </p>
                      <ul className="list-disc space-y-0.5 pl-5 text-base text-fg-muted">
                        {s.live.map((p) => (
                          <li key={p}>{p}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <p className="mt-auto text-xs text-fg-muted">
                    In the repository: connector <code className="font-mono">{s.repo}</code>
                  </p>
                </Card>
              </li>
            ))}
          </ul>
          <p className="mt-6 max-w-3xl text-base text-fg-muted">
            The two systems are linked by supplier IDs, so a question can follow a part from a
            change request to its supplier to a late shipment.
          </p>
        </div>
      </section>

      <section aria-labelledby="questions-title" className="px-4 py-16 sm:px-8">
        <div className="mx-auto max-w-6xl">
          <SectionTitle
            id="questions-title"
            eyebrow="Questions"
            title="What you can ask now"
            text="Each of these needs knowledge from more than one place. Documents alone can't tell you whether a shipment is late today."
          />
          <ul className="grid gap-4 md:grid-cols-2">
            {QUESTIONS.map((x) => (
              <li key={x.q} className="min-w-0">
                <Card className="flex h-full flex-col gap-2 p-5">
                  <p className="text-lg font-medium">“{x.q}”</p>
                  <p className="flex flex-wrap items-center gap-2 text-sm text-fg-muted">
                    {x.live ? <Badge tone="info">Live</Badge> : <Badge>Synced</Badge>}
                    {x.from}
                  </p>
                </Card>
              </li>
            ))}
          </ul>
          <div className="mt-8 flex flex-wrap gap-4 text-sm">
            <span className="text-fg-muted">
              Try them yourself with <code className="font-mono text-fg">task showcase:up</code>:
            </span>
            <a href={repoPath("docs/user-manual/connectors.md")} className="text-accent underline">
              Try the showcase in the user manual
            </a>
            <a href={repoPath("examples/showcase/README.md")} className="text-accent underline">
              Showcase source
            </a>
          </div>
        </div>
      </section>

      <section aria-labelledby="build-title" className="px-4 py-16 sm:px-8">
        <div className="mx-auto grid max-w-6xl gap-10 lg:grid-cols-2 lg:items-center">
          <div>
            <SectionTitle
              id="build-title"
              eyebrow="Build your own"
              title="A connector in a few lines"
              text="Scaffold one with a single command, implement search to query live and list_changes to sync, and a contract test checks your connector."
            />
            <div className="flex flex-wrap gap-3">
              <a
                href={repoPath("docs/connectors.md")}
                className={buttonClass("primary", "px-6 py-3 text-base")}
              >
                Read the connector SDK guide
                <ArrowRight className="size-4" aria-hidden="true" />
              </a>
              <a href={BASE} className={buttonClass("secondary", "px-6 py-3 text-base")}>
                Back to the overview
              </a>
            </div>
          </div>
          <figure className="glass min-w-0 rounded-panel p-4 sm:p-6">
            <figcaption className="mb-3 flex items-center gap-2 font-mono text-xs text-fg-muted">
              <FlaskConical className="size-3.5" aria-hidden="true" />
              Sketch of a connector
            </figcaption>
            <pre className="overflow-x-auto font-mono text-sm leading-relaxed">
              <code>{`$ task connector:new -- wiki

class WikiConnector(Connector[WikiConfig]):
    config_model = WikiConfig

    async def search(self, query, limit):
        ...  # answer at question time: live data

    async def list_changes(self, since):
        async for page in self.pages(since):
            yield Record(external_id=page.id, ...)`}</code>
            </pre>
          </figure>
        </div>
      </section>
    </Page>
  );
}

/** A row of steps joined by arrows: a column on small screens. */
function Flow({ steps }: { steps: string[] }) {
  return (
    <ol
      aria-label="Flow"
      className="flex flex-col items-center gap-1.5 font-mono text-xs sm:flex-row sm:flex-wrap"
    >
      {steps.map((s, i) => (
        <li key={s} className="flex items-center gap-1.5 sm:contents">
          {i > 0 && <ArrowDown className="size-3.5 text-fg-muted sm:hidden" aria-hidden="true" />}
          {i > 0 && (
            <ArrowRight className="hidden size-3.5 text-fg-muted sm:block" aria-hidden="true" />
          )}
          <span className="rounded-control border border-border bg-surface px-2.5 py-1">{s}</span>
        </li>
      ))}
    </ol>
  );
}
