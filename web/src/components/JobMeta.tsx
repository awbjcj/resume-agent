// Structured meta panel for the modal rail. Labeled rows, null-omitting,
// surfacing the full per-job facet set.

import { salaryLabel, recency } from "@/lib/format";
import type { JobDetail } from "@/features/job/use-job-detail";

const SPONSORSHIP_TONE: Record<string, string> = {
  offered: "text-emerald-600 dark:text-emerald-400",
  denied: "text-rose-600 dark:text-rose-400",
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
  const locationParts = [job.locationCity, job.locationRegion, job.locationCountry]
    .filter(Boolean)
    .join(", ");

  const rows: Array<[string, React.ReactNode]> = [];
  if (salary) rows.push(["Salary", salary]);
  if (job.seniority) rows.push(["Seniority", job.seniority]);
  if (job.employmentType) rows.push(["Type", job.employmentType]);
  if (job.remotePolicy) rows.push(["Remote", job.remotePolicy]);
  if (job.sponsorshipSignal)
    rows.push([
      "Sponsorship",
      <span className={SPONSORSHIP_TONE[job.sponsorshipSignal] ?? ""}>
        {job.sponsorshipSignal}
      </span>,
    ]);
  if (job.industry) rows.push(["Industry", job.industry]);
  if (job.sicLabel) rows.push(["Sector", job.sicLabel]);
  if (job.companySize) rows.push(["Company size", job.companySize]);
  if (locationParts || job.location)
    rows.push(["Location", locationParts || job.location]);
  if (posted) rows.push(["Posted", posted]);
  rows.push(["Source", job.source]);

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
