import { useRatingSummary } from "./useRating.ts";

/** How many users found a document helpful or not; nothing while it has no ratings or they can't be loaded. */
export default function RatingSummary({ documentId }: { documentId: string }) {
  const summary = useRatingSummary(documentId);
  const { helpful = 0, notHelpful = 0 } = summary.data ?? {};
  if (helpful + notHelpful === 0) return null;
  return (
    <span>
      {helpful} found it helpful, {notHelpful} not
    </span>
  );
}
