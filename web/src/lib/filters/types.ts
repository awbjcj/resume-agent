import type { components } from "@/lib/api/schema";

export type ShortlistItem = components["schemas"]["ShortlistItem"];
export type SkillTag = components["schemas"]["SkillTagOut"];

export type SortKey = "fit" | "salary" | "recency" | "composite" | "company" | "stage";
export type Preset = "balanced" | "pay_first" | "freshest";

export interface FilterState {
  q: string;
  salaryMin: number | null;
  source: Set<string>;
  status: Set<string>;
  remote: Set<string>;
  sponsorship: Set<string>;
  seniority: Set<string>;
  employmentType: Set<string>;
  industry: Set<string>;
  country: Set<string>;
  region: Set<string>;
  city: Set<string>;
  companySize: Set<string>;
  fitMin: number | null;
  maxFit: number | null;
  staleDays: number | null;
  staleMinDays: number | null;
  skills: Set<string>;
  sort: SortKey;
  preset: Preset;
}

export function emptyFilterState(): FilterState {
  return {
    q: "",
    salaryMin: null,
    source: new Set(),
    status: new Set(),
    remote: new Set(),
    sponsorship: new Set(),
    seniority: new Set(),
    employmentType: new Set(),
    industry: new Set(),
    country: new Set(),
    region: new Set(),
    city: new Set(),
    companySize: new Set(),
    fitMin: null,
    maxFit: null,
    staleDays: null,
    staleMinDays: null,
    skills: new Set(),
    sort: "fit",
    preset: "balanced",
  };
}
