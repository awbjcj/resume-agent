// Legacy JD rows are flat text (HTML structure was stripped at ingest before the
// markdown change); newer rows are already markdown. Both render via react-markdown
// with remark-breaks (single newlines -> <br>, preserving legacy line layout). This
// pass only normalizes leading bullet glyphs to "- " for consistency; it is
// idempotent and leaves headings, numbered lists, bold, and existing "- " untouched.
const BULLET_GLYPH = /^(\s*)[•·▪◦●○*–-]\s+/;
const MATERIAL_ICON_TOKENS = new Set([
  "business_center",
  "corporate_fare",
  "event",
  "laptop_windows",
  "location_on",
  "payments",
  "place",
  "schedule",
  "school",
  "work",
]);
const ESCAPED_ICON_TOKEN = /(^|\s)\\_([a-z][a-z0-9]*(?:\\_[a-z0-9]+)*)\\_(?=\s|$|[,.])/g;
const PLAIN_ICON_TOKEN = /(^|\s)_([a-z][a-z0-9]*(?:_[a-z0-9]+)*)_(?=\s|$|[,.])/g;
const ESCAPED_STRONG = /\\\*\\\*([^*\n]+?)\\\*\\\*/g;

function dropIconToken(match: string, prefix: string, rawToken: string) {
  const token = rawToken.replaceAll("\\_", "_").toLowerCase();
  return MATERIAL_ICON_TOKENS.has(token) ? prefix : match;
}

export function cleanJobDescriptionText(text: string): string {
  if (!text) return "";
  return text
    .replace(ESCAPED_ICON_TOKEN, dropIconToken)
    .replace(PLAIN_ICON_TOKEN, dropIconToken)
    .replace(ESCAPED_STRONG, "$1")
    .replace(/[ \t]+([,.;:])/g, "$1")
    .split("\n")
    .map((line) => line.replace(/[ \t]{2,}/g, " ").trim())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function prettifyPlainText(text: string): string {
  if (!text) return "";
  return cleanJobDescriptionText(text)
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => line.replace(BULLET_GLYPH, "$1- "))
    .join("\n");
}
