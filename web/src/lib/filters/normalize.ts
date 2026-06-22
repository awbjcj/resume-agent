const PUNCT = /[^a-z0-9+#. ]+/g;
const WS = /\s+/g;

export function normalizeSkill(skill: string): string {
  return skill.toLowerCase().replace(PUNCT, " ").replace(WS, " ").trim();
}
