import { ChevronLeft, ChevronRight, Mail } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CareerLabTab } from "@/features/career-lab/CareerLabTab";
import { InterviewTab } from "@/features/interview/InterviewTab";
import type { CoverLetterItem } from "@/features/job/CoverLetterRow";
import { CoverLettersTab } from "@/features/job/CoverLettersTab";
import { EmailDraftDialog } from "@/features/job/EmailDraftDialog";
import { H1BSponsorshipPanel } from "@/features/job/H1BSponsorshipPanel";
import { CompanyIntelligencePanel } from "@/features/job/CompanyIntelligencePanel";
import { ResumeVersionsTab } from "@/features/job/ResumeVersionsTab";
import { TrackingTab } from "@/features/job/TrackingTab";
import { useJobDetail } from "@/features/job/use-job-detail";
import { RedoDialog } from "@/features/runs/RedoDialog";
import { useRedoRun } from "@/features/runs/use-redo-run";
import { locationLabel } from "@/lib/format";
import { FitDial } from "./FitDial";
import { JdBody } from "./JdBody";
import { JobMeta } from "./JobMeta";
import { SkillMatrix } from "./SkillMatrix";
import { StatusBadge } from "./StatusBadge";
import { DrawerSkeleton } from "./skeletons";

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
  const closedLoopJob = job as
    | (NonNullable<typeof job> & ClosedLoopJob)
    | undefined;
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
        <DialogContent className="block max-h-[92vh] w-full max-w-[calc(100%-1.5rem)] gap-0 overflow-hidden rounded-2xl p-0 shadow-[0_40px_120px_-24px_rgba(8,32,40,0.55)] sm:max-w-7xl">
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
            <div className="flex max-h-[92vh] min-h-0 flex-col">
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

              <Tabs defaultValue="job" className="flex min-h-0 flex-1 flex-col">
                <TabsList className="h-auto w-full shrink-0 flex-nowrap justify-start gap-1 overflow-x-auto rounded-none border-b bg-muted/25 px-4 py-3 text-base group-data-horizontal/tabs:h-auto sm:px-8">
                  <TabsTrigger value="job" className={tabTriggerClass}>
                    Job details
                  </TabsTrigger>
                  <TabsTrigger value="resumes" className={tabTriggerClass}>
                    Resumes
                    {job.resumeVersions.length > 0 && (
                      <span className={tabCountClass}>
                        {job.resumeVersions.length}
                      </span>
                    )}
                  </TabsTrigger>
                  <TabsTrigger value="sponsorship" className={tabTriggerClass}>
                    Sponsorship
                  </TabsTrigger>
                  <TabsTrigger value="research" className={tabTriggerClass}>
                    Research
                  </TabsTrigger>
                  <TabsTrigger value="coverLetters" className={tabTriggerClass}>
                    Cover letters
                    {coverLetters.length > 0 && (
                      <span className={tabCountClass}>
                        {coverLetters.length}
                      </span>
                    )}
                  </TabsTrigger>
                  <TabsTrigger value="tracking" className={tabTriggerClass}>
                    Tracking
                  </TabsTrigger>
                  <TabsTrigger value="interview" className={tabTriggerClass}>
                    Interview
                  </TabsTrigger>
                  <TabsTrigger value="careerLab" className={tabTriggerClass}>
                    Career Lab
                  </TabsTrigger>
                </TabsList>

                <div className="min-h-0 flex-1 overflow-y-auto bg-muted/10 px-5 py-6 sm:px-8 sm:py-8">
                  <TabsContent
                    value="job"
                    className="mx-auto mt-0 max-w-[94rem]"
                  >
                    <div className="mb-6 flex items-end justify-between gap-4">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
                          Role context
                        </p>
                        <h2 className="mt-1 font-heading text-2xl font-semibold">
                          Job Brief
                        </h2>
                      </div>
                      <span className="hidden text-xs text-muted-foreground sm:inline">
                        The source material used for tailoring
                      </span>
                    </div>

                    <div className="grid gap-6 rounded-xl border bg-background/70 p-4 sm:p-5 lg:grid-cols-[minmax(18rem,0.7fr)_minmax(28rem,1.3fr)]">
                      <div className="space-y-5 lg:border-r lg:pr-6">
                        <div className="flex justify-center">
                          <FitDial score={job.fitScore} />
                        </div>
                        <JobMeta job={job} />
                      </div>
                      <div
                        className="rise-in"
                        style={{ "--rise-i": 4 } as React.CSSProperties}
                      >
                        <h3 className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                          Skills requested
                        </h3>
                        <SkillMatrix skills={job.skills} />
                      </div>
                    </div>

                    {(job.status === "rejected" || job.status === "filtered") &&
                      job.rejectReason && (
                        <div className="tone-panel mt-6 rounded-xl p-5" data-tone="danger">
                          <span className="tone-accent block text-xs font-semibold uppercase tracking-[0.16em]">
                            {job.status === "filtered" ||
                            job.rejectCategory === "filtered"
                              ? "Filtered out during discovery"
                              : "Rejected during discovery"}
                          </span>
                          <p className="mt-1.5 text-[15px] leading-7">
                            {job.rejectReason}
                          </p>
                        </div>
                      )}

                    {job.fitRationale && (
                      <div className="mt-6 rounded-xl border bg-accent/35 p-5">
                        <h3 className="text-sm font-semibold">
                          Why this role fits
                        </h3>
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
                  </TabsContent>

                  <TabsContent
                    value="resumes"
                    className="mx-auto mt-0 max-w-[94rem]"
                  >
                    <div className="flex flex-wrap items-end justify-between gap-3">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
                          Tailored application
                        </p>
                        <h2 className="mt-1 font-heading text-2xl font-semibold">
                          Resume versions
                        </h2>
                        <p className="mt-1 text-sm leading-6 text-muted-foreground">
                          Compare each version, understand its evidence choices,
                          and pick what you will send.
                        </p>
                      </div>
                      <Badge variant="outline" className="tabular-nums">
                        {`${job.resumeVersions.length} version${job.resumeVersions.length === 1 ? "" : "s"}`}
                      </Badge>
                    </div>
                    {job.resumeVersions.length === 0 && (
                      <p className="mt-4 rounded-xl border border-dashed bg-background/60 p-5 text-sm text-muted-foreground">
                        No tailored resume yet. Use Redo to create the first
                        version.
                      </p>
                    )}
                    <ResumeVersionsTab
                      jobId={jobId}
                      versions={job.resumeVersions}
                      appliedVersionId={
                        closedLoopJob?.application?.resumeVersionId ?? null
                      }
                    />
                  </TabsContent>

                  <TabsContent
                    value="sponsorship"
                    className="mx-auto mt-0 max-w-6xl"
                  >
                    <H1BSponsorshipPanel
                      jobId={jobId}
                      company={job.company}
                      initialResult={job.h1BSponsorship}
                    />
                  </TabsContent>

                  <TabsContent
                    value="research"
                    className="mx-auto mt-0 max-w-6xl"
                  >
                    <CompanyIntelligencePanel
                      jobId={jobId}
                      company={job.company}
                      initialResult={job.companyIntelligence}
                    />
                  </TabsContent>

                  <TabsContent
                    value="coverLetters"
                    className="mx-auto mt-0 max-w-6xl"
                  >
                    <h2 className="mb-4 font-heading text-2xl font-semibold">
                      Cover letters
                    </h2>
                    <CoverLettersTab
                      jobId={jobId}
                      coverLetters={coverLetters}
                      appliedId={
                        closedLoopJob?.application?.coverLetterId ?? null
                      }
                    />
                  </TabsContent>

                  <TabsContent
                    value="tracking"
                    className="mx-auto mt-0 max-w-6xl"
                  >
                    <TrackingTab job={job} onDeleted={onClose} />
                  </TabsContent>

                  <TabsContent
                    value="interview"
                    className="mx-auto mt-0 max-w-6xl"
                  >
                    <InterviewTab
                      jobId={jobId}
                      versions={job.resumeVersions}
                      hasJd={Boolean(job.jdText?.trim())}
                    />
                  </TabsContent>

                  <TabsContent
                    value="careerLab"
                    className="mx-auto mt-0 max-w-6xl"
                  >
                    <CareerLabTab
                      jobId={jobId}
                      jobLabel={
                        [job.title, job.company].filter(Boolean).join(" at ") ||
                        `job #${jobId}`
                      }
                      versions={job.resumeVersions}
                    />
                  </TabsContent>
                </div>
              </Tabs>
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
