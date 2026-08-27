export function PageHeader({
  kicker,
  title,
  sub,
}: {
  kicker: string;
  title: string;
  sub?: string;
}) {
  return (
    <header className="mb-5 grid gap-2.5 border-b pb-5 sm:mb-7 sm:gap-3 sm:pb-6 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-end">
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-primary">{kicker}</p>
        {/* Tracking and leading are size-specific: as display type grows the
            letters read too far apart and the lines too loose, so both tighten
            here while the small uppercase kicker above keeps positive tracking. */}
        <h1 className="mt-1.5 font-heading text-3xl font-semibold leading-[1.08] tracking-[-0.025em] text-balance text-foreground sm:mt-2 sm:text-4xl md:text-5xl">
          {title}
        </h1>
      </div>
      {sub ? (
        <p className="max-w-[64ch] text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7 xl:text-right">
          {sub}
        </p>
      ) : null}
    </header>
  );
}
