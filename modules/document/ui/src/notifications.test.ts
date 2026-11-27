import { create } from "@bufbuild/protobuf";
import {
  DocumentSchema,
  DocumentStatus,
  PendingVersionSchema,
} from "@knowcel/document-api/knowcel/document/v1/document_pb";
import {
  clearNotifications,
  type NotificationEntry,
  onNotificationsChange,
} from "@knowcel/module-sdk";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import manifest from "./manifest.ts";
import { ReprocessingWatch } from "./notifications.ts";

const doc = (id: string, status: DocumentStatus, extra: Record<string, unknown> = {}) =>
  create(DocumentSchema, { id, title: `Doc ${id}`, status, ...extra });

describe("ReprocessingWatch", () => {
  let entries: readonly NotificationEntry[] = [];
  let stop = () => {};
  beforeEach(() => {
    entries = [];
    stop = onNotificationsChange((e) => {
      entries = e;
    });
  });
  afterEach(() => {
    stop();
    clearNotifications();
  });

  it("declares the Documents category", () => {
    expect(manifest.notifications).toEqual([{ id: "documents", label: "Documents" }]);
  });

  it("sends one summary when the last of several reprocessed documents is ready", () => {
    const watch = new ReprocessingWatch();
    watch.update([doc("a", DocumentStatus.READY), doc("b", DocumentStatus.READY)]);
    watch.update([doc("a", DocumentStatus.PROCESSING), doc("b", DocumentStatus.PROCESSING)]);
    watch.update([doc("a", DocumentStatus.READY), doc("b", DocumentStatus.PROCESSING)]);
    expect(entries).toHaveLength(0);
    watch.update([doc("a", DocumentStatus.READY), doc("b", DocumentStatus.READY)]);
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      category: "documents",
      title: "2 documents are ready",
      link: "/m/document",
      kind: "success",
    });
    watch.update([doc("a", DocumentStatus.READY), doc("b", DocumentStatus.READY)]);
    expect(entries).toHaveLength(1);
  });

  it("names a single document and links to it", () => {
    const watch = new ReprocessingWatch();
    watch.update([doc("a", DocumentStatus.READY)]);
    watch.update([doc("a", DocumentStatus.PROCESSING)]);
    watch.update([doc("a", DocumentStatus.READY)]);
    expect(entries.map((e) => [e.title, e.link])).toEqual([["Doc a is ready", "/m/document/a"]]);
  });

  it("watches a document already reprocessing when first seen, but not a first upload", () => {
    const watch = new ReprocessingWatch();
    watch.update([
      doc("old", DocumentStatus.PROCESSING, { chunkCount: 3 }),
      doc("new", DocumentStatus.PROCESSING),
    ]);
    watch.update([doc("old", DocumentStatus.READY), doc("new", DocumentStatus.READY)]);
    expect(entries.map((e) => e.title)).toEqual(["Doc old is ready"]);
  });

  it("watches a new version of a ready document", () => {
    const watch = new ReprocessingWatch();
    const pending = (status: DocumentStatus) => create(PendingVersionSchema, { status });
    watch.update([doc("a", DocumentStatus.READY)]);
    watch.update([
      doc("a", DocumentStatus.READY, { pendingVersion: pending(DocumentStatus.PROCESSING) }),
    ]);
    watch.update([doc("a", DocumentStatus.READY)]);
    expect(entries.map((e) => e.title)).toEqual(["Doc a is ready"]);
  });

  it("reports a failure as its own error entry next to the summary", () => {
    const watch = new ReprocessingWatch();
    watch.update([doc("a", DocumentStatus.READY), doc("b", DocumentStatus.READY)]);
    watch.update([doc("a", DocumentStatus.PROCESSING), doc("b", DocumentStatus.PROCESSING)]);
    watch.update([doc("a", DocumentStatus.FAILED), doc("b", DocumentStatus.READY)]);
    expect(entries.map((e) => [e.kind, e.title, e.link])).toEqual([
      ["error", "Couldn't process Doc a", "/m/document/a"],
      ["success", "Doc b is ready", "/m/document/b"],
    ]);
  });

  it("reports a failed new version", () => {
    const watch = new ReprocessingWatch();
    const pending = (status: DocumentStatus) => create(PendingVersionSchema, { status });
    watch.update([
      doc("a", DocumentStatus.READY, { pendingVersion: pending(DocumentStatus.PROCESSING) }),
    ]);
    watch.update([
      doc("a", DocumentStatus.READY, { pendingVersion: pending(DocumentStatus.FAILED) }),
    ]);
    expect(entries.map((e) => [e.kind, e.title])).toEqual([["error", "Couldn't process Doc a"]]);
  });

  it("says nothing about documents that were never reprocessing or that were deleted", () => {
    const watch = new ReprocessingWatch();
    watch.update([doc("a", DocumentStatus.READY), doc("b", DocumentStatus.READY)]);
    watch.update([doc("a", DocumentStatus.READY), doc("b", DocumentStatus.PROCESSING)]);
    watch.update([doc("a", DocumentStatus.READY)]);
    expect(entries).toHaveLength(0);
  });
});
