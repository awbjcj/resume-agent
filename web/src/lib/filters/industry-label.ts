import { fieldLabel } from "@/lib/format";

/** Make a persisted industry value readable, in the same title-cased style as
 * every other job-brief facet. */
export function industryLabel(value: string): string {
  return fieldLabel(value);
}
