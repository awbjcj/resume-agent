import { useTranslation } from "react-i18next";

import {
  profileBuildReportLineLabel,
  profileBuildStatusLabel,
} from "@/i18n/profile-build-diagnostics";
import { useRunStore } from "@/lib/runs/store";

type BuildReport = {
  experiences?: number;
  projects?: number;
  docStatus?: Record<string, string>;
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
  const { t } = useTranslation();
  const runs = useRunStore((s) => s.runs);
  const latest = Object.values(runs)
    .filter((run) => run.kind === "profile-build" && run.status === "succeeded")
    .sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0))[0];
  if (!latest?.result) return null;
  const report = latest.result as BuildReport;
  const docStatus = Object.entries(report.docStatus ?? {})
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([doc, status]) => `${doc}: ${profileBuildStatusLabel(t, status)}`);

  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <div className="text-sm font-medium">
        Last build: {report.experiences ?? 0} experiences, {report.projects ?? 0} projects
      </div>
      <Section title="Document status" lines={docStatus} />
      <Section
        title="Anchor decisions"
        lines={(report.anchorDecisions ?? []).map((line) => profileBuildReportLineLabel(t, "anchor", line))}
      />
      <Section
        title="Dropped claims"
        lines={(report.verificationDrops ?? []).map((line) => profileBuildReportLineLabel(t, "verificationDrop", line))}
        tone="warn"
      />
      <Section
        title="Conflicts"
        lines={(report.conflicts ?? []).map((line) => profileBuildReportLineLabel(t, "conflict", line))}
      />
      <Section
        title="Warnings"
        lines={(report.warnings ?? []).map((line) => profileBuildReportLineLabel(t, "warning", line))}
        tone="warn"
      />
    </div>
  );
}
