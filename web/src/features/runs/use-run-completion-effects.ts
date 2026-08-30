import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { ackRuns } from "@/lib/runs/ack";
import { announceCompletions } from "@/lib/runs/announce";
import { invalidationKeys } from "@/lib/runs/invalidation";
import { addTerminalListener } from "@/lib/runs/tracker";
import { RUN_COMPLETIONS_KEY } from "@/features/notifications/use-run-completions";

/**
 * The one place a finished run turns into user-visible effects.
 *
 * Mount once, at the app root. It lives in React rather than in the tracker
 * because it needs the QueryClient, and the tracker is a module singleton with
 * no business holding one — that inversion is what lets a completion found by
 * the poller, on page load, or over SSE all land here identically.
 *
 * Announcement runs before invalidation: a completion notice should never wait
 * on a board refetch, which is exactly what used to delay it past the moment
 * the progress bar disappeared.
 */
export function useRunCompletionEffects(): void {
  const queryClient = useQueryClient();
  useEffect(
    () =>
      addTerminalListener((runs) => {
        announceCompletions(runs);
        void ackRuns(runs.map((run) => run.runId));
        const keys = new Set(
          runs.flatMap((run) => invalidationKeys(run.runId, run.kind)),
        );
        for (const key of keys) {
          void queryClient.invalidateQueries({ queryKey: [key] });
        }
        void queryClient.invalidateQueries({ queryKey: RUN_COMPLETIONS_KEY });
      }),
    [queryClient],
  );
}
