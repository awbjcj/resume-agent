import { recency, salaryLabel } from "@/lib/format";

type ShortlistDetailsRow = {
  salaryMin?: number | null;
  salaryMax?: number | null;
  salaryCurrency?: string | null;
  seniority?: string | null;
  employmentType?: string | null;
  industry?: string | null;
  postedAt?: string | null;
};

export function ShortlistDetails({ row }: { row: ShortlistDetailsRow }) {
  const fields = [
    {
      label: "Compensation",
      value: salaryLabel(row.salaryMin, row.salaryMax, row.salaryCurrency),
    },
    { label: "Level", value: row.seniority },
    { label: "Work type", value: row.employmentType },
    { label: "Industry", value: row.industry },
    { label: "Posted", value: recency(row.postedAt) },
  ].filter((field) => Boolean(field.value));

  if (!fields.length) return null;

  return (
    <dl className="grid grid-cols-2 gap-x-5 gap-y-2.5 whitespace-normal">
      {fields.map((field) => (
        <div key={field.label} className="min-w-0">
          <dt className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground/75">
            {field.label}
          </dt>
          <dd className="mt-0.5 break-words text-sm leading-5 text-foreground">
            {field.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
