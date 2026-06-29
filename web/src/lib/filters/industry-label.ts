/** Format an extracted industry value without reinterpreting its meaning. */
export function industryLabel(value: string): string {
  return value.replace(/_/g, " ");
}
