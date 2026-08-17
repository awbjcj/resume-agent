export type SkillCategory = "unspecified" | "hard" | "soft" | "domain";

export const SKILL_CATEGORY_LABELS: Record<SkillCategory, string> = {
  unspecified: "Not sure",
  hard: "Hard skill",
  soft: "Soft skill",
  domain: "Domain",
};

export const SKILL_CATEGORY_OPTIONS = (
  Object.keys(SKILL_CATEGORY_LABELS) as SkillCategory[]
).map((value) => ({ value, label: SKILL_CATEGORY_LABELS[value] }));
