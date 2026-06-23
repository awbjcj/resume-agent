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
    <header className="mb-7 grid gap-3 border-b pb-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-primary">{kicker}</p>
        <h1 className="mt-2 text-4xl font-semibold text-foreground md:text-5xl">
          {title}
        </h1>
      </div>
      {sub ? (
        <p className="max-w-[64ch] text-base leading-7 text-muted-foreground lg:text-right">
          {sub}
        </p>
      ) : null}
    </header>
  );
}
