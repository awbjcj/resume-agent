# Session substrate developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_agent/sessions/`.

- **Mock interviews are practice artifacts, not progress.** `interview/store.py`
  keeps one durable session JSON per interview under `data/interview/`
  (turn-per-run, ADR 0006), with the JD + tailored-resume snapshot frozen at
  opening. The interviewer stays in character (no mid-session coaching); the
  debrief run scores only questions actually asked. No corpus writes — fact-lock
  untouched — and sessions never gate job deletion (`has_progress` unchanged);
  the job delete endpoint removes the job's session files. Voice input rides
  `llm_runner.transcribe` (`Settings.transcribe_model`, Gemini/OpenAI only,
  default `gemini:gemini-2.5-flash`) through `POST /api/transcribe`; audio is
  never persisted.
  The coach, interview, and Career Lab stores are all adapters of the Session
  substrate (`sessions/store.py`); custody bugs are fixed there, once — bulk
  removal is `SessionStore.delete_where(root, predicate)`, where only the
  predicate belongs to the kind (it owns the lock spanning scan-and-unlink, the
  archived-inclusive scan, and treating an already-gone file as success).
  **`list` skips an unreadable file with a warning; `load` stays strict.** A
  request for one session by id must say when it cannot be read, but `list`
  backs every active-session check and bulk delete, so failing the whole scan on
  one bad file took down far more than it protected: a job delete runs its
  cascade _after_ the row is committed, so a single corrupt file turned every
  later delete into a 500 for a job that had in fact been removed.
  `TurnRejected` and
  `format_with_retry` live in `sessions/turns.py`, shared by both stacks.
  `RunStreamSink` (`sessions/stream.py`) batches **text and reasoning alike** —
  each on its own budget, a kind change flushing the other — because every
  unbatched delta costs a file open/write/flush, an SSE frame, and a React
  re-render that re-parses the thread's markdown. A reasoning model streams
  thinking one word at a time, so bypassing the batch cost 1,846 rows on a
  single turn where 33 suffice.
- **Seeded coach topics carry an owner anchor.** `CoachTopic.owner_id` defaults
  to `""` so older session JSON remains readable. On approval a non-empty owner
  id becomes the synthesis-mode corpus anchor for the coach note; model-added
  topics retain the unanchored literal path.
