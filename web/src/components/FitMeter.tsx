export function FitMeter({ score }: { score: number | null }) {
  const label = score === null ? "no fit score" : `fit score ${score}`;

  return (
    <div
      className="flex size-12 shrink-0 flex-col items-center justify-center rounded-lg border bg-accent/70 text-accent-foreground sm:size-16"
      aria-label={label}
    >
      <span className="text-lg font-semibold leading-none sm:text-2xl">
        {score ?? "\u2014"}
      </span>
      <span className="mt-1 text-[0.58rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground sm:text-[0.63rem] sm:tracking-[0.2em]">
        fit
      </span>
    </div>
  );
}
