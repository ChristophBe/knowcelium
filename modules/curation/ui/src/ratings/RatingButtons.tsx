import { Rating } from "@knowcel/curation-api/knowcel/curation/v1/curation_pb";
import { cn, IconButton, ThumbsDown, ThumbsUp } from "@knowcel/ui";
import { useRef } from "react";
import { useRate, useRatingSummary } from "./useRating.ts";

/**
 * Thumbs up and down to rate a document, or one passage of it, as helpful or
 * not. They are toggle buttons: the one that is pressed is the user's rating,
 * and pressing it again takes the rating back; the other one changes it. The
 * focus stays where it is while the rating is saved. They take no room while the
 * user's rating can't be loaded, as the page works without them.
 */
export default function RatingButtons({
  documentId,
  documentTitle,
  chunkIndex,
  conversationId,
}: {
  documentId: string;
  /** Names the source in the buttons' labels; without it the buttons are for "this document". */
  documentTitle?: string;
  /** The passage to rate, counted from 0; the document as a whole without it. */
  chunkIndex?: number;
  /** The conversation a source of an answer was rated in. */
  conversationId?: string;
}) {
  const summary = useRatingSummary(documentId, chunkIndex);
  const rate = useRate(documentId, chunkIndex, conversationId);
  // Set at once, where `rate.isPending` only follows after the next render.
  const saving = useRef(false);
  if (!summary.data) return null;
  const mine = summary.data.myRating;
  const what =
    chunkIndex === undefined
      ? "this document"
      : `passage ${chunkIndex + 1}${documentTitle ? ` of ${documentTitle}` : ""}`;

  const toggle = (rating: Rating) => {
    // Not `disabled` while saving: a disabled button loses the focus.
    if (saving.current) return;
    saving.current = true;
    rate.mutate(mine === rating ? Rating.NONE : rating, {
      onSettled: () => {
        saving.current = false;
      },
    });
  };
  const pressed = (on: boolean) => cn(on && "bg-accent-subtle text-accent hover:text-accent");

  return (
    <span className="inline-flex items-center gap-0.5">
      <IconButton
        label={`Mark ${what} as helpful`}
        aria-pressed={mine === Rating.HELPFUL}
        className={pressed(mine === Rating.HELPFUL)}
        onClick={() => toggle(Rating.HELPFUL)}
      >
        <ThumbsUp className="size-4" />
      </IconButton>
      <IconButton
        label={`Mark ${what} as not helpful`}
        aria-pressed={mine === Rating.NOT_HELPFUL}
        className={pressed(mine === Rating.NOT_HELPFUL)}
        onClick={() => toggle(Rating.NOT_HELPFUL)}
      >
        <ThumbsDown className="size-4" />
      </IconButton>
    </span>
  );
}
