import { Code, ConnectError, createRouterTransport } from "@connectrpc/connect";
import { CurationService, Rating } from "@knowcel/curation-api/knowcel/curation/v1/curation_pb";
import { toast } from "@knowcel/module-sdk";
import { renderWithRuntime } from "@knowcel/module-sdk/testing";
import { expectNoAxeViolations } from "@knowcel/ui/testing";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RateAction from "./RateAction.tsx";
import RatingButtons from "./RatingButtons.tsx";
import RatingSummary from "./RatingSummary.tsx";

/** A service that remembers the user's ratings, per document or passage, and counts them. */
function server(initial: Record<string, Rating> = {}, others = { helpful: 0, notHelpful: 0 }) {
  const mine = new Map(Object.entries(initial));
  const key = (chunk?: number) => (chunk === undefined ? "document" : String(chunk));
  const rateDocument = vi.fn((request: { chunkIndex?: number; rating: Rating }) => {
    if (request.rating === Rating.NONE) mine.delete(key(request.chunkIndex));
    else mine.set(key(request.chunkIndex), request.rating);
    return {};
  });
  const getRatingSummary = vi.fn((request: { chunkIndex?: number }) => {
    const own = [...mine.values()];
    return {
      helpful: others.helpful + own.filter((r) => r === Rating.HELPFUL).length,
      notHelpful: others.notHelpful + own.filter((r) => r === Rating.NOT_HELPFUL).length,
      myRating: mine.get(key(request.chunkIndex)) ?? Rating.NONE,
    };
  });
  const transport = createRouterTransport(({ service }) =>
    service(CurationService, { rateDocument, getRatingSummary }),
  );
  return { transport, rateDocument, getRatingSummary };
}

afterEach(() => vi.restoreAllMocks());

const helpful = (name: string) => screen.findByRole("button", { name });

describe("RatingButtons", () => {
  it("offers thumbs named after the passage and its document, with the user's rating pressed", async () => {
    const { transport } = server({ "2": Rating.NOT_HELPFUL });
    const { container } = renderWithRuntime(
      <RatingButtons documentId="d1" documentTitle="Aurora" chunkIndex={2} />,
      transport,
    );
    const up = await helpful("Mark passage 3 of Aurora as helpful");
    const down = screen.getByRole("button", { name: "Mark passage 3 of Aurora as not helpful" });
    expect(up.getAttribute("aria-pressed")).toBe("false");
    expect(down.getAttribute("aria-pressed")).toBe("true");
    // Big enough to hit, also for a finger.
    expect(up.className).toContain("size-7");
    expect(up.className).toContain("pointer-coarse:size-11");
    await expectNoAxeViolations(container);
  });

  it("rates a passage, with the conversation, and says so without moving the focus", async () => {
    const { transport, rateDocument } = server();
    const success = vi.spyOn(toast, "success");
    renderWithRuntime(
      <RatingButtons documentId="d1" documentTitle="Aurora" chunkIndex={0} conversationId="c1" />,
      transport,
    );
    const up = await helpful("Mark passage 1 of Aurora as helpful");
    up.focus();
    fireEvent.click(up);
    await waitFor(() => expect(rateDocument).toHaveBeenCalledTimes(1));
    expect(rateDocument.mock.calls[0]?.[0]).toMatchObject({
      documentId: "d1",
      chunkIndex: 0,
      rating: Rating.HELPFUL,
      conversationId: "c1",
    });
    await waitFor(() => expect(up.getAttribute("aria-pressed")).toBe("true"));
    expect(success).toHaveBeenCalledWith("Marked as helpful");
    expect(document.activeElement).toBe(up);
  });

  it("takes a rating back with one click on the pressed thumb, and changes it with the other", async () => {
    const { transport, rateDocument } = server({ document: Rating.HELPFUL });
    renderWithRuntime(<RatingButtons documentId="d1" />, transport);
    const up = await helpful("Mark this document as helpful");
    const down = screen.getByRole("button", { name: "Mark this document as not helpful" });
    expect(up.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(down);
    await waitFor(() => expect(down.getAttribute("aria-pressed")).toBe("true"));
    expect(up.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(down);
    await waitFor(() => expect(down.getAttribute("aria-pressed")).toBe("false"));
    expect(rateDocument.mock.calls.map((c) => c[0].rating)).toEqual([
      Rating.NOT_HELPFUL,
      Rating.NONE,
    ]);
  });

  it("doesn't rate twice while a rating is being saved", async () => {
    let finish: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      finish = resolve;
    });
    const rateDocument = vi.fn(async () => {
      await gate;
      return {};
    });
    const transport = createRouterTransport(({ service }) =>
      service(CurationService, {
        rateDocument,
        getRatingSummary: () => ({ helpful: 0, notHelpful: 0, myRating: Rating.NONE }),
      }),
    );
    renderWithRuntime(<RatingButtons documentId="d1" />, transport);
    const up = await helpful("Mark this document as helpful");
    fireEvent.click(up);
    fireEvent.click(up);
    // Neither disabled, which would drop the focus, nor sent twice.
    expect((up as HTMLButtonElement).disabled).toBe(false);
    await waitFor(() => expect(rateDocument).toHaveBeenCalledTimes(1));
    finish();
  });

  it("says so when the rating can't be saved, and keeps the thumbs as they were", async () => {
    const error = vi.spyOn(toast, "error");
    const transport = createRouterTransport(({ service }) =>
      service(CurationService, {
        rateDocument: () => {
          throw new ConnectError("down", Code.Unavailable);
        },
        getRatingSummary: () => ({ helpful: 0, notHelpful: 0, myRating: Rating.NONE }),
      }),
    );
    renderWithRuntime(<RatingButtons documentId="d1" />, transport);
    const up = await helpful("Mark this document as helpful");
    fireEvent.click(up);
    await waitFor(() =>
      expect(error).toHaveBeenCalledWith("Couldn't save your rating. Try again in a moment."),
    );
    expect(up.getAttribute("aria-pressed")).toBe("false");
  });

  it("takes no room while the rating can't be loaded", async () => {
    const transport = createRouterTransport(({ service }) =>
      service(CurationService, {
        getRatingSummary: () => {
          throw new ConnectError("down", Code.Unavailable);
        },
      }),
    );
    const { container } = renderWithRuntime(<RatingButtons documentId="d1" />, transport);
    await waitFor(() => expect(container.textContent).toBe(""));
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("RatingSummary", () => {
  it("says how many users found the document helpful", async () => {
    const { transport } = server({}, { helpful: 3, notHelpful: 1 });
    renderWithRuntime(<RatingSummary documentId="d1" />, transport);
    expect(await screen.findByText("3 found it helpful, 1 not")).toBeTruthy();
  });

  it("shows nothing for a document nobody rated", async () => {
    const { transport, getRatingSummary } = server();
    const { container } = renderWithRuntime(<RatingSummary documentId="d1" />, transport);
    await waitFor(() => expect(getRatingSummary).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });
});

describe("RateAction", () => {
  it("groups the thumbs of a document with how it was rated", async () => {
    const { transport } = server({ document: Rating.HELPFUL }, { helpful: 2, notHelpful: 1 });
    const { container } = renderWithRuntime(<RateAction documentId="d1" />, transport);
    expect(await screen.findByRole("group", { name: "Rate this document" })).toBeTruthy();
    expect(await screen.findByText("3 found it helpful, 1 not")).toBeTruthy();
    expect(
      screen
        .getByRole("button", { name: "Mark this document as helpful" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    await expectNoAxeViolations(container);
  });
});
