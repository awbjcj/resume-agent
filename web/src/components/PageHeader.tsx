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
    <header className="mb-6 border-b-2 border-foreground pb-4">
      <p className="font-mono text-xs uppercase tracking-[0.3em] text-primary">{kicker}</p>
      <h1 className="font-serif text-4xl font-bold leading-tight">{title}</h1>
      {sub ? <p className="mt-2 max-w-[70ch] text-muted-foreground">{sub}</p> : null}
    </header>
  );
}
