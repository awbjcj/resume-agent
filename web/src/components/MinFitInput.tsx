import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function fitValue(value: string): number {
  if (!value) return 0;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 0;
  return Math.min(100, Math.max(0, Math.round(parsed)));
}

export function MinFitInput({
  id,
  value,
  onChange,
}: {
  id: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id} className="text-xs font-semibold uppercase tracking-[0.14em]">
        Min fit
      </Label>
      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="number"
          min={0}
          max={100}
          step={1}
          inputMode="numeric"
          placeholder="Any"
          className="h-10 bg-card tabular-nums"
          value={value === 0 ? "" : value}
          onChange={(event) => onChange(fitValue(event.target.value))}
        />
        <span className="shrink-0 text-sm tabular-nums text-muted-foreground">/ 100</span>
      </div>
      <p className="text-xs text-muted-foreground">Leave blank to include every fit score.</p>
    </div>
  );
}
