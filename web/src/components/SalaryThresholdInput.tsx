import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function salarySummary(value: string) {
  const salary = Number(value.trim());
  if (!Number.isFinite(salary) || salary <= 0) return "Any annual salary";

  const rounded = Math.round(salary);
  if (rounded >= 1_000_000 && rounded % 1_000 === 0) {
    return `$${rounded / 1_000_000}M+ / year`;
  }
  if (rounded >= 1_000 && rounded % 1_000 === 0) return `$${rounded / 1_000}k+ / year`;
  return `$${rounded.toLocaleString("en-US")}+ / year`;
}

export function SalaryThresholdInput({
  id,
  value,
  valid,
  onChange,
}: {
  id: string;
  value: string;
  valid: boolean;
  onChange: (value: string) => void;
}) {
  const descriptionId = `${id}-description`;

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id} className="text-xs font-semibold uppercase tracking-[0.14em]">
        Min salary (USD)
      </Label>
      <div className="relative">
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-sm text-muted-foreground"
        >
          $
        </span>
        <Input
          id={id}
          type="number"
          min={0}
          step={10000}
          inputMode="numeric"
          className="h-10 bg-card pl-7 tabular-nums"
          value={value}
          aria-invalid={!valid}
          aria-describedby={descriptionId}
          onChange={(event) => onChange(event.target.value)}
        />
      </div>
      <p
        id={descriptionId}
        className={valid ? "text-xs text-muted-foreground" : "text-xs text-destructive"}
      >
        {valid ? salarySummary(value) : "Enter a non-negative annual salary."}
      </p>
    </div>
  );
}
