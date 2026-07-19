import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { api, fetchAllPages, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

import { InterviewSetupDialog } from "./InterviewSetupDialog";
import { useInterviewSessions } from "./use-interview";

type PipelineItem = components["schemas"]["PipelineItem"];
type JobDetail = components["schemas"]["JobDetail"];

function useInterviewableJobs(enabled: boolean) {
  return useQuery({
    queryKey: ["interviewable-jobs"], enabled,
    queryFn: async () => (await Promise.all((["tailored", "rendered"] as const).map((status) => fetchAllPages<PipelineItem>((page) => api.GET("/api/pipeline", { params: { query: { status, sortBy: "stage", page, pageSize: 200 } } }))))).flat(),
  });
}

export function NewInterviewDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [jobId, setJobId] = useState<number | null>(null);
  const jobs = useInterviewableJobs(open);
  const sessions = useInterviewSessions();
  const activeJobIds = useMemo(() => new Set((sessions.data?.sessions ?? []).filter((session) => session.status === "active").map((session) => session.jobId)), [sessions.data]);
  const candidates = (jobs.data ?? []).filter((job) => !activeJobIds.has(job.jobId));
  const detail = useQuery({
    queryKey: ["job-detail", jobId], enabled: jobId != null,
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: jobId as number } } })) as Promise<JobDetail>,
  });
  const close = (next: boolean) => { if (!next) setJobId(null); onOpenChange(next); };

  if (jobId != null && detail.data?.resumeVersions.length) return <InterviewSetupDialog jobId={jobId} versions={detail.data.resumeVersions} open={open} onOpenChange={close} />;

  return <Dialog open={open} onOpenChange={close}><DialogContent className="sm:max-w-md"><DialogHeader><DialogTitle>New mock interview</DialogTitle><DialogDescription>Choose a tailored job. Jobs with an interview in progress are hidden so you can resume them from the sessions list.</DialogDescription></DialogHeader>
    {jobs.isPending || sessions.isPending ? <div className="flex items-center gap-2 text-sm text-muted-foreground"><Spinner />Loading jobs…</div> : null}
    {jobs.isError || sessions.isError ? <Alert variant="destructive"><AlertTitle>Could not load jobs</AlertTitle><AlertDescription className="flex items-center justify-between gap-3"><span>Check the connection and try again.</span><Button size="sm" variant="outline" onClick={() => { void jobs.refetch(); void sessions.refetch(); }}>Try again</Button></AlertDescription></Alert> : null}
    {!jobs.isPending && !sessions.isPending && !jobs.isError && !sessions.isError && candidates.length === 0 ? <p className="text-sm text-muted-foreground">No interviewable jobs yet — tailor a resume first.</p> : null}
    {candidates.length ? <Field><FieldLabel htmlFor="new-interview-job">Job</FieldLabel><Select items={candidates.map((job) => ({ label: [job.company, job.title].filter(Boolean).join(" · "), value: String(job.jobId) }))} value={jobId != null ? String(jobId) : null} onValueChange={(value) => setJobId(value ? Number(value) : null)}><SelectTrigger id="new-interview-job" className="w-full"><SelectValue placeholder="Choose a job" /></SelectTrigger><SelectContent><SelectGroup>{candidates.map((job) => <SelectItem key={job.jobId} value={String(job.jobId)}>{[job.company, job.title].filter(Boolean).join(" · ")}</SelectItem>)}</SelectGroup></SelectContent></Select></Field> : null}
    {jobId != null && detail.isPending ? <div className="flex items-center gap-2 text-sm text-muted-foreground"><Spinner />Loading resume versions…</div> : null}
    {jobId != null && detail.isError ? <Alert variant="destructive"><AlertTitle>Could not load resume versions</AlertTitle><AlertDescription><Button size="sm" variant="outline" onClick={() => void detail.refetch()}>Try again</Button></AlertDescription></Alert> : null}
    {jobId != null && detail.data && detail.data.resumeVersions.length === 0 ? <p className="text-sm text-muted-foreground">This job has no tailored resume version yet.</p> : null}
  </DialogContent></Dialog>;
}
