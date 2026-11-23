import {
  type Connector,
  ConnectorHealth,
  IngestionService,
} from "@knowcel/ingestion-api/knowcel/ingestion/v1/ingestion_pb";
import {
  Code,
  ConnectError,
  useClient,
  useCurrentUserStatus,
  useIsPlatformAdmin,
  useQuery,
} from "@knowcel/module-sdk";
import {
  Badge,
  Button,
  brandText,
  Card,
  CheckCircle2,
  CircleAlert,
  CircleHelp,
  Clock,
  DelayedLoading,
  EmptyState,
  ErrorMessage,
  type IconComponent,
  PageHeader,
  Plug,
  RelativeTime,
  ShieldAlert,
  SkeletonRows,
  type Tone,
  TriangleAlert,
  useDocumentTitle,
} from "@knowcel/ui";
import { Link } from "react-router";

/** How often the list refreshes: the worker reports a sync at most every few seconds, usually minutes. */
export const REFRESH_MS = 30_000;

/** The guide for people who write a connector, where the empty state sends them. */
const GUIDE_URL = "https://github.com/ChristophBe/knowcelium/blob/main/docs/connectors.md";

/** Where the manual says what to do about an unhealthy connector. */
const FIX_HREF = "/help/ingestion#fix-an-unhealthy-connector";

const health: Record<ConnectorHealth, { label: string; tone: Tone; icon: IconComponent }> = {
  [ConnectorHealth.HEALTHY]: { label: "Healthy", tone: "success", icon: CheckCircle2 },
  [ConnectorHealth.DEGRADED]: { label: "Degraded", tone: "warning", icon: TriangleAlert },
  [ConnectorHealth.FAILING]: { label: "Failing", tone: "danger", icon: CircleAlert },
  [ConnectorHealth.STALE]: { label: "Stale", tone: "warning", icon: Clock },
  [ConnectorHealth.UNKNOWN]: { label: "Not synced yet", tone: "neutral", icon: CircleHelp },
  [ConnectorHealth.UNSPECIFIED]: { label: "Not synced yet", tone: "neutral", icon: CircleHelp },
};

/** A connector's health as an icon and a word, never colour alone. */
export function HealthBadge({ value }: { value: ConnectorHealth }) {
  const { label, tone, icon: Icon } = health[value] ?? health[ConnectorHealth.UNKNOWN];
  return (
    <Badge tone={tone}>
      <span className="inline-flex items-center gap-1">
        <Icon className="size-3.5" aria-hidden="true" />
        {label}
      </span>
    </Badge>
  );
}

const number = new Intl.NumberFormat();

/** What a failed request means for the user, in the words the page shows. */
function connectorsError(err: unknown): Error | null {
  if (!err) return null;
  const error = ConnectError.from(err);
  if (error.code === Code.Unavailable) {
    return new Error("Connectors are not available right now. Try again in a moment.");
  }
  if (error.code === Code.PermissionDenied) {
    return new Error("Only platform admins can see the connectors.");
  }
  return new Error(error.rawMessage);
}

/**
 * The connectors and whether they keep their documents up to date. Only
 * platform admins see it; the service refuses everyone else as well.
 */
export function Connectors() {
  useDocumentTitle("Connectors");
  const isAdmin = useIsPlatformAdmin();
  const status = useCurrentUserStatus();
  return (
    <div>
      <PageHeader
        eyebrow={brandText("knowcelium / connectors")}
        title="Connectors"
        description={brandText(
          "The external systems whose content Knowcelium keeps in sync, and whether each one is working.",
        )}
      />
      {status === "loading" ? (
        <Card>
          <DelayedLoading>
            <SkeletonRows label="Loading your account" />
          </DelayedLoading>
        </Card>
      ) : isAdmin ? (
        <ConnectorList />
      ) : status === "failed" ? (
        <Card>
          <EmptyState icon={CircleAlert}>
            Your account could not be loaded, so some pages, such as the connectors, are
            unavailable. Reload the page to try again.
          </EmptyState>
        </Card>
      ) : (
        <Card>
          <EmptyState icon={ShieldAlert}>Only platform admins can see the connectors.</EmptyState>
        </Card>
      )}
    </div>
  );
}

function ConnectorList() {
  const client = useClient(IngestionService);
  const connectors = useQuery({
    queryKey: ["connectors"],
    queryFn: () => client.listConnectors({}),
    refetchInterval: REFRESH_MS,
  });

  if (connectors.isPending) {
    return (
      <Card>
        <DelayedLoading>
          <SkeletonRows label="Loading connectors" />
        </DelayedLoading>
      </Card>
    );
  }
  if (connectors.error && !connectors.data) {
    return (
      <div className="flex flex-col items-start gap-3">
        <ErrorMessage error={connectorsError(connectors.error)} />
        <Button variant="secondary" onClick={() => connectors.refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  const rows = connectors.data?.connectors ?? [];
  if (rows.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={Plug}
          action={
            <a
              href={GUIDE_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm font-medium text-accent underline"
            >
              Read the connector guide (opens in a new tab)
            </a>
          }
        >
          No connectors yet. A connector keeps documents in step with an external system, such as a
          wiki or a drive, and its health shows here once your administrator has set one up.
        </EmptyState>
      </Card>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {/* A refresh that fails keeps the last list on screen. */}
      <ErrorMessage error={connectorsError(connectors.error)} />
      <Card className="overflow-x-auto">
        <table aria-label="Connectors" className="w-full min-w-160 text-sm">
          <thead className="border-b border-border text-left text-xs text-fg-muted uppercase">
            <tr>
              <th scope="col" className="px-4 py-2 font-medium">
                Connector
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                Health
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                Last successful sync
              </th>
              <th scope="col" className="px-4 py-2 text-right font-medium">
                Documents
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                Last error
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <ConnectorRow key={c.id} connector={c} />
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function ConnectorRow({ connector: c }: { connector: Connector }) {
  const name = c.name || c.id;
  const healthy = c.health === ConnectorHealth.HEALTHY;
  return (
    <tr className="border-b border-border align-top last:border-0">
      <th scope="row" className="px-4 py-2 text-left font-medium">
        {name}
        <span className="block text-xs font-normal text-fg-muted">
          {c.kind ? <span className="font-mono">{c.kind}</span> : "Invalid settings"}
          {!c.enabled && " · Disabled"}
        </span>
      </th>
      <td className="px-4 py-2">
        <div className="flex flex-col items-start gap-1">
          <HealthBadge value={c.health} />
          {!healthy && (
            <Link
              to={FIX_HREF}
              aria-label={`What to do about ${name}`}
              className="text-xs underline"
            >
              What to do
            </Link>
          )}
        </div>
      </td>
      <td className="px-4 py-2 whitespace-nowrap">
        {c.lastSuccessTime ? <RelativeTime time={c.lastSuccessTime} /> : "Never"}
      </td>
      <td className="px-4 py-2 text-right tabular-nums">{number.format(c.documentsSynced)}</td>
      <td className="max-w-sm px-4 py-2 wrap-anywhere text-fg-muted">{c.lastError || "None"}</td>
    </tr>
  );
}
