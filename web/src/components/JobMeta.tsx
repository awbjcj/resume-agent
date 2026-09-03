// Structured meta panel for the modal rail. Labeled rows, null-omitting,
// surfacing the full per-job facet set.

import { fieldLabel, locationLabel, salaryLabel, recency } from "@/lib/format";
import { industryLabel } from "@/lib/filters/industry-label";
import type { JobDetail } from "@/features/job/use-job-detail";

const SPONSORSHIP_TONE: Record<string, string> = {
  offered: "text-success",
  denied: "text-destructive",
  silent: "text-muted-foreground",
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-2">
      <dt className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </dt>
      <dd className="text-right text-base font-medium">{children}</dd>
    </div>
  );
}

export function JobMeta({ job }: { job: JobDetail }) {
  const salary = salaryLabel(job.salaryMin, job.salaryMax, job.salaryCurrency);
  const posted = recency(job.postedAt);
  const location = locationLabel(job);

  const rows: Array<[string, React.ReactNode]> = [];
  if (salary) rows.push(["Salary", salary]);
  if (job.seniority) rows.push(["Seniority", fieldLabel(job.seniority)]);
  if (job.employmentType) rows.push(["Type", fieldLabel(job.employmentType)]);
  if (job.remotePolicy) rows.push(["Remote", fieldLabel(job.remotePolicy)]);
  if (job.sponsorshipSignal)
    rows.push([
      "Sponsorship",
      <span className={SPONSORSHIP_TONE[job.sponsorshipSignal] ?? ""}>
        {fieldLabel(job.sponsorshipSignal)}
      </span>,
    ]);
  if (job.industry) rows.push(["Industry", industryLabel(job.industry)]);
  if (job.companySize) rows.push(["Company size", fieldLabel(job.companySize)]);
  if (location) rows.push(["Location", location]);
  if (posted) rows.push(["Posted", posted]);
  rows.push(["Source", fieldLabel(job.source)]);

  return (
    <dl className="divide-y divide-border/60">
      {rows.map(([label, value], i) => (
        <div
          key={label}
          className="rise-in"
          style={{ "--rise-i": i } as React.CSSProperties}
        >
          <Row label={label}>{value}</Row>
        </div>
      ))}
    </dl>
  );
}
