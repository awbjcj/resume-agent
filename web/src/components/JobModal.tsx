import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { CoverLetterItem } from "@/features/job/CoverLetterRow";
import { StatusBadge } from "./StatusBadge";
import { FitDial } from "./FitDial";
import { JobMeta } from "./JobMeta";
import { SkillMatrix } from "./SkillMatrix";
import { DrawerSkeleton } from "./skeletons";
import { ApplicationEditor } from "@/features/job/ApplicationEditor";
import { CoverLettersTab } from "@/features/job/CoverLettersTab";
import { StageManager } from "@/features/job/StageManager";
import { InterviewTab } from "@/features/interview/InterviewTab";
import { VersionRow } from "@/features/job/VersionRow";
import { RevisionRunPlaceholders } from "@/features/job/RevisionRunPlaceholders";
import { useJobDetail } from "@/features/job/use-job-detail";
import { JdBody } from "./JdBody";

type ClosedLoopApplication = {
  resumeVersionId?: number | null;
  coverLetterId?: number | null;
};

type ClosedLoopJob = {
  coverLetters?: CoverLetterItem[];
  application?: ClosedLoopApplication | null;
};

const tabTriggerClass =
  "h-10 flex-none rounded-full px-4 py-2 text-sm font-semibold text-muted-foreground after:hidden hover:bg-background/70 data-active:bg-background data-active:text-foreground data-active:shadow-sm data-active:ring-1 data-active:ring-border/70";

const tabCountClass =
  "ml-1.5 inline-flex min-w-5 justify-center rounded-full bg-muted px-1.5 text-[11px] font-semibold tabular-nums text-muted-foreground";

export function JobModal({ jobId, onClose }: { jobId: number; onClose: () => void }) {
  const { data: job, isLoading } = useJobDetail(jobId);
  const closedLoopJob = job as (NonNullable<typeof job> & ClosedLoopJob) | undefined;
  const coverLetters = closedLoopJob?.coverLetters ?? [];

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="block max-h-[92vh] w-full max-w-[calc(100%-1.5rem)] gap-0 overflow-hidden rounded-2xl p-0 shadow-[0_40px_120px_-24px_rgba(8,32,40,0.55)] sm:max-w-6xl">
        {isLoading || !job ? (
          <div className="p-6">
            <DrawerSkeleton />
          </div>
        ) : (
          <div className="flex max-h-[92vh] flex-col">
            {/* ── Gradient-mesh masthead ─────────────────────────────── */}
            <header className="jobmodal-mesh relative shrink-0 overflow-hidden border-b px-8 py-7 pr-16">
              <div className="relative">
                <DialogTitle className="font-heading text-3xl leading-tight font-semibold text-foreground sm:text-4xl">
                  {job.title ?? "—"}
                </DialogTitle>
                <div className="mt-3 flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-base text-foreground/70">
                  <span className="font-medium text-foreground/90">
                    {job.company ?? "—"}
                  </span>
                  <span aria-hidden>·</span>
                  <span>{job.location ?? "location n/a"}</span>
                  <StatusBadge status={job.status} />
                  {job.url && (
                    <a
                      href={job.url}
                      target="_blank"
                      rel="noreferrer"
                      className="ml-auto inline-flex items-center gap-1 rounded-full border border-foreground/15 bg-background/60 px-3.5 py-1.5 text-sm font-semibold backdrop-blur-sm transition-colors hover:bg-background"
                    >
                      Open posting ↗
                    </a>
                  )}
                </div>
              </div>
            </header>

            {/* ── Two-pane body: rail (fit + meta + skills) | main (JD) ─ */}
            <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
              <aside className="shrink-0 space-y-6 overflow-y-auto border-b bg-muted/30 px-6 py-6 lg:w-[400px] lg:border-b-0 lg:border-r">
                <div className="flex justify-center">
                  <FitDial score={job.fitScore} />
                </div>
                <JobMeta job={job} />
                <div className="rise-in" style={{ "--rise-i": 4 } as React.CSSProperties}>
                  <h3 className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                    Skills
                  </h3>
                  <SkillMatrix skills={job.skills} />
                </div>
              </aside>

              <section className="flex min-h-0 min-w-0 flex-1 flex-col">
                <Tabs defaultValue="jd" className="flex min-h-0 flex-1 flex-col">
                  <TabsList className="h-auto w-full shrink-0 flex-wrap justify-start gap-2 rounded-none border-b bg-muted/25 px-6 py-4 text-base group-data-horizontal/tabs:h-auto">
                    <TabsTrigger value="jd" className={tabTriggerClass}>Job description</TabsTrigger>
                    <TabsTrigger value="versions" className={tabTriggerClass}>
                      Versions
                      {job.resumeVersions.length > 0 && (
                        <span className={tabCountClass}>
                          {job.resumeVersions.length}
                        </span>
                      )}
                    </TabsTrigger>
                    <TabsTrigger value="coverLetters" className={tabTriggerClass}>
                      Cover letters
                      {coverLetters.length > 0 && (
                        <span className={tabCountClass}>
                          {coverLetters.length}
                        </span>
                      )}
                    </TabsTrigger>
                    <TabsTrigger value="application" className={tabTriggerClass}>Application</TabsTrigger>
                    <TabsTrigger value="interview" className={tabTriggerClass}>Interview</TabsTrigger>
                    <TabsTrigger value="manage" className={tabTriggerClass}>Manage</TabsTrigger>
                  </TabsList>

                  <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
                    <TabsContent value="jd" className="mt-0">
                      {job.status === "rejected" && job.rejectReason && (
                        <div className="mb-5 rounded-xl border border-rose-200 bg-rose-50 p-5 dark:border-rose-900 dark:bg-rose-950/40">
                          <span className="block text-xs font-semibold uppercase tracking-[0.16em] text-rose-700 dark:text-rose-300">
                            Rejected during discovery
                          </span>
                          <p className="mt-1.5 text-[15px] leading-7 text-rose-900 dark:text-rose-100">
                            {job.rejectReason}
                          </p>
                        </div>
                      )}
                      {job.fitRationale && (
                        <p className="mb-5 rounded-xl border bg-accent/40 p-5 text-[15px] leading-7">
                          {job.fitRationale}
                        </p>
                      )}
                      <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                        Job description
                      </h3>
                      <JdBody text={job.jdText} />
                    </TabsContent>

                    <TabsContent value="versions" className="mt-0">
                      <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                        Resume versions
                      </h3>
                      {job.resumeVersions.length === 0 && (
                        <p className="mt-2 text-sm text-muted-foreground">
                          Not tailored yet.
                        </p>
                      )}
                      <ul className="mt-2 space-y-2">
                        {job.resumeVersions.map((v) => (
                          <VersionRow
                            key={v.id}
                            jobId={jobId}
                            version={v}
                            appliedVersionId={
                              closedLoopJob?.application?.resumeVersionId ?? null
                            }
                          />
                        ))}
                        <RevisionRunPlaceholders
                          jobId={jobId}
                          kind="revise"
                          label="Resume revision"
                        />
                      </ul>
                    </TabsContent>

                    <TabsContent value="coverLetters" className="mt-0">
                      <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                        Cover letters
                      </h3>
                      <CoverLettersTab
                        jobId={jobId}
                        coverLetters={coverLetters}
                        appliedId={closedLoopJob?.application?.coverLetterId ?? null}
                      />
                    </TabsContent>

                    <TabsContent value="application" className="mt-0">
                      <ApplicationEditor jobId={jobId} application={job.application} />
                    </TabsContent>

                    <TabsContent value="interview" className="mt-0">
                      <InterviewTab
                        jobId={jobId}
                        versions={job.resumeVersions}
                        hasJd={Boolean(job.jdText?.trim())}
                      />
                    </TabsContent>

                    <TabsContent value="manage" className="mt-0">
                      <StageManager job={job} onDeleted={onClose} />
                    </TabsContent>
                  </div>
                </Tabs>
              </section>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
