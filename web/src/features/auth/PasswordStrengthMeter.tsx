import { Progress } from "@/components/ui/progress";
import { scorePassword } from "./strength";

const labels = ["Very weak", "Weak", "Fair", "Good", "Strong"] as const;

export function PasswordStrengthMeter({ password }: { password: string }) {
  const { score, hint } = scorePassword(password);
  return (
    <div className="mt-2" data-slot="password-strength">
      <Progress value={score * 25} aria-label={`Password strength: ${labels[score]}`} />
      <p className="mt-1.5 text-xs text-muted-foreground" role="status">
        {labels[score]} — {hint}
      </p>
    </div>
  );
}
