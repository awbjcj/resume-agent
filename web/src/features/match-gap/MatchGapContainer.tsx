import { useMemo, useState } from "react";
import { ArrowUpRight, Layers3 } from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { BoardSkeleton } from "@/components/skeletons";
import { Button } from "@/components/ui/button";
import { deriveView, type Filters as FilterValue } from "./aggregate";
import { Filters } from "./Filters";
import { RankedList } from "./RankedList";
import { RefreshClustersButton } from "./RefreshClustersButton";
import { SkillDrawer } from "./SkillDrawer";
import { StatTables } from "./StatTables";
import { useMatchGap, useRefreshClusters } from "./use-match-gap";
import { WordCloud } from "./WordCloud";

const DEFAULT_FILTERS: FilterValue = {
  company: null,
  seniority: null,
  gapsOnly: false,
  weighting: "essential",
};

type DrawerSelection =
  | { kind: "skill"; key: string; label: string }
  | { kind: "theme"; key: string; label: string }
  | null;

export function MatchGapContainer() {
  const { data, isLoading, isError, refetch } = useMatchGap();
  const { refresh } = useRefreshClusters();
  const [filters, setFilters] = useState<FilterValue>(DEFAULT_FILTERS);
  const [selected, setSelected] = useState<DrawerSelection>(null);
  const view = useMemo(() => (data ? deriveView(data, filters) : null), [data, filters]);

  if (isLoading) return <BoardSkeleton />;

  if (isError) {
    return (
      <div role="alert" className="space-y-3">
        <EmptyState
          title="Couldn't load skill demand"
          body="The dashboard request failed. Retry after checking the API connection."
        />
        <Button type="button" variant="outline" onClick={() => void refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  const drawerJobs = selected
    ? selected.kind === "skill"
      ? (view?.jobsForSkill(selected.key) ?? [])
      : (view?.jobsForTheme(selected.key) ?? [])
    : [];

  return (
    <>
      <PageHeader
        kicker="Closed loop"
        title="Match / Gap"
        sub="A weighted view of what target roles demand, what your profile already proves, and where focused learning has the most leverage."
      />

      {!data || data.targetTotal === 0 || !view ? (
        <EmptyState
          title="No target jobs yet"
          body="Shortlist or approve jobs to populate the demand graph."
        />
      ) : (
        <div className="space-y-7">
          <section
            aria-label="Dashboard controls"
            className="flex flex-wrap items-end justify-between gap-4 border-y bg-card/80 px-5 py-4"
          >
            <Filters
              value={filters}
              onChange={setFilters}
              companies={view.companies}
              seniorities={view.seniorities}
            />
            <RefreshClustersButton stale={data.clustersStale} onRefresh={refresh} />
          </section>

          <MetricRow
            items={[
              ["Target jobs", String(data.targetTotal)],
              ["Distinct skills", String(view.skills.length)],
              ["Open gaps", String(view.skills.filter((skill) => !skill.covered).length)],
            ]}
          />

          {view.skills.length === 0 ? (
            <EmptyState
              title="No skills match these filters"
              body="Clear a filter or include covered skills to restore results."
            />
          ) : (
            <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(22rem,0.85fr)]">
              <RankedList
                skills={view.skills}
                onSelect={(skill) => setSelected({ kind: "skill", key: skill, label: skill })}
              />
              <WordCloud
                skills={view.skills}
                onSelect={(skill) => setSelected({ kind: "skill", key: skill, label: skill })}
              />
            </div>
          )}

          {view.themes.length > 0 && (
            <section aria-labelledby="theme-paths-title" className="border-y bg-card">
              <div className="flex items-center gap-3 border-b px-5 py-4">
                <Layers3 className="size-4 text-primary" />
                <div>
                  <h2 id="theme-paths-title" className="text-sm font-semibold">
                    Theme learning paths
                  </h2>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Inspect the roles and skills grouped into each capability area.
                  </p>
                </div>
              </div>
              <div className="divide-y">
                {view.themes.map((theme) => (
                  <button
                    key={theme.id}
                    type="button"
                    aria-label={`Open ${theme.label} learning path`}
                    onClick={() =>
                      setSelected({ kind: "theme", key: theme.id, label: theme.label })
                    }
                    className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-4 px-5 py-3 text-left transition-colors hover:bg-accent/55 motion-reduce:transition-none"
                  >
                    <span>
                      <span className="block text-sm font-medium">{theme.label}</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {theme.skills.length} {theme.skills.length === 1 ? "skill" : "skills"}
                      </span>
                    </span>
                    <span className="font-mono text-sm tabular-nums">{theme.score}</span>
                    <ArrowUpRight className="size-4 text-muted-foreground" />
                  </button>
                ))}
              </div>
            </section>
          )}

          <StatTables byCompany={view.byCompany} byPosition={view.byPosition} />
        </div>
      )}

      <SkillDrawer
        kind={selected?.kind ?? "skill"}
        targetKey={selected?.key ?? null}
        label={selected?.label ?? null}
        jobs={drawerJobs}
        onClose={() => setSelected(null)}
      />
    </>
  );
}
