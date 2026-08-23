# Run completion delivery — design

**Date:** 2026-08-22
**Status:** Approved, awaiting implementation plan

## Problem

A background run (tailoring is the reported case) finishes server-side, but the
client never learns about it: the progress bar freezes below 100%, no completion
toast appears, and the board keeps showing stale data until the page is
reloaded. Reproduced in both local dev and the Railway deployment, so the cause
is in our own code rather than any one network path.

The backend terminal write is correct. `progress_stats` forces `pct = 100` on
`state == "done"`, and `RunProgressReporter.done()` writes the record atomically
before waking SSE subscribers. The failure is entirely in delivery and recovery.

### Failure chain

```
SSE drops mid-run  ->  tracker reconnects once  ->  drops again  ->  tracked.delete()
                   ->  bar frozen at last percent (remove() only fires on terminal)
                   ->  onDone never fires  ->  no toast, no query invalidation
                   ->  board stale until a full page reload
```

### Defects

1. **The tracker gives up.** `tracker.ts` guards reconnection with
   `entry.reconnects < 1` — exactly one reconnect, ever. A run whose stream
   drops twice is abandoned with no terminal handling and no user-visible sign.

2. **A completed run leaves no recoverable trace.** `list_rehydratable` returns
   `ACTIVE_RUN_STATES` plus failed revisions. A run that succeeded while the
   client was disconnected is invisible to the UI permanently. There is no
   run-completion notification system: the `Notification` table
   (`services/notifications.py`) is Gmail-only — inbound email status proposals
   with `application_id` / `message_id` / `proposed_status` and an accept/dismiss
   flow. The only completion signal that exists is an ephemeral toast bound to a
   closure created at launch time.

3. **The toast waits on a refetch.** `use-launch-run.ts` awaits
   `Promise.all(invalidate.map(qc.invalidateQueries))` *before* calling
   `announceCompletion`. Meanwhile `sse.ts` removes the run from the store on a
   4-second timer, so a slow board query can make the bar vanish before it reads
   100% and push the toast past it.

4. **Stale notifier binding.** `manager.py` binds
   `notify=self.notifier(run_id).notify` — a reference to that object's bound
   method, captured when the reporter is constructed. When
   `_release_terminal_notifier` pops the notifier and a reconnecting client
   creates a fresh one via `setdefault`, the worker keeps waking the orphan. The
   reconnected stream silently degrades to the 500 ms poll fallback.

5. **Invalidation lives at the call site.** The query keys to invalidate are an
   argument to `launch()`. A run discovered any way other than its own launch
   closure therefore invalidates nothing.

## Non-goals

- No change to the SSE wire format or to what a run's `result` contains.
- No new database table and no change to `Notification`. Folding run completions
  into the Gmail-shaped bell is a possible later spec, not this one.
- Not designing around `uvicorn --reload` killing streams in dev. The design
  tolerates it as one instance of "the connection can drop at any time".

## Design

### 1. Backend: the completion record becomes durable and acknowledgeable

The durable store already exists and is simply not exposed. Every run's terminal
state is written to `data/runs/{run_id}.json` via `atomic_write_text` and
survives for 24 hours (`sweep(max_age_seconds=86_400)` on app startup). The
record already carries `kind`, `state`, `result`, `error`, `meta`, `user_id`,
and `updated_at` — everything a completion toast needs.

**One new field.** The run JSON record gains `announced_at: str | null`
(ISO-8601, matching `updated_at`), threaded through `parse_run_snapshot` →
`RunSnapshot.announced_at` → `RunOut.announcedAt`. Absent on existing records,
which read as `null`. No migration, no backfill.

**`list_rehydratable` widens by one clause.** In addition to active runs and
failed revisions, it returns terminal runs owned by the caller with
`announced_at is None` whose `updated_at` falls within
`Settings.run_announce_window_seconds` (default 3600). Runs older than the
window are neither returned nor announced — nobody wants a toast for a job that
finished yesterday — but they remain readable via `GET /runs/{id}` until the
sweep removes them.

**One new endpoint.** `POST /api/runs/ack` with `{"runIds": [...]}`. Idempotent,
ownership-checked per id through the existing `_owned_record` gate, silently
skipping ids that are unknown, already acked, or not terminal. Returns the count
stamped.

**Concurrency.** `_write` is called from worker threads and ack from a request
thread, and two browser tabs can ack the same run simultaneously. Ack performs a
read-modify-write **inside the manager's `_singleton_lock`**, re-reading the
record from disk within the lock rather than trusting a snapshot taken outside
it, and refuses to stamp a non-terminal run. It never writes a record it did not
just read, so it cannot turn a concurrent progress write into a lost update.

Keeping the acknowledgement in the same file as the thing acknowledged means one
atomic write and one sweep govern both; a side table would need its own cleanup
and could drift out of sync with `sweep()`.

### 2. Frontend: the live path stops being the only path

The structural problem is that run lifecycle logic lives in the transport layer.
`sse.ts` decides when to remove a run from the store; `tracker.ts` decides when
to give up. Any completion discovered by a route other than a live SSE message
therefore receives no terminal handling at all.

**`sse.ts` becomes a pure translator.** Wire JSON → `RunRecord`, hand it to the
tracker, close on terminal. It stops calling `useRunStore.remove`, stops owning
the 4-second removal timer, and stops knowing that `revise` failures are special.

**`tracker.ts` owns the run lifecycle.** A single `finish(entry, run)` path,
reached from every discovery route, performs: upsert the terminal record →
announce → ack → invalidate queries → schedule removal from the store after
4 s (the current interval, so the bar holds at 100% briefly before collapsing).
Whether the completion arrived over SSE or was found by a poll becomes
irrelevant downstream.

The one exception `sse.ts` currently encodes moves here intact: a **failed**
`revise` or `coverLetterRevise` run is never auto-removed, because its `meta`
carries the original instruction that the durable retry UI reads. That rule
belongs to the lifecycle, not the transport.

**A reconciliation poller is the safety net.** While any run is tracked, one
interval (default 15 s) issues `GET /api/runs` — a single request that already
returns the caller's active runs plus, after section 1, their unannounced
terminal ones. Any tracked run returned as terminal is finished. Any tracked run
**missing** from the payload gets one `GET /api/runs/{id}` to distinguish "acked
by another tab" from "swept"; either way it stops being tracked, or its entry
would live forever and its bar would never leave the screen. The interval stops
when nothing is tracked.

**A run the payload reports as already announced is restored, not announced.**
`list_rehydratable`'s failed-revision clause is independent of `announced_at` —
the retry UI needs a failed `revise` listed even after acknowledgement — so a
client that announced every terminal run in the payload would re-toast the same
failure on every page load until the 24 h sweep. The client reads `announcedAt`
and puts such runs on screen silently.

This makes a frozen bar structurally impossible: SSE becomes a latency
optimization rather than the thing correctness depends on. `useRehydrateRuns`
stops owning its own `/api/runs` fetch and instead triggers the poller's first
tick, leaving one owner of that endpoint.

**Reconnect becomes unbounded.** `reconnects < 1` is replaced by capped
exponential backoff with jitter — 1 s, 2 s, 4 s, 8 s, 16 s, 30 s ceiling —
resetting to 1 s on any received message, stopping only when the run is known
terminal or `trackRun` is torn down. Unbounded retry is safe precisely because
the poller bounds the cost of being wrong: worst case is one poll per 15 s and
one reconnect attempt per 30 s, per run.

A transport error also triggers an immediate reconciliation rather than waiting
out the interval — the most common reason a stream dies is that its run ended.
Reconciliations are **coalesced**: a backend restart errors every tracked
stream at once, and without coalescing N runs would each fire their own
identical `/api/runs` request and then race one another applying the result.
Concurrent callers share the one in-flight request.

**The toast fires before the refetch.** In `use-launch-run.ts`, announcement
moves ahead of `await Promise.all(invalidate.map(...))`. A completion notice
should not wait on a board query.

**Late-binding notifier.** `manager.py`'s `notify=self.notifier(run_id).notify`
becomes a closure that resolves the current notifier at call time, so a worker
cannot keep waking an orphaned `StreamNotifier` after
`_release_terminal_notifier` has popped it. (`_write` already resolves late and
is unaffected.)

### 3. Announcement, invalidation, and testing

**Completion side-effects move out of the launch closure.** The tracker gains a
set of **global terminal listeners** alongside its existing per-run callbacks.
One listener, registered once at the app root by a `useRunCompletionEffects()`
hook, owns announce → ack → invalidate. Per-run callbacks remain for
launch-specific behavior such as `removeSupersededArtifactFailures`, and
`useLaunchRun` stops announcing so nothing double-toasts. This keeps the
`QueryClient` inside React; the tracker is a module singleton and has no
business holding one.

**Invalidation becomes a property of the run kind.** A single
`kind → queryKeys` map in `lib/runs/invalidation.ts` is consulted by both the
launch path and the poller-discovered path, with `DEFAULT_INVALIDATE` as the
fallback. Without this, a run discovered on page load invalidates nothing and
the board stays stale even once we know the run finished.

**Announcement is capped.** When a single announce pass carries **3 or fewer**
completions, each gets its own toast. At **4 or more**, they collapse into one
summary toast (`"4 runs finished while you were away"`) and no individual toasts
are shown — not 3 toasts plus a summary of the remainder. All completions are
acked regardless; the cap limits noise, not bookkeeping. The `error` and
`cancelled` states announce through the existing `toast.error` / `toast.info`
branches.

The cap applies per announce pass, so it only ever engages on load or after a
long disconnect. A run completing on the live path is always announced
individually, since it arrives alone.

**Ack failure degrades safely.** The client holds an in-session `announced` set,
so a failed ack cannot produce a duplicate toast within the same session. A
reload after a failed ack re-announces once: showing a completion twice is a
nuisance, losing it is the bug being fixed.

## Testing

Backend (`.venv/Scripts/python.exe -m pytest`):

- `announced_at` absent on a legacy record parses as `null`
- ack stamps the record; ack is idempotent; ack refuses a non-terminal run; ack
  on another user's run is **skipped, not raised** — the Design section above
  already says unusable ids are skipped silently, and a bulk endpoint that 404s
  over one stale id would make the client re-announce the whole batch. (An
  earlier draft of this line said "404s through `_owned_record`", contradicting
  the design two sections up.) The test must run in **hosted** mode: single-tenant
  has no `UserContext`, so `current_context()` is `None` and no owner filtering
  applies there at all — the same contract `_owned_record` already has.
- `list_rehydratable` includes unannounced terminal runs inside the window,
  excludes acked ones, and excludes ones past it
- a threaded test that a concurrent ack and progress write lose neither, because
  the read-modify-write happens inside the lock
- regression: after `_release_terminal_notifier` drops a notifier, the
  reporter's next wake reaches the current one (fails against the current
  bound-method capture)

Frontend (`npm run test:run` in `web/`):

- `sse.ts` no longer touches `useRunStore.remove`
- unbounded reconnect with backoff; the delay resets on a received message
- the poller finding a terminal run causes `finish` to fire exactly once, even
  when SSE delivers the same terminal event
- a tracked run missing from `/api/runs` triggers exactly one disambiguating
  `GET /api/runs/{id}`
- 3 completions on load produce 3 toasts; 4 produce exactly one summary toast
  and no individual ones; ack is called with every id in both cases
- a failed `revise` run is announced but not auto-removed from the store
- the launch path does not double-toast now that announcement is global

End-to-end: start a tailor run, kill the SSE connection mid-flight (a backend
restart is the easy lever, and is the dev case), and confirm the bar still
reaches 100%, the toast appears, and the board refreshes without touching the
page.

## Settings added

| Setting | Default | Purpose |
| --- | --- | --- |
| `run_announce_window_seconds` | `3600` | How recently a terminal run must have finished to be announced on load |

## Deferred

- Folding run completions into the notifications bell as permanent records
  (approach B). Requires a migration and stretches a Gmail-shaped table over a
  second concept; revisit once we know completions should outlive the 24 h sweep.
- Taxonomy regroup latency (batch/parallel LLM work). Tracked separately; the
  bottleneck there is the serial reconcile chain in `classification.py` and the
  phase barriers around it, not a lack of fan-out.
