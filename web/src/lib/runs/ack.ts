import { api, unwrap } from "@/lib/api/client";

/**
 * Tell the server these completions have been shown to the user, so a later
 * reconnect does not announce them again.
 *
 * Never throws. The tracker also holds an in-session guard, so a failed ack
 * cannot double-announce within this session; the worst case is one repeat
 * after a reload. Losing a completion is the bug this whole path exists to
 * fix — showing one twice is a nuisance.
 */
/**
 * Matches `AckRunsIn.run_ids`' `max_length` in `api/schemas/runs.py`.
 *
 * Reconnecting after a long absence can recover more completions than that in
 * one batch. Sending them as a single request would 422 — and because the
 * failure is swallowed, nothing would ever be stamped, so the same oversized
 * batch would come back and fail again every window.
 */
const ACK_BATCH_LIMIT = 200;

export async function ackRuns(runIds: readonly string[]): Promise<void> {
  for (let start = 0; start < runIds.length; start += ACK_BATCH_LIMIT) {
    const chunk = runIds.slice(start, start + ACK_BATCH_LIMIT);
    try {
      await unwrap(api.POST("/api/runs/ack", { body: { runIds: chunk } }));
    } catch {
      // Intentionally swallowed — see above. Later chunks still go out; one
      // failed chunk should not cost the others their acknowledgement.
    }
  }
}
