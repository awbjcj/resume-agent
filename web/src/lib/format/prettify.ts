// Legacy JD rows are flat text (HTML structure was stripped at ingest before the
// markdown change); newer rows are already markdown. Both render via react-markdown
// with remark-breaks (single newlines -> <br>, preserving legacy line layout). This
// pass only normalizes leading bullet glyphs to "- " for consistency; it is
// idempotent and leaves headings, numbered lists, bold, and existing "- " untouched.
const BULLET_GLYPH = /^(\s*)[•·▪◦●○*–-]\s+/;

export function prettifyPlainText(text: string): string {
  if (!text) return "";
  return text
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => line.replace(BULLET_GLYPH, "$1- "))
    .join("\n");
}
