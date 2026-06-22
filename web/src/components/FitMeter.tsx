export function FitMeter({ score }: { score: number | null }) {
  const label = score === null ? "no fit score" : `fit score ${score}`;

  return (
    <div className="flex flex-col items-center" aria-label={label}>
      <span className="font-serif text-2xl font-bold leading-none">
        {score ?? "\u2014"}
      </span>
      <span className="font-mono text-[0.6rem] uppercase tracking-widest text-muted-foreground">
        fit
      </span>
    </div>
  );
}
