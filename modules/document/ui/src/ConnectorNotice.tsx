import { Info } from "@knowcel/ui";

/** Metadata keys a connector sets on the documents it syncs. */
const CONNECTOR_KEY = "connector";
const SOURCE_URL_KEY = "source_url";

/** The connector that keeps a document in sync, if any. */
export function connectorOf(metadata: Record<string, string>): string | undefined {
  return metadata[CONNECTOR_KEY] || undefined;
}

/** Where the document lives in its source, when that is a web address. */
function sourceLink(metadata: Record<string, string>): string | undefined {
  const url = metadata[SOURCE_URL_KEY];
  return url && /^https?:\/\//i.test(url) ? url : undefined;
}

/** The "Source" row: which connector the document comes from. */
export function ConnectorSource({ metadata }: { metadata: Record<string, string> }) {
  const name = connectorOf(metadata);
  if (!name) return null;
  const link = sourceLink(metadata);
  return (
    <>
      Synced by connector “{name}”
      {link && (
        <>
          {" · "}
          <a href={link} className="underline" rel="noreferrer noopener">
            Open the original
          </a>
        </>
      )}
    </>
  );
}

/** Tells the owner that the next sync overwrites what they edit here. */
export function ConnectorNotice({ metadata }: { metadata: Record<string, string> }) {
  const name = connectorOf(metadata);
  if (!name) return null;
  return (
    <div
      role="note"
      className="mb-6 flex max-w-2xl items-start gap-3 rounded-control bg-info-subtle px-3 py-2 text-info text-sm"
    >
      <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <p>
        This document is kept in sync with the connector “{name}”. When the original changes, the
        next sync replaces the file, the title and the metadata, so changes you make here to those
        are lost. Sharing and access stay as you set them.
      </p>
    </div>
  );
}
