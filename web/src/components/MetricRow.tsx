export function MetricRow({ items }: { items: [string, string][] }) {
  return (
    <div className="mb-6 flex flex-wrap gap-3">
      {items.map(([label, value]) => (
        <div
          key={label}
          className="min-w-[150px] flex-1 rounded-lg border border-border bg-card p-4"
        >
          <div className="font-serif text-2xl font-bold leading-none">{value}</div>
          <div className="mt-2 font-mono text-[0.7rem] uppercase tracking-widest text-muted-foreground">
            {label}
          </div>
        </div>
      ))}
    </div>
  );
}
