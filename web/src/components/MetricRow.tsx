import type { CSSProperties } from "react";

export function MetricRow({ items }: { items: [string, string][] }) {
  return (
    <div className="mb-7 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
      {items.map(([label, value], index) => (
        <div
          key={label}
          style={{ "--rise-i": index } as CSSProperties}
          className="rise-in relative overflow-hidden rounded-lg border bg-card p-5 shadow-card"
        >
          {/* A hairline that fades out to the right reads as a finish on the
              surface; the old solid 4px bar carried no information and competed
              with the number it sat above. */}
          <div
            aria-hidden="true"
            className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-primary/80 to-primary/10"
          />
          {/* Tabular figures keep the tile from reflowing as the value updates. */}
          <div className="text-3xl font-semibold leading-none tracking-[-0.02em] tabular-nums">
            {value}
          </div>
          <div className="mt-3 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            {label}
          </div>
        </div>
      ))}
    </div>
  );
}
