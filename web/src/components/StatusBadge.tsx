import { Badge } from "@/components/ui/badge";
import { useTranslation } from "react-i18next";

const TONES: Record<string, string> = {
  raw: "border-neutral-300 bg-neutral-100 text-neutral-700 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-200",
  shortlisted:
    "border-cyan-200 bg-cyan-50 text-cyan-800 dark:border-cyan-900 dark:bg-cyan-950/50 dark:text-cyan-200",
  approved:
    "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200",
  tailored:
    "border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-900 dark:bg-blue-950/50 dark:text-blue-200",
  rendered:
    "border-teal-200 bg-teal-50 text-teal-800 dark:border-teal-900 dark:bg-teal-950/50 dark:text-teal-200",
  rejected:
    "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-950/50 dark:text-rose-200",
};

export function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  const fallback = status.replace(/_/g, " ");
  const label = {
    raw: t("job.stages.raw"),
    extracted: t("job.stages.extracted"),
    filtered: t("job.stages.filtered"),
    rejected: t("job.stages.rejected"),
    shortlisted: t("job.stages.shortlisted"),
    approved: t("job.stages.approved"),
    tailored: t("job.stages.tailored"),
    rendered: t("job.stages.rendered"),
  }[status] ?? fallback;

  return (
    <Badge
      variant="outline"
      className={`rounded-full px-2.5 py-0.5 text-[0.68rem] font-semibold uppercase tracking-[0.14em] ${
        TONES[status] ?? "bg-secondary text-secondary-foreground"
      }`}
    >
      {label}
    </Badge>
  );
}
