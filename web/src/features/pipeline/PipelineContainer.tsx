import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { useBulkRun } from "@/features/runs/use-bulk-run";
import { BoardSkeleton } from "@/components/skeletons";
import { EmptyState } from "@/components/EmptyState";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { JobModal } from "@/components/JobModal";
import { PipelineCard } from "./PipelineCard";
import { usePipeline, type PipelineItem } from "./use-pipeline";

const STAGE_ORDER = ["raw", "shortlisted", "approved", "tailored", "rendered", "rejected"];

export function PipelineContainer() {
  const { data: rows, isLoading } = usePipeline();
  const [q, setQ] = useState("");
  const [minFit, setMinFit] = useState(0);
  const [params, setParams] = useSearchParams();
  const bulk = useBulkRun();

  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (rows ?? []).filter(
      (r) =>
        (r.fitScore == null || r.fitScore >= minFit) &&
        (!needle || `${r.company ?? ""} ${r.title ?? ""}`.toLowerCase().includes(needle)),
    );
  }, [rows, q, minFit]);

  if (isLoading) return <BoardSkeleton />;

  const byStage = new Map<string, PipelineItem[]>();
  for (const r of visible) byStage.set(r.status, [...(byStage.get(r.status) ?? []), r]);
  const stages = [
    ...STAGE_ORDER.filter((s) => byStage.has(s)),
    ...[...byStage.keys()].filter((s) => !STAGE_ORDER.includes(s)),
  ];
  const rendered = byStage.get("rendered")?.length ?? 0;
  const openId = params.get("job");

  return (
    <>
      <PageHeader
        kicker="Mission control"
        title="Pipeline / Board"
        sub="Every job by pipeline stage, with its tailored PDF, review critiques, and your application status."
      />
      <div className="mb-5 flex flex-wrap gap-2 rounded-lg border bg-card p-3 shadow-[0_1px_2px_rgba(24,32,38,0.04)]">
        <Button variant="outline" size="sm" onClick={bulk.tailorApproved}>
          Tailor approved
        </Button>
        <Button variant="outline" size="sm" onClick={bulk.coverLettersApproved}>
          Cover letters (approved)
        </Button>
      </div>
      <MetricRow
        items={[
          ["In view", String(visible.length)],
          ["Rendered", String(rendered)],
          ["Stages active", String(byStage.size)],
        ]}
      />
      <div className="mb-7 grid grid-cols-1 gap-4 rounded-lg border bg-card p-5 shadow-[0_1px_2px_rgba(24,32,38,0.04)] sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="pipe-q" className="text-xs font-semibold uppercase tracking-[0.14em]">
            Company/title
          </Label>
          <Input
            id="pipe-q"
            className="h-10 bg-card"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="pipe-fit" className="text-xs font-semibold uppercase tracking-[0.14em]">
            Min fit
          </Label>
          <Slider
            id="pipe-fit"
            aria-label="Min fit"
            min={0}
            max={100}
            value={[minFit]}
            onValueChange={(v) => setMinFit((v as number[])[0])}
          />
        </div>
      </div>
      {!rows?.length ? (
        <EmptyState
          title="No jobs in the pipeline"
          body="Start by adding a job or running a pull."
        />
      ) : (
        stages.map((stage) => (
          <section key={stage} className="mb-8">
            <div className="mb-3 flex items-center justify-between border-b pb-2">
              <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                {stage}
              </h2>
              <span className="rounded-full bg-secondary px-2.5 py-1 text-xs font-semibold">
                {byStage.get(stage)!.length}
              </span>
            </div>
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3">
              {byStage.get(stage)!.map((row) => (
                <PipelineCard
                  key={row.jobId}
                  row={row}
                  onOpen={() =>
                    setParams(
                      (p) => {
                        p.set("job", String(row.jobId));
                        return p;
                      },
                      { replace: true },
                    )
                  }
                />
              ))}
            </div>
          </section>
        ))
      )}
      {openId && (
        <JobModal
          jobId={Number(openId)}
          onClose={() =>
            setParams(
              (p) => {
                p.delete("job");
                return p;
              },
              { replace: true },
            )
          }
        />
      )}
    </>
  );
}
