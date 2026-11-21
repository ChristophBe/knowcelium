import RatingButtons from "./RatingButtons.tsx";
import RatingSummary from "./RatingSummary.tsx";

/** The rating of a document in the toolbar of its page: the thumbs, and how it was rated. */
export default function RateAction({ documentId }: { documentId: string }) {
  return (
    <fieldset className="m-0 inline-flex min-w-0 items-center gap-2 border-0 p-0">
      <legend className="sr-only">Rate this document</legend>
      <RatingButtons documentId={documentId} />
      <span className="text-xs text-fg-muted empty:hidden">
        <RatingSummary documentId={documentId} />
      </span>
    </fieldset>
  );
}
