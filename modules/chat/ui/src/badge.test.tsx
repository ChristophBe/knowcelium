import { create } from "@bufbuild/protobuf";
import {
  ConversationSchema,
  ListConversationsResponseSchema,
} from "@knowcel/chat-api/knowcel/chat/v1/chat_pb";
import { clearNotifications, KbRuntimeProvider, useNotifications } from "@knowcel/module-sdk";
import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useUnseenAnswers } from "./badge.ts";
import "./notify.ts";

const listConversations = vi.fn();

vi.mock("@knowcel/module-sdk", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@knowcel/module-sdk")>()),
  useClient: () => ({ listConversations }),
}));

function respond(...conversations: Parameters<typeof create<typeof ConversationSchema>>[1][]) {
  listConversations.mockResolvedValue(
    create(ListConversationsResponseSchema, {
      conversations: conversations.map((c) => create(ConversationSchema, c)),
    }),
  );
}

function Badge() {
  const entries = useNotifications();
  return (
    <>
      <p>unseen: {useUnseenAnswers()}</p>
      <p>entries: {entries.map((e) => `${e.category}|${e.body}|${e.link}`).join(",")}</p>
    </>
  );
}

function renderBadge() {
  return render(
    <KbRuntimeProvider config={{ apiBaseUrl: "http://test" }}>
      <MemoryRouter>
        <Badge />
      </MemoryRouter>
    </KbRuntimeProvider>,
  );
}

describe("useUnseenAnswers", () => {
  beforeEach(() => {
    listConversations.mockReset();
    clearNotifications();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("counts the conversations whose answer finished while away", async () => {
    respond({ id: "a", completedUnseen: true }, { id: "b" }, { id: "c", completedUnseen: true });
    renderBadge();
    expect(await screen.findByText("unseen: 2")).toBeTruthy();
  });

  it("is 0 while nothing waits, and does not look again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    respond({ id: "a" });
    renderBadge();
    expect(await screen.findByText("unseen: 0")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(listConversations).toHaveBeenCalledOnce();
    vi.useRealTimers();
  });

  it("looks again while an answer is written and records a notification when it finishes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    respond({ id: "a", title: "Budget", generating: true });
    renderBadge();
    expect(await screen.findByText("unseen: 0")).toBeTruthy();

    respond({ id: "a", title: "Budget", completedUnseen: true });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(await screen.findByText("unseen: 1")).toBeTruthy();
    expect(screen.getByText("entries: answers|Budget|/m/chat/a")).toBeTruthy();
    vi.useRealTimers();
  });

  it("does not notify about what was already waiting when the app opened", async () => {
    respond({ id: "a", title: "Old", completedUnseen: true });
    renderBadge();
    expect(await screen.findByText("unseen: 1")).toBeTruthy();
    expect(screen.getByText("entries:")).toBeTruthy();
  });
});
