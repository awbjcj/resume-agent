import { useRunStore } from "@/lib/runs/store";

type BuildReport = {
  experiences?: number;
  projects?: number;
  anchorDecisions?: string[];
  verificationDrops?: string[];
  conflicts?: string[];
  warnings?: string[];
};

function Section({ title, lines, tone }: {
  title: string; lines: string[]; tone?: "warn";
}) {
  if (lines.length === 0) return null;
  return (
    <div>
      <div className="text-xs font-medium uppercase text-muted-foreground">{title}</div>
      <ul className={`mt-1 flex flex-col gap-0.5 text-sm ${tone === "warn" ? "text-destructive" : ""}`}>
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </div>
  );
}

export function BuildReportPanel() {
  const runs = useRunStore((s) => s.runs);
  const latest = Object.values(runs)
    .filter((run) => run.kind === "profile-build" && run.status === "succeeded")
    .sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0))[0];
  if (!latest?.result) return null;
  const report = latest.result as BuildReport;

  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <div className="text-sm font-medium">
        Last build: {report.experiences ?? 0} experiences, {report.projects ?? 0} projects
      </div>
      <Section title="Anchor decisions" lines={report.anchorDecisions ?? []} />
      <Section title="Dropped claims" lines={report.verificationDrops ?? []} tone="warn" />
      <Section title="Conflicts" lines={report.conflicts ?? []} />
      <Section title="Warnings" lines={report.warnings ?? []} tone="warn" />
    </div>
  );
}
