import { create } from "@bufbuild/protobuf";
import { Code, ConnectError } from "@connectrpc/connect";
import {
  ChatMessageSchema,
  CitationSchema,
  ConversationSchema,
} from "@knowcel/chat-api/knowcel/chat/v1/chat_pb";
import { KbRuntimeProvider, useToasts } from "@knowcel/module-sdk";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConversationHeader } from "./ConversationHeader.tsx";

const updateConversation = vi.fn();
const getPromptTemplates = vi.fn();

// The real runtime, except that the chat client is a fake.
vi.mock("@knowcel/module-sdk", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@knowcel/module-sdk")>()),
  useClient: () => ({ updateConversation, getPromptTemplates }),
}));

function Toasts() {
  return (
    <ul>
      {useToasts().map((t) => (
        <li key={t.id}>{t.message}</li>
      ))}
    </ul>
  );
}

function renderHeader(title = "Q3 revenue") {
  const conversation = create(ConversationSchema, { id: "c1", title });
  return render(
    <KbRuntimeProvider config={{ apiBaseUrl: "http://test" }}>
      <MemoryRouter>
        <ConversationHeader conversation={conversation} />
      </MemoryRouter>
      <Toasts />
    </KbRuntimeProvider>,
  );
}

function startRename() {
  fireEvent.click(screen.getByRole("button", { name: "Rename" }));
  return screen.getByRole("textbox", { name: "Conversation title" }) as HTMLInputElement;
}

describe("ConversationHeader", () => {
  beforeEach(() => {
    updateConversation.mockReset();
  });

  it("shows the title, or a placeholder without one", () => {
    renderHeader("");
    expect(screen.getByRole("heading", { name: "New conversation" })).toBeTruthy();
  });

  it("saves a new title with Enter and returns focus to Rename", async () => {
    updateConversation.mockResolvedValue({});
    renderHeader();
    const input = startRename();
    expect(input.value).toBe("Q3 revenue");

    fireEvent.change(input, { target: { value: "  Q4 plans " } });
    await act(async () => {
      fireEvent.submit(input.closest("form") as HTMLFormElement);
    });

    expect(updateConversation).toHaveBeenCalledWith({ id: "c1", title: "Q4 plans" });
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Rename" }));
    expect(screen.getByText("Conversation renamed")).toBeTruthy();
  });

  it("rejects an empty title without calling the server", () => {
    renderHeader();
    const input = startRename();
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    expect(updateConversation).not.toHaveBeenCalled();
    expect(screen.getByText("Title must not be empty")).toBeTruthy();
    expect(input.getAttribute("aria-invalid")).toBe("true");
  });

  it("shows the server's reason next to the field", async () => {
    updateConversation.mockRejectedValue(
      new ConnectError("title must not be longer than 200 characters", Code.InvalidArgument),
    );
    renderHeader();
    const input = startRename();
    fireEvent.change(input, { target: { value: "too long" } });
    await act(async () => {
      fireEvent.submit(input.closest("form") as HTMLFormElement);
    });

    expect(screen.getByText("title must not be longer than 200 characters")).toBeTruthy();
    expect(screen.getByRole("textbox")).toBeTruthy();
  });

  it("cancels with Escape", () => {
    renderHeader();
    fireEvent.keyDown(startRename(), { key: "Escape" });
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(updateConversation).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Rename" }));
  });

  describe("sources in this chat", () => {
    const answer = (id: string, ...connectors: string[]) =>
      create(ChatMessageSchema, {
        id,
        citations: connectors.map((connector) => create(CitationSchema, { connector })),
      });

    function renderWith(messages: ReturnType<typeof answer>[]) {
      return render(
        <KbRuntimeProvider config={{ apiBaseUrl: "http://test" }}>
          <MemoryRouter>
            <ConversationHeader
              conversation={create(ConversationSchema, { id: "c1", title: "T" })}
              messages={messages}
            />
          </MemoryRouter>
        </KbRuntimeProvider>,
      );
    }

    it("says so when no connector was used", () => {
      renderWith([answer("a1")]);
      fireEvent.click(screen.getByRole("button", { name: /Sources in this chat/ }));
      expect(screen.getByText("No connectors used yet")).toBeTruthy();
    });

    it("lists each connector once, with a link to the first answer that used it", () => {
      const target = document.createElement("div");
      target.id = "message-a2";
      document.body.append(target);
      renderWith([answer("a1"), answer("a2", "orders", "orders", "crm"), answer("a3", "orders")]);
      fireEvent.click(screen.getByRole("button", { name: /Sources in this chat/ }));
      const items = within(
        screen.getByRole("region", { name: "Sources in this chat" }),
      ).getAllByRole("listitem");
      expect(items.map((i) => i.textContent)).toEqual([
        "orders · 3 snippets, first used in this answer",
        "crm · 1 snippet, first used in this answer",
      ]);
      fireEvent.click(within(items[0] as HTMLElement).getByRole("button"));
      expect(document.activeElement).toBe(target);
      target.remove();
    });
  });
});
