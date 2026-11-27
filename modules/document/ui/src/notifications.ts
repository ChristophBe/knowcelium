import {
  type Document,
  DocumentStatus,
} from "@knowcel/document-api/knowcel/document/v1/document_pb";
import { defineNotifications } from "@knowcel/module-sdk";
import { useEffect, useRef } from "react";
import { inProgress } from "./VersionInfo.tsx";

export const notifications = defineNotifications([{ id: "documents", label: "Documents" }]);

const LIST_LINK = "/m/document";
const documentLink = (id: string) => `${LIST_LINK}/${encodeURIComponent(id)}`;

const failed = (d: Document) =>
  d.status === DocumentStatus.FAILED || d.pendingVersion?.status === DocumentStatus.FAILED;

/**
 * Follows the documents of a page across its status polling and tells the user
 * once what was reprocessing is done. Only documents the user saw being
 * processed again are watched: those seen ready before, or that already had
 * passages, versions or a new version when first seen in flight. A first upload is announced
 * by the upload page, not here.
 */
export class ReprocessingWatch {
  private seenReady = new Set<string>();
  private watched = new Set<string>();
  /** Finished ones wait here until the last watched document is done, to send one summary. */
  private finished = new Map<string, { title: string; failed: boolean }>();

  /** Takes the latest documents; sends notifications when everything watched has finished. */
  update(docs: readonly Document[]) {
    const present = new Set<string>();
    for (const d of docs) {
      present.add(d.id);
      if (inProgress(d)) {
        if (this.seenReady.has(d.id) || d.chunkCount > 0 || d.version > 1 || d.pendingVersion) {
          this.watched.add(d.id);
          this.finished.delete(d.id);
        }
      } else {
        if (this.watched.delete(d.id)) {
          this.finished.set(d.id, { title: d.title, failed: failed(d) });
        }
        if (d.status === DocumentStatus.READY) this.seenReady.add(d.id);
      }
    }
    // Deleted documents never finish.
    for (const id of this.watched) if (!present.has(id)) this.watched.delete(id);
    for (const id of this.finished.keys()) if (!present.has(id)) this.finished.delete(id);
    if (this.watched.size === 0 && this.finished.size > 0) this.flush();
  }

  private flush() {
    const ready: [string, string][] = [];
    for (const [id, { title, failed: bad }] of this.finished) {
      if (bad) {
        notifications.notify({
          category: "documents",
          kind: "error",
          title: `Couldn't process ${title}`,
          link: documentLink(id),
          tag: `failed:${id}`,
        });
      } else {
        ready.push([id, title]);
      }
    }
    this.finished.clear();
    if (ready.length === 1) {
      const [id, title] = ready[0] as [string, string];
      notifications.notify({
        category: "documents",
        kind: "success",
        title: `${title} is ready`,
        link: documentLink(id),
      });
    } else if (ready.length > 1) {
      notifications.notify({
        category: "documents",
        kind: "success",
        title: `${ready.length} documents are ready`,
        link: LIST_LINK,
      });
    }
  }
}

/** Notifies when documents the user watched being reprocessed are ready again, or failed. */
export function useReprocessingNotifications(docs: readonly Document[] | undefined) {
  const watch = useRef<ReprocessingWatch>(null);
  useEffect(() => {
    if (!docs) return;
    watch.current ??= new ReprocessingWatch();
    watch.current.update(docs);
  }, [docs]);
}
