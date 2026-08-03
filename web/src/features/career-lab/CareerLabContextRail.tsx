import { useEffect, useMemo, useState } from "react";
import type { RefObject } from "react";
import { BriefcaseBusiness, SlidersHorizontal } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import {
  type CareerLabContext,
  type CareerLabJob,
  useCareerLabJobDetail,
  useCareerLabJobs,
  useCareerLabSkills,
} from "./use-career-lab";

type SkillsQuery = Pick<ReturnType<typeof useCareerLabSkills>, "data" | "isPending">;

function jobMatchesSearch(job: CareerLabJob, query: string) {
  if (!query) return true;
  return [job.company, job.title, job.location]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase()
    .includes(query);
}

function uniqueSorted(values: string[]) {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right));
}

export function CareerLabSkillPicker({
  skill,
  setSkill,
  skills,
  selectRef,
  id = "career-skill",
}: {
  skill: string;
  setSkill: (value: string) => void;
  skills: SkillsQuery;
  selectRef?: RefObject<HTMLSelectElement | null>;
  id?: string;
}) {
  const rows = skills.data?.skills ?? [];
  const unavailable = rows.find((row) => row.name === skill && !row.isAvailable);

  return (
    <div className="space-y-2">
      <Label htmlFor={id}>Career skill</Label>
      <select
        id={id}
        aria-label="Career skill"
        ref={selectRef}
        value={skill}
        onChange={(event) => setSkill(event.target.value)}
        className="h-9 w-full rounded-lg border border-input bg-background px-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <option value="">Let Career Lab route it</option>
        {rows.map((row) => (
          <option key={row.name} value={row.name} disabled={!row.isAvailable}>
            {row.name}{row.isAvailable ? "" : " — unavailable"}
          </option>
        ))}
      </select>
      {!skill && rows.length > 0 ? <p className="text-xs leading-5 text-muted-foreground">Ambiguous requests will ask you to choose a skill.</p> : null}
      {unavailable ? <p className="text-xs leading-5 text-destructive">{unavailable.unavailableReason ?? "This skill is unavailable."}</p> : null}
    </div>
  );
}

export function CareerLabContextRail({
  skill,
  setSkill,
  skills,
  goal,
  context,
  setContext,
  skillRef,
}: {
  skill: string;
  setSkill: (value: string) => void;
  skills: SkillsQuery;
  goal: string;
  context: CareerLabContext;
  setContext: (value: CareerLabContext) => void;
  skillRef: RefObject<HTMLSelectElement | null>;
}) {
  const jobs = useCareerLabJobs();
  const jobDetail = useCareerLabJobDetail(context.jobId ?? null);
  const [jobSearch, setJobSearch] = useState("");
  const [jobStatus, setJobStatus] = useState("");
  const [jobSource, setJobSource] = useState("");
  const normalizedSearch = jobSearch.trim().toLocaleLowerCase();
  const jobRows = useMemo(() => jobs.data ?? [], [jobs.data]);
  const searchMatches = useMemo(
    () => jobRows.filter((job) => jobMatchesSearch(job, normalizedSearch)),
    [jobRows, normalizedSearch],
  );
  const statuses = useMemo(
    () => uniqueSorted(searchMatches.filter((job) => !jobSource || job.source === jobSource).map((job) => job.status)),
    [jobSource, searchMatches],
  );
  const sources = useMemo(
    () => uniqueSorted(searchMatches.filter((job) => !jobStatus || job.status === jobStatus).map((job) => job.source)),
    [jobStatus, searchMatches],
  );
  const filteredJobs = useMemo(
    () => searchMatches.filter((job) => (!jobStatus || job.status === jobStatus) && (!jobSource || job.source === jobSource)),
    [jobSource, jobStatus, searchMatches],
  );

  const clearHiddenJob = (search: string, status: string, source: string) => {
    const visibleJobs = jobRows.filter((job) => (
      jobMatchesSearch(job, search)
      && (!status || job.status === status)
      && (!source || job.source === source)
    ));
    if (context.jobId != null && !visibleJobs.some((job) => job.jobId === context.jobId)) {
      setContext({ ...context, jobId: undefined, resumeVersionId: undefined });
    }
  };

  const updateSearch = (value: string) => {
    const nextSearch = value.trim().toLocaleLowerCase();
    const nextMatches = jobRows.filter((job) => jobMatchesSearch(job, nextSearch));
    const nextStatuses = uniqueSorted(nextMatches.filter((job) => !jobSource || job.source === jobSource).map((job) => job.status));
    const nextStatus = nextStatuses.includes(jobStatus) ? jobStatus : "";
    const nextSources = uniqueSorted(nextMatches.filter((job) => !nextStatus || job.status === nextStatus).map((job) => job.source));
    const nextSource = nextSources.includes(jobSource) ? jobSource : "";
    setJobSearch(value);
    if (nextStatus !== jobStatus) setJobStatus(nextStatus);
    if (nextSource !== jobSource) setJobSource(nextSource);
    clearHiddenJob(nextSearch, nextStatus, nextSource);
  };

  const updateStatus = (value: string) => {
    const nextSources = uniqueSorted(searchMatches.filter((job) => !value || job.status === value).map((job) => job.source));
    const nextSource = nextSources.includes(jobSource) ? jobSource : "";
    setJobStatus(value);
    if (nextSource !== jobSource) setJobSource(nextSource);
    clearHiddenJob(normalizedSearch, value, nextSource);
  };

  const updateSource = (value: string) => {
    const nextStatuses = uniqueSorted(searchMatches.filter((job) => !value || job.source === value).map((job) => job.status));
    const nextStatus = nextStatuses.includes(jobStatus) ? jobStatus : "";
    setJobSource(value);
    if (nextStatus !== jobStatus) setJobStatus(nextStatus);
    clearHiddenJob(normalizedSearch, nextStatus, value);
  };

  useEffect(() => {
    if (context.jobId != null && !filteredJobs.some((job) => job.jobId === context.jobId)) {
      setContext({ ...context, jobId: undefined, resumeVersionId: undefined });
    }
  }, [context, filteredJobs, setContext]);

  useEffect(() => {
    const resumeVersions = jobDetail.data?.resumeVersions;
    if (context.resumeVersionId != null && resumeVersions && !resumeVersions.some((version) => version.id === context.resumeVersionId)) {
      setContext({ ...context, resumeVersionId: undefined });
    }
  }, [context, jobDetail.data?.resumeVersions, setContext]);

  const updateContext = (changes: Partial<CareerLabContext>) => setContext({ ...context, ...changes });
  const updateOfferIds = (value: string) => {
    const offerApplicationIds = value
      .split(",")
      .map((part) => Number(part.trim()))
      .filter((id) => Number.isInteger(id) && id > 0)
      .slice(0, 10);
    updateContext({ offerApplicationIds });
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <SlidersHorizontal className="size-4 text-primary" aria-hidden="true" />
            Session setup
          </CardTitle>
          <CardDescription>Set the drafting mode for your next response and keep the session focus visible.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <CareerLabSkillPicker skill={skill} setSkill={setSkill} skills={skills} selectRef={skillRef} />
          <div className="space-y-1.5 border-t pt-4">
            <p className="text-sm font-medium">Session focus</p>
            <p className="text-sm leading-6 text-muted-foreground">{goal || "Your opening request sets this session’s focus."}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <BriefcaseBusiness className="size-4 text-primary" aria-hidden="true" />
            Reference context
          </CardTitle>
          <CardDescription>Add only the material that should shape the next draft.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <label className="flex items-start gap-3 rounded-lg border bg-muted/20 p-3 text-sm">
            <Checkbox
              checked={context.profileSnapshot === "current"}
              onCheckedChange={(checked) => updateContext({ profileSnapshot: checked ? "current" : undefined })}
              aria-label="Include current profile snapshot"
            />
            <span>
              <span className="block font-medium">Include current profile</span>
              <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">Use the current profile as a bounded draft reference.</span>
            </span>
          </label>

          <details className="rounded-lg border bg-muted/20 p-3">
            <summary className="cursor-pointer text-sm font-medium">Job and resume context</summary>
            <div className="mt-4 space-y-4">
              <div className="grid gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="career-job-search">Find a job</Label>
                  <Input
                    id="career-job-search"
                    value={jobSearch}
                    onChange={(event) => updateSearch(event.target.value)}
                    placeholder="Company, role, or location"
                    className="h-9"
                  />
                </div>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                  <div className="space-y-1.5">
                    <Label htmlFor="career-job-status">Job status</Label>
                    <select id="career-job-status" value={jobStatus} onChange={(event) => updateStatus(event.target.value)} className="h-9 w-full rounded-lg border border-input bg-background px-2 text-sm">
                      <option value="">All statuses</option>
                      {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="career-job-source">Job source</Label>
                    <select id="career-job-source" value={jobSource} onChange={(event) => updateSource(event.target.value)} className="h-9 w-full rounded-lg border border-input bg-background px-2 text-sm">
                      <option value="">All sources</option>
                      {sources.map((source) => <option key={source} value={source}>{source}</option>)}
                    </select>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground" aria-live="polite">{filteredJobs.length} of {jobRows.length} jobs match these filters.</p>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="career-job">Job</Label>
                <select
                  id="career-job"
                  value={context.jobId ?? ""}
                  onChange={(event) => updateContext({ jobId: event.target.value ? Number(event.target.value) : undefined, resumeVersionId: undefined })}
                  className="h-9 w-full rounded-lg border border-input bg-background px-2 text-sm"
                >
                  <option value="">No job selected</option>
                  {filteredJobs.map((job) => <option key={job.jobId} value={job.jobId}>{[job.company, job.title].filter(Boolean).join(" · ") || `Job ${job.jobId}`} — {job.status}</option>)}
                </select>
                {jobs.isPending ? <p className="text-xs text-muted-foreground">Loading jobs…</p> : null}
                {jobs.isError ? <p className="text-xs text-destructive">Jobs could not be loaded.</p> : null}
                {!jobs.isPending && !jobs.isError && filteredJobs.length === 0 ? <p className="text-xs text-muted-foreground">No jobs match these filters.</p> : null}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="career-resume-version">Resume version</Label>
                <select
                  id="career-resume-version"
                  disabled={!context.jobId || jobDetail.isPending}
                  value={context.resumeVersionId ?? ""}
                  onChange={(event) => updateContext({ resumeVersionId: event.target.value ? Number(event.target.value) : undefined })}
                  className="h-9 w-full rounded-lg border border-input bg-background px-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <option value="">{context.jobId ? "No resume version" : "Choose a job first"}</option>
                  {(jobDetail.data?.resumeVersions ?? []).map((version) => <option key={version.id} value={version.id}>Round {version.round} · {version.origin}</option>)}
                </select>
                {context.jobId && jobDetail.data?.resumeVersions.length === 0 ? <p className="text-xs text-muted-foreground">This job has no tailored resume versions yet.</p> : null}
              </div>
            </div>
          </details>

          <details className="rounded-lg border bg-muted/20 p-3">
            <summary className="cursor-pointer text-sm font-medium">Offer comparison references</summary>
            <div className="mt-4 space-y-1.5">
              <Label htmlFor="career-offer-ids">Offer application ids</Label>
              <input
                id="career-offer-ids"
                type="text"
                inputMode="numeric"
                placeholder="e.g. 12, 18"
                value={(context.offerApplicationIds ?? []).join(", ")}
                onChange={(event) => updateOfferIds(event.target.value)}
                className="h-9 w-full rounded-lg border border-input bg-background px-2 text-sm"
              />
              <p className="text-xs leading-5 text-muted-foreground">Up to 10 offer-status application ids.</p>
            </div>
          </details>
        </CardContent>
      </Card>
    </div>
  );
}
