// Radial fit dial — the modal's focal element. An SVG ring sweeps from empty
// to the score once on open (CSS keyframe, see .dial-ring in index.css), with
// the number counting in the center. Score bands tint the arc.

const BANDS = [
  { min: 80, stroke: "var(--chart-2)" }, // strong — green
  { min: 60, stroke: "var(--primary)" }, // solid — teal
  { min: 0, stroke: "var(--chart-4)" }, // weak — muted blue
];

export function FitDial({ score, size = 160 }: { score: number | null; size?: number }) {
  const r = size / 2 - 10;
  const circ = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score ?? 0)) / 100;
  const offset = circ * (1 - pct);
  const stroke = BANDS.find((b) => (score ?? 0) >= b.min)?.stroke ?? "var(--chart-4)";

  return (
    <div
      className="relative grid place-items-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={score == null ? "no fit score" : `fit score ${score} of 100`}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="block">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--border)"
          strokeWidth={9}
        />
        {score != null && (
          <circle
            className="dial-ring"
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={stroke}
            strokeWidth={9}
            strokeLinecap="round"
            style={
              {
                "--dial-circ": `${circ}px`,
                "--dial-offset": `${offset}px`,
              } as React.CSSProperties
            }
          />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-heading text-5xl font-semibold leading-none tabular-nums">
          {score ?? "—"}
        </span>
        <span className="mt-2 text-xs font-semibold uppercase tracking-[0.24em] text-muted-foreground">
          fit
        </span>
      </div>
    </div>
  );
}
