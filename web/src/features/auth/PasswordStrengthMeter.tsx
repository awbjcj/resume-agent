import { useTranslation } from "react-i18next";

import { Progress } from "@/components/ui/progress";
import { scorePassword } from "./strength";

const strengthLabelKeys = [
  "auth.passwordStrength.labels.veryWeak",
  "auth.passwordStrength.labels.weak",
  "auth.passwordStrength.labels.fair",
  "auth.passwordStrength.labels.good",
  "auth.passwordStrength.labels.strong",
] as const;

export function PasswordStrengthMeter({ password }: { password: string }) {
  const { t } = useTranslation();
  const { score, hintKey } = scorePassword(password);
  const label = t(strengthLabelKeys[score]);
  return (
    <div className="mt-2" data-slot="password-strength">
      <Progress value={score * 25} aria-label={t("auth.passwordStrength.ariaLabel", { label })} />
      <p className="mt-1.5 text-xs text-muted-foreground" role="status">
        {label} — {t(hintKey)}
      </p>
    </div>
  );
}
