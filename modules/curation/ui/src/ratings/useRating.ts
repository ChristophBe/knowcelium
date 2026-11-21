import { CurationService, Rating } from "@knowcel/curation-api/knowcel/curation/v1/curation_pb";
import { toast, useClient, useMutation, useQuery, useQueryClient } from "@knowcel/module-sdk";

/**
 * How users rated a document, and the signed-in user's own rating of the
 * document, or of one passage when `chunkIndex` is given. The counts are the
 * whole document's whichever passage is asked about.
 */
export function useRatingSummary(documentId: string, chunkIndex?: number) {
  const client = useClient(CurationService);
  return useQuery({
    queryKey: ["ratings", documentId, chunkIndex ?? "document"],
    queryFn: () => client.getRatingSummary({ documentId, chunkIndex }),
    retry: false,
  });
}

const CONFIRMATION: Partial<Record<Rating, string>> = {
  [Rating.HELPFUL]: "Marked as helpful",
  [Rating.NOT_HELPFUL]: "Marked as not helpful",
  [Rating.NONE]: "Rating taken back",
};

/** Saves, changes or takes back the user's rating, and says so in a notification. */
export function useRate(documentId: string, chunkIndex?: number, conversationId?: string) {
  const client = useClient(CurationService);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (rating: Rating) =>
      client.rateDocument({ documentId, chunkIndex, rating, conversationId: conversationId ?? "" }),
    onSuccess: async (_, rating) => {
      toast.success(CONFIRMATION[rating] ?? "Rating saved");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ratings", documentId] }),
        // A rating changes the document's score.
        queryClient.invalidateQueries({ queryKey: ["finding-scores"] }),
      ]);
    },
    onError: () => toast.error("Couldn't save your rating. Try again in a moment."),
  });
}
