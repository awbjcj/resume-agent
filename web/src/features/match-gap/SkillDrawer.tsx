import { BriefcaseBusiness } from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

export type SuggestionKind = "skill" | "theme";

type Job = {
  id: number;
  company?: string | null;
  title?: string | null;
  seniority?: string | null;
};

export function SkillDrawer({
  kind,
  targetKey,
  label,
  jobs,
  onClose,
}: {
  kind: SuggestionKind;
  targetKey: string | null;
  label: string | null;
  jobs: Job[];
  onClose: () => void;
}) {
  return (
    <Sheet open={targetKey !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto p-0 sm:max-w-xl">
        <SheetHeader className="border-b bg-accent/45 px-6 py-7 pr-14">
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-primary">
            {kind === "theme" ? "Theme path" : "Skill evidence"}
          </p>
          <SheetTitle className="mt-1 text-xl font-semibold">{label}</SheetTitle>
          <SheetDescription>
            {jobs.length} target {jobs.length === 1 ? "job" : "jobs"} demand this {kind}
          </SheetDescription>
        </SheetHeader>

        <section aria-labelledby="demanding-jobs-title" className="px-6 py-6">
          <h2 id="demanding-jobs-title" className="text-sm font-semibold">
            Demanding roles
          </h2>
          {jobs.length === 0 ? (
            <p role="status" className="mt-4 border-l-2 border-muted px-3 text-sm text-muted-foreground">
              No target jobs match the current filters.
            </p>
          ) : (
            <ul className="mt-3 divide-y border-y">
              {jobs.map((job) => (
                <li key={job.id} className="flex gap-3 py-3">
                  <BriefcaseBusiness className="mt-0.5 size-4 shrink-0 text-primary" />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{job.company ?? "Unknown company"}</p>
                    <p className="mt-0.5 text-sm text-muted-foreground">
                      {job.title ?? "Untitled role"}
                      {job.seniority ? ` · ${job.seniority}` : ""}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </SheetContent>
    </Sheet>
  );
}
