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
    <header className="mb-7 grid gap-3 border-b pb-6 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-end">
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-primary">{kicker}</p>
        {/* Tracking and leading are size-specific: as display type grows the
            letters read too far apart and the lines too loose, so both tighten
            here while the small uppercase kicker above keeps positive tracking. */}
        <h1 className="mt-2 font-heading text-4xl font-semibold leading-[1.08] tracking-[-0.025em] text-balance text-foreground md:text-5xl">
          {title}
        </h1>
      </div>
      {sub ? (
        <p className="max-w-[64ch] text-base leading-7 text-muted-foreground xl:text-right">
          {sub}
        </p>
      ) : null}
    </header>
  );
}
