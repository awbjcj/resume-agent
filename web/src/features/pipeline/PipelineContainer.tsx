import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { BoardSkeleton } from "@/components/skeletons";
import { EmptyState } from "@/components/EmptyState";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { JobDrawer } from "@/components/JobDrawer";
import { PipelineCard } from "./PipelineCard";
import { usePipeline, type PipelineItem } from "./use-pipeline";

const STAGE_ORDER = ["raw", "shortlisted", "approved", "tailored", "rendered", "rejected"];

export function PipelineContainer() {
  const { data: rows, isLoading } = usePipeline();
  const [q, setQ] = useState("");
  const [minFit, setMinFit] = useState(0);
  const [params, setParams] = useSearchParams();

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
      <MetricRow
        items={[
          ["In view", String(visible.length)],
          ["Rendered", String(rendered)],
          ["Stages active", String(byStage.size)],
        ]}
      />
      <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="pipe-q">Company/title</Label>
          <Input id="pipe-q" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="pipe-fit">Min fit</Label>
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
          <section key={stage} className="mb-6">
            <h2 className="mb-2 font-mono text-xs uppercase tracking-widest text-muted-foreground">
              {stage} · {byStage.get(stage)!.length}
            </h2>
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
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
        <JobDrawer
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
