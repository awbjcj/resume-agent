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
  defaultTargetStatuses,
  deriveView,
  hasActiveScopeFilters,
  targetId,
  visibleUnassignedSkillKeys,
  type Filters as FilterValue,
  type SkillRow,
  type SuggestionTarget,
} from "./aggregate";
import { Filters } from "./Filters";
import { RankedList } from "./RankedList";
import { RefreshClustersButton } from "./RefreshClustersButton";
import { RetiredSkills } from "./RetiredSkills";
import { SelectionTray } from "./SelectionTray";
import { SkillMap } from "./SkillMap";
import { SkillModal } from "./SkillModal";
import {
  useMaintainTaxonomy,
  useMatchGap,
  useRefreshClusters,
  useUndoTaxonomyMaintenance,
} from "./use-match-gap";
import { useSuggestionRuns } from "./use-suggestion-runs";

const DEFAULT_FILTERS: FilterValue = {
  q: "",
  company: null,
  seniority: null,
  statuses: defaultTargetStatuses(),
  gapsOnly: false,
  weighting: "essential",
};

export function MatchGapContainer() {
  const { data, isLoading, isError, refetch } = useMatchGap();
  const { refresh } = useRefreshClusters();
  const { maintain } = useMaintainTaxonomy();
  const { undo } = useUndoTaxonomyMaintenance();
  const [filters, setFilters] = useState<FilterValue>(DEFAULT_FILTERS);
  const [activeView, setActiveView] = useState("map");
  const [selection, setSelection] = useState<SuggestionTarget[]>([]);
  const [openSkill, setOpenSkill] = useState<SkillRow | null>(null);
  const view = useMemo(() => (data ? deriveView(data, filters) : null), [data, filters]);
  const visibleUnassignedKeys = useMemo(
    () => (view ? visibleUnassignedSkillKeys(view) : []),
    [view],
  );
  const scopedRegroup = hasActiveScopeFilters(filters);
  const regroup = useCallback(
    () => refresh(scopedRegroup ? visibleUnassignedKeys : undefined),
    [refresh, scopedRegroup, visibleUnassignedKeys],
  );
  // Taxonomy edits target the whole constellation, so their pickers must not be
  // narrowed by the active filters that shape the *displayed* map/outline.
  const editView = useMemo(
    () => (data ? deriveView(data, DEFAULT_FILTERS) : null),
    [data],
  );
  const persistedStateOf = useCallback(
    (kind: "skill" | "domain", key: string) => view?.persistedStateOf(kind, key),
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
            className="sticky top-2 z-20 flex flex-wrap items-center justify-between gap-4 rounded-lg border bg-card/95 p-4 backdrop-blur"
          >
            <Filters
              value={filters}
              onChange={setFilters}
              companies={view.companies}
              seniorities={view.seniorities}
              statusCounts={view.statusCounts}
            />
            <RefreshClustersButton
              unassignedCount={visibleUnassignedKeys.length}
              onRegroup={regroup}
              onMaintain={maintain}
              canUndo={data.taxonomyUndoAvailable}
              onUndo={undo}
              maintenanceDue={data.taxonomyMaintenanceDue}
              trailing={<RetiredSkills skills={data.retiredSkills ?? []} />}
            />
          </section>

          <MetricRow
            items={[
              ["Filtered jobs", String(view.filteredJobCount)],
              ["Distinct skills", String(view.skills.length)],
              ["Open gaps", String(view.skills.filter((skill) => skill.coverage === "gap").length)],
              ["Adjacent", String(view.skills.filter((skill) => skill.coverage === "adjacent").length)],
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
            <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_23rem]">
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
                    Select any domain or skill to research it.
                  </span>
                </div>
                <TabsContent value="map">
                  <SkillMap
                    categoryRows={view.categoryRows}
                    editCategoryRows={editView?.categoryRows ?? view.categoryRows}
                    categories={data.categories}
                    stateOf={suggestionRuns.stateOf}
                    selected={selectedIds}
                    onToggleSelect={toggleSelection}
                    onOpenSkill={setOpenSkill}
                  />
                </TabsContent>
                <TabsContent value="outline">
                  <RankedList
                    domainRows={view.domainRows}
                    categoryRows={view.categoryRows}
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
        domainLabel={
          openSkill
            ? (view?.domainRows.find((domain) => domain.id === openSkill.domainId)?.label ?? null)
            : null
        }
        state={openSkill ? suggestionRuns.stateOf("skill", openSkill.key) : "none"}
        jobs={openSkill ? (view?.jobsForSkill(openSkill.key) ?? []) : []}
        onClose={() => setOpenSkill(null)}
      />
    </>
  );
}
