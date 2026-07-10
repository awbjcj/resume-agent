import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";

const CONTROL_LABEL_CLASS =
  "text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground";

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
    <Field className="w-full gap-1.5 sm:w-auto sm:min-w-36 sm:flex-1">
      <FieldLabel htmlFor={id} className={CONTROL_LABEL_CLASS}>
        Min fit
      </FieldLabel>
      <div className="flex h-9 items-center gap-2.5">
        <Slider
          className="min-w-0 flex-1"
          aria-label="Minimum fit slider"
          value={[value]}
          min={0}
          max={100}
          step={1}
          onValueChange={(nextValue) =>
            onChange(
              typeof nextValue === "number" ? nextValue : (nextValue[0] ?? 0),
            )
          }
        />
        <div className="flex shrink-0 items-center gap-1">
          <Input
            id={id}
            type="number"
            min={0}
            max={100}
            step={1}
            inputMode="numeric"
            placeholder="Any"
            className="h-9 w-16 bg-background px-2 text-right tabular-nums"
            value={value === 0 ? "" : value}
            onChange={(event) => onChange(fitValue(event.target.value))}
          />
          <span className="shrink-0 text-xs text-muted-foreground">/100</span>
        </div>
      </div>
    </Field>
  );
}
