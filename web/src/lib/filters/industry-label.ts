/** Make persisted canonical separators readable without changing the vocabulary. */
export function industryLabel(value: string): string {
  return value.replaceAll("_", " ");
}
