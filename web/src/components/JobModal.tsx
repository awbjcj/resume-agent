import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Mail } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmailDraftDialog } from "@/features/job/EmailDraftDialog";
import { RedoDialog } from "@/features/runs/RedoDialog";
import { useRedoRun } from "@/features/runs/use-redo-run";
import type { CoverLetterItem } from "@/features/job/CoverLetterRow";
import { StatusBadge } from "./StatusBadge";
import { FitDial } from "./FitDial";
import { JobMeta } from "./JobMeta";
import { SkillMatrix } from "./SkillMatrix";
import { DrawerSkeleton } from "./skeletons";
import { CoverLettersTab } from "@/features/job/CoverLettersTab";
import { H1BSponsorshipPanel } from "@/features/job/H1BSponsorshipPanel";
import { TrackingTab } from "@/features/job/TrackingTab";
import { InterviewTab } from "@/features/interview/InterviewTab";
import { VersionRow } from "@/features/job/VersionRow";
import { RevisionRunPlaceholders } from "@/features/job/RevisionRunPlaceholders";
import { useJobDetail } from "@/features/job/use-job-detail";
import { JdBody } from "./JdBody";
import { locationLabel } from "@/lib/format";

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
  "ml-1 inline-flex min-w-5 items-center justify-center rounded-full bg-muted px-1.5 text-[11px] font-semibold leading-none tabular-nums text-muted-foreground";

export function JobModal({
  jobId,
  onClose,
  onPrev,
  onNext,
  hasPrev = false,
  hasNext = false,
  isLoadingNext = false,
}: {
  jobId: number;
  onClose: () => void;
  onPrev?: () => void;
  onNext?: () => void;
  hasPrev?: boolean;
  hasNext?: boolean;
  isLoadingNext?: boolean;
}) {
  const { data: job, isLoading } = useJobDetail(jobId);
  const closedLoopJob = job as (NonNullable<typeof job> & ClosedLoopJob) | undefined;
  const coverLetters = closedLoopJob?.coverLetters ?? [];
  const [emailDraftOpen, setEmailDraftOpen] = useState(false);
  const [redoOpen, setRedoOpen] = useState(false);
  const redoRun = useRedoRun();
  const navEnabled = Boolean(onPrev || onNext);

  // Arrow keys step through the list, but never while the user is typing in a
  // field (Tracking tab, cover-letter editors, etc.).
  useEffect(() => {
    if (!navEnabled) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.isContentEditable ||
          target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT")
      ) {
        return;
      }
      if (event.key === "ArrowLeft" && hasPrev) {
        event.preventDefault();
        onPrev?.();
      } else if (event.key === "ArrowRight" && hasNext && !isLoadingNext) {
        event.preventDefault();
        onNext?.();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [navEnabled, hasPrev, hasNext, isLoadingNext, onPrev, onNext]);

  return (
    <>
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="block h-[calc(100svh-1rem)] max-h-[96svh] w-full max-w-[calc(100%-1rem)] gap-0 overflow-hidden rounded-2xl p-0 shadow-[0_40px_120px_-24px_rgba(8,32,40,0.55)] sm:h-[94svh] sm:max-w-[min(1760px,calc(100vw-2rem))]">
        {navEnabled && (
          <>
            <Button
              type="button"
              variant="secondary"
              size="icon"
              aria-label="Previous job"
              title="Previous job (←)"
              className="absolute top-1/2 left-3 z-20 size-9 -translate-y-1/2 rounded-full shadow-md"
              disabled={!hasPrev}
              onClick={onPrev}
            >
              <ChevronLeft className="size-5" aria-hidden="true" />
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="icon"
              aria-label="Next job"
              title="Next job (→)"
              className="absolute top-1/2 right-3 z-20 size-9 -translate-y-1/2 rounded-full shadow-md"
              disabled={!hasNext || isLoadingNext}
              onClick={onNext}
            >
              {isLoadingNext ? (
                <Spinner className="size-5" />
              ) : (
                <ChevronRight className="size-5" aria-hidden="true" />
              )}
            </Button>
          </>
        )}
        {isLoading || !job ? (
          <div className="p-6">
            <DrawerSkeleton />
          </div>
        ) : (
          <div className="flex h-full min-h-0 flex-col">
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
                  <span>{locationLabel(job) ?? "location n/a"}</span>
                  <StatusBadge status={job.status} />
                  <div className="ml-auto flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      className="rounded-full bg-background/60 backdrop-blur-sm"
                      onClick={() => setRedoOpen(true)}
                    >
                      Redo…
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="rounded-full bg-background/60 backdrop-blur-sm"
                      onClick={() => setEmailDraftOpen(true)}
                    >
                      <Mail className="size-4" aria-hidden="true" />
                      Draft email
                    </Button>
                    {job.url && (
                      <a
                        href={job.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 rounded-full border border-foreground/15 bg-background/60 px-3.5 py-1.5 text-sm font-semibold backdrop-blur-sm transition-colors hover:bg-background"
                      >
                        Open posting ↗
                      </a>
                    )}
                  </div>
                </div>
              </div>
            </header>

            {/* Job context and application work stay visible together on wide screens. */}
            <div className="grid min-h-0 flex-1 xl:grid-cols-[minmax(0,1.08fr)_minmax(34rem,0.92fr)]">
              <section
                aria-labelledby="job-brief-title"
                className="min-w-0 overflow-y-auto border-b px-5 py-6 sm:px-8 xl:border-r xl:border-b-0"
              >
                <div className="mx-auto max-w-4xl">
                  <div className="mb-5 flex items-end justify-between gap-4">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
                        Role context
                      </p>
                      <h2 id="job-brief-title" className="mt-1 font-heading text-2xl font-semibold">
                        Job brief
                      </h2>
                    </div>
                    <span className="hidden text-xs text-muted-foreground sm:inline">
                      The source material used for tailoring
                    </span>
                  </div>

                  <div className="grid gap-6 rounded-xl border bg-muted/20 p-4 sm:p-5 lg:grid-cols-[13rem_minmax(0,1fr)]">
                    <div className="flex justify-center lg:border-r lg:pr-5">
                      <FitDial score={job.fitScore} />
                    </div>
                    <JobMeta job={job} />
                  </div>

                  <div className="rise-in mt-6" style={{ "--rise-i": 4 } as React.CSSProperties}>
                    <h3 className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                      Skills requested
                    </h3>
                    <SkillMatrix skills={job.skills} />
                  </div>

                  {(job.status === "rejected" || job.status === "filtered") &&
                    job.rejectReason && (
                    <div className="mt-6 rounded-xl border border-rose-200 bg-rose-50 p-5 dark:border-rose-900 dark:bg-rose-950/40">
                      <span className="block text-xs font-semibold uppercase tracking-[0.16em] text-rose-700 dark:text-rose-300">
                        {job.status === "filtered" || job.rejectCategory === "filtered"
                          ? "Filtered out during discovery"
                          : "Rejected during discovery"}
                      </span>
                      <p className="mt-1.5 text-[15px] leading-7 text-rose-900 dark:text-rose-100">
                        {job.rejectReason}
                      </p>
                    </div>
                  )}

                  {job.fitRationale && (
                    <div className="mt-6 rounded-xl border bg-accent/35 p-5">
                      <h3 className="text-sm font-semibold">Why this role fits</h3>
                      <p className="mt-1.5 text-[15px] leading-7 text-foreground/80">
                        {job.fitRationale}
                      </p>
                    </div>
                  )}

                  <div className="mt-8 border-t pt-6">
                    <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                      Full job description
                    </h3>
                    <JdBody text={job.jdText} />
                  </div>
                </div>
              </section>

              <aside
                aria-labelledby="application-workspace-title"
                className="min-w-0 overflow-y-auto bg-muted/15 px-5 py-6 sm:px-6"
              >
                <div className="mx-auto max-w-3xl space-y-8">
                  <section>
                    <div className="flex flex-wrap items-end justify-between gap-3">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
                          Tailored application
                        </p>
                        <h2 id="application-workspace-title" className="mt-1 font-heading text-2xl font-semibold">
                          Resume versions
                        </h2>
                        <p className="mt-1 text-sm leading-6 text-muted-foreground">
                          Compare each version, understand its evidence choices, and pick what you will send.
                        </p>
                      </div>
                      <Badge variant="outline" className="tabular-nums">
                        {job.resumeVersions.length} version{job.resumeVersions.length === 1 ? "" : "s"}
                      </Badge>
                    </div>
                    {job.resumeVersions.length === 0 && (
                      <p className="mt-4 rounded-xl border border-dashed bg-background/60 p-5 text-sm text-muted-foreground">
                        No tailored resume yet. Use Redo to create the first version.
                      </p>
                    )}
                    <ul className="mt-4 space-y-3">
                      {job.resumeVersions.map((v) => (
                        <VersionRow
                          key={v.id}
                          jobId={jobId}
                          version={v}
                          appliedVersionId={closedLoopJob?.application?.resumeVersionId ?? null}
                        />
                      ))}
                      <RevisionRunPlaceholders
                        jobId={jobId}
                        kind="revise"
                        label="Resume revision"
                      />
                    </ul>
                  </section>

                  <section className="border-t pt-7" aria-label="Sponsorship information">
                    <H1BSponsorshipPanel
                      jobId={jobId}
                      company={job.company}
                      initialResult={job.h1BSponsorship}
                    />
                  </section>

                  <section className="border-t pt-7" aria-labelledby="other-application-tools-title">
                    <div className="mb-3">
                      <h2 id="other-application-tools-title" className="font-heading text-xl font-semibold">
                        Application tools
                      </h2>
                      <p className="mt-1 text-sm text-muted-foreground">
                        Draft supporting material, track progress, or prepare for interviews.
                      </p>
                    </div>
                    <Tabs defaultValue="coverLetters">
                      <TabsList className="h-auto w-full flex-wrap justify-start gap-2 rounded-lg border bg-background/70 p-1.5 group-data-horizontal/tabs:h-auto">
                        <TabsTrigger value="coverLetters" className={tabTriggerClass}>
                          Cover letters
                          {coverLetters.length > 0 && (
                            <span className={tabCountClass}>{coverLetters.length}</span>
                          )}
                        </TabsTrigger>
                        <TabsTrigger value="tracking" className={tabTriggerClass}>Tracking</TabsTrigger>
                        <TabsTrigger value="interview" className={tabTriggerClass}>Interview</TabsTrigger>
                      </TabsList>
                      <div className="mt-4">
                        <TabsContent value="coverLetters" className="mt-0">
                          <CoverLettersTab
                            jobId={jobId}
                            coverLetters={coverLetters}
                            appliedId={closedLoopJob?.application?.coverLetterId ?? null}
                          />
                        </TabsContent>
                        <TabsContent value="tracking" className="mt-0">
                          <TrackingTab job={job} onDeleted={onClose} />
                        </TabsContent>
                        <TabsContent value="interview" className="mt-0">
                          <InterviewTab
                            jobId={jobId}
                            versions={job.resumeVersions}
                            hasJd={Boolean(job.jdText?.trim())}
                          />
                        </TabsContent>
                      </div>
                    </Tabs>
                  </section>
                </div>
              </aside>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
    <EmailDraftDialog
      jobId={jobId}
      open={emailDraftOpen}
      onOpenChange={setEmailDraftOpen}
    />
    <RedoDialog
      open={redoOpen}
      jobIds={[jobId]}
      initialStages={["tailor"]}
      onOpenChange={setRedoOpen}
      onLaunch={(jobIds, stages, deep) => redoRun.redo(jobIds, stages, deep)}
    />
    </>
  );
}
