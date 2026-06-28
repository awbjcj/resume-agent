import { useCallback, useMemo, useState } from "react";
import { AlertCircleIcon, NetworkIcon, Rows3Icon } from "lucide-react";

import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { BoardSkeleton } from "@/components/skeletons";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  deriveView,
  targetId,
  type Filters as FilterValue,
  type SkillRow,
  type SuggestionTarget,
} from "./aggregate";
import { Filters } from "./Filters";
import { RankedList } from "./RankedList";
import { RefreshClustersButton } from "./RefreshClustersButton";
import { SelectionTray } from "./SelectionTray";
import { SkillMap } from "./SkillMap";
import { SkillModal } from "./SkillModal";
import { useMatchGap, useRefreshClusters } from "./use-match-gap";
import { useSuggestionRuns } from "./use-suggestion-runs";

const DEFAULT_FILTERS: FilterValue = {
  company: null,
  seniority: null,
  gapsOnly: false,
  weighting: "essential",
};

export function MatchGapContainer() {
  const { data, isLoading, isError, refetch } = useMatchGap();
  const { refresh } = useRefreshClusters();
  const [filters, setFilters] = useState<FilterValue>(DEFAULT_FILTERS);
  const [activeView, setActiveView] = useState("map");
  const [selection, setSelection] = useState<SuggestionTarget[]>([]);
  const [openSkill, setOpenSkill] = useState<SkillRow | null>(null);
  const view = useMemo(() => (data ? deriveView(data, filters) : null), [data, filters]);
  const persistedStateOf = useCallback(
    (kind: "skill" | "theme", key: string) => view?.persistedStateOf(kind, key),
    [view],
  );
  const suggestionRuns = useSuggestionRuns(persistedStateOf);
  const selectedIds = useMemo(
    () => new Set(selection.map((target) => targetId(target))),
    [selection],
  );

  const toggleSelection = useCallback((target: SuggestionTarget) => {
    const id = targetId(target);
    setSelection((current) =>
      current.some((candidate) => targetId(candidate) === id)
        ? current.filter((candidate) => targetId(candidate) !== id)
        : [...current, target],
    );
  }, []);
  const removeSelection = useCallback((target: SuggestionTarget) => {
    const id = targetId(target);
    setSelection((current) => current.filter((candidate) => targetId(candidate) !== id));
  }, []);

  if (isLoading) return <BoardSkeleton />;

  if (isError) {
    return (
      <Alert variant="destructive">
        <AlertCircleIcon aria-hidden="true" />
        <AlertTitle>Couldn't load skill demand</AlertTitle>
        <AlertDescription>
          Check the API connection, then try again.
          <Button className="mt-3 block" type="button" variant="outline" onClick={() => void refetch()}>
            Retry
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <>
      <PageHeader
        kicker="Demand intelligence"
        title="Match / Gap"
        sub="See what target roles demand, what your profile already proves, and where focused learning has the most leverage."
      />

      {!data || data.targetTotal === 0 || !view ? (
        <Empty className="min-h-80 border">
          <EmptyHeader>
            <EmptyTitle>No target jobs yet</EmptyTitle>
            <EmptyDescription>
              Shortlist or approve jobs to populate the demand graph.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="space-y-6">
          <section
            aria-label="Dashboard controls"
            className="sticky top-0 z-20 flex flex-wrap items-end justify-between gap-4 border-y bg-background/95 px-4 py-4 backdrop-blur sm:px-5"
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
              ["Filtered jobs", String(view.filteredJobCount)],
              ["Distinct skills", String(view.skills.length)],
              ["Open gaps", String(view.skills.filter((skill) => !skill.covered).length)],
            ]}
          />

          {view.skills.length === 0 ? (
            <Empty className="min-h-72 border">
              <EmptyHeader>
                <EmptyTitle>No skills match these filters</EmptyTitle>
                <EmptyDescription>
                  Clear a filter or include covered skills to restore results.
                </EmptyDescription>
                <Button variant="outline" onClick={() => setFilters(DEFAULT_FILTERS)}>
                  Reset filters
                </Button>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_21rem]">
              <Tabs value={activeView} onValueChange={setActiveView} className="min-w-0">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <TabsList aria-label="Skill demand view">
                    <TabsTrigger value="map">
                      <NetworkIcon data-icon="inline-start" />
                      Map
                    </TabsTrigger>
                    <TabsTrigger value="outline">
                      <Rows3Icon data-icon="inline-start" />
                      Outline
                    </TabsTrigger>
                  </TabsList>
                  <span className="hidden text-xs text-muted-foreground sm:inline">
                    Select any theme or skill to research it.
                  </span>
                </div>
                <TabsContent value="map">
                  <SkillMap
                    themeRows={view.themeRows}
                    stateOf={suggestionRuns.stateOf}
                    selected={selectedIds}
                    onToggleSelect={toggleSelection}
                    onOpenSkill={setOpenSkill}
                  />
                </TabsContent>
                <TabsContent value="outline">
                  <RankedList
                    themeRows={view.themeRows}
                    stateOf={suggestionRuns.stateOf}
                    selected={selectedIds}
                    onToggleSelect={toggleSelection}
                    onOpenSkill={setOpenSkill}
                  />
                </TabsContent>
              </Tabs>

              <SelectionTray
                targets={selection}
                stateOf={suggestionRuns.stateOf}
                onRemove={removeSelection}
                onClear={() => setSelection([])}
                onGenerateAll={(targets) => void suggestionRuns.generateAll(targets)}
                onRetry={(target) => void suggestionRuns.retry(target)}
                generating={suggestionRuns.generating}
                launchError={suggestionRuns.launchError}
              />
            </div>
          )}
        </div>
      )}

      <SkillModal
        skill={openSkill}
        themeLabel={
          openSkill
            ? (view?.themeRows.find((theme) => theme.id === openSkill.themeId)?.label ?? null)
            : null
        }
        state={openSkill ? suggestionRuns.stateOf("skill", openSkill.key) : "none"}
        jobs={openSkill ? (view?.jobsForSkill(openSkill.key) ?? []) : []}
        onClose={() => setOpenSkill(null)}
      />
    </>
  );
}
