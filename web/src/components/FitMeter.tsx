export function FitMeter({ score }: { score: number | null }) {
  const label = score === null ? "no fit score" : `fit score ${score}`;

  return (
    <div
      className="flex size-16 shrink-0 flex-col items-center justify-center rounded-lg border bg-accent/70 text-accent-foreground"
      aria-label={label}
    >
      <span className="text-2xl font-semibold leading-none">
        {score ?? "\u2014"}
      </span>
      <span className="mt-1 text-[0.63rem] font-semibold uppercase tracking-[0.2em] text-muted-foreground">
        fit
      </span>
    </div>
  );
}
