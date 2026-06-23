export function MetricRow({ items }: { items: [string, string][] }) {
  return (
    <div className="mb-7 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
      {items.map(([label, value]) => (
        <div
          key={label}
          className="relative overflow-hidden rounded-lg border bg-card p-5 shadow-[0_1px_2px_rgba(24,32,38,0.04)]"
        >
          <div className="absolute inset-x-0 top-0 h-1 bg-primary/80" />
          <div className="text-3xl font-semibold leading-none">{value}</div>
          <div className="mt-3 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            {label}
          </div>
        </div>
      ))}
    </div>
  );
}
