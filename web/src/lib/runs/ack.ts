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
export async function ackRuns(runIds: readonly string[]): Promise<void> {
  if (runIds.length === 0) return;
  try {
    await unwrap(api.POST("/api/runs/ack", { body: { runIds: [...runIds] } }));
  } catch {
    // Intentionally swallowed — see above.
  }
}
