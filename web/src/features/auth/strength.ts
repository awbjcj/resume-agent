export type StrengthScore = 0 | 1 | 2 | 3 | 4;
export type StrengthHintKey =
  | "auth.passwordStrength.hints.tooShort"
  | "auth.passwordStrength.hints.predictable"
  | "auth.passwordStrength.hints.addVariety"
  | "auth.passwordStrength.hints.reasonable";

const hasRun = (value: string) => /(.)\1{3,}/.test(value);

function hasSequence(value: string): boolean {
  const lowered = value.toLowerCase();
  for (let index = 0; index + 3 < lowered.length; index += 1) {
    const start = lowered.charCodeAt(index);
    if ([1, 2, 3].every((offset) => lowered.charCodeAt(index + offset) === start + offset)) {
      return true;
    }
  }
  return false;
}

export function scorePassword(password: string): { score: StrengthScore; hintKey: StrengthHintKey } {
  if (!password) return { score: 0, hintKey: "auth.passwordStrength.hints.tooShort" };
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((pattern) =>
    pattern.test(password),
  ).length;
  let points = password.length >= 12 ? 2 : password.length >= 8 ? 1 : 0;
  if (password.length >= 20) points += 1;
  if (classes >= 3) points += 1;
  if (hasRun(password) || hasSequence(password)) points -= 2;
  const score = Math.max(0, Math.min(4, points)) as StrengthScore;
  const hint =
    password.length < 12
      ? "auth.passwordStrength.hints.tooShort"
      : hasRun(password) || hasSequence(password)
        ? "auth.passwordStrength.hints.predictable"
        : classes < 3
          ? "auth.passwordStrength.hints.addVariety"
          : "auth.passwordStrength.hints.reasonable";
  return { score, hintKey: hint };
}
