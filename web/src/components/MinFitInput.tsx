import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";

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
  const descriptionId = `${id}-description`;

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id} className="text-xs font-semibold uppercase tracking-[0.14em]">
        Min fit
      </Label>
      <div className="flex min-h-10 items-center gap-3">
        <div className="flex shrink-0 items-center gap-2">
          <Input
            id={id}
            type="number"
            min={0}
            max={100}
            step={1}
            inputMode="numeric"
            placeholder="Any"
            className="h-10 w-20 bg-card text-right tabular-nums"
            value={value === 0 ? "" : value}
            aria-describedby={descriptionId}
            onChange={(event) => onChange(fitValue(event.target.value))}
          />
          <span className="shrink-0 text-sm tabular-nums text-muted-foreground">/ 100</span>
        </div>
        <Slider
          aria-label="Minimum fit slider"
          value={[value]}
          min={0}
          max={100}
          step={1}
          onValueChange={(nextValue) =>
            onChange(typeof nextValue === "number" ? nextValue : (nextValue[0] ?? 0))
          }
        />
      </div>
      <p id={descriptionId} className="text-xs text-muted-foreground">
        Blank or 0 includes every fit score.
      </p>
    </div>
  );
}
