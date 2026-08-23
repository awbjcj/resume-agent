/**
 * Run kinds that revise one existing artifact, and the `meta` key naming it.
 *
 * Two places need this and had drifted into separate copies: the launch path
 * clears a superseded failed attempt for the same artifact, and the tracker
 * keeps a failed attempt on screen because its `meta` carries the instruction
 * the retry UI replays. The backend holds the same table as
 * `_REVISION_META_KEYS` in `api/runs/manager.py` — keep them in step.
 */
export const REVISION_META_KEYS: Readonly<Record<string, string>> = {
  revise: "versionId",
  coverLetterRevise: "coverLetterId",
};

/** The `meta` key naming the artifact this run revises, or null if it revises none. */
export function revisionMetaKey(kind: string): string | null {
  return REVISION_META_KEYS[kind] ?? null;
}

export function isRevisionKind(kind: string): boolean {
  return kind in REVISION_META_KEYS;
}
