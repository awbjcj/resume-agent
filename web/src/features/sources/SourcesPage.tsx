import { useMemo, useState } from "react";
import { Play, Trash2 } from "lucide-react";

import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { launchers, useLaunchRun } from "@/features/runs/use-launch-run";
import { useRunStore, type PullRunResult } from "@/lib/runs/store";
import { AddSourceDialog } from "./AddSourceDialog";
import { useRemoveSource, useSetEnabled, useSources, type Source } from "./use-sources";

function SourceRow({
  source,
  checked,
  onToggleCheck,
}: {
  source: Source;
  checked: boolean;
  onToggleCheck: (id: string) => void;
}) {
  const setEnabled = useSetEnabled();
  const removeSource = useRemoveSource();
  const { launch } = useLaunchRun();
  const pullDisabled = !source.pullable;

  return (
    <li
      className="grid min-h-14 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-b py-3 last:border-b-0 lg:grid-cols-[auto_minmax(0,1fr)_auto_auto_auto_auto]"
      aria-disabled={pullDisabled}
    >
      <Checkbox
        checked={checked}
        disabled={pullDisabled}
        aria-label={`Select ${source.displayName}`}
        onCheckedChange={() => onToggleCheck(source.id)}
      />
      <div className="min-w-0">
        <div className="truncate text-sm font-medium">{source.displayName}</div>
        <div className="mt-1 truncate text-xs text-muted-foreground">
          {source.detail}
        </div>
      </div>
      <Badge variant={source.pullable ? "outline" : "secondary"}>{source.kind}</Badge>
      <Switch
        size="sm"
        aria-label={`Enable ${source.displayName}`}
        checked={source.enabled}
        onCheckedChange={(enabled) => setEnabled.mutate({ id: source.id, enabled })}
      />
      <Button
        size="sm"
        variant="secondary"
        aria-label={`Pull ${source.displayName}`}
        disabled={pullDisabled}
        onClick={() =>
          launch(
            "pull",
            () => launchers.pullSources([source.id]),
            ["shortlist", "pipeline", "triage", "sources"],
          )
        }
      >
        <Play className="size-3.5" aria-hidden="true" />
        Pull
      </Button>
      {source.type === "board" ? (
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label={`Remove ${source.displayName}`}
          onClick={() => removeSource.mutate(source.id)}
        >
          <Trash2 className="size-4" aria-hidden="true" />
        </Button>
      ) : (
        <span className="hidden size-9 lg:block" aria-hidden="true" />
      )}
    </li>
  );
}

function LatestPullResult({ sources }: { sources: Source[] }) {
  const runsMap = useRunStore((state) => state.runs);
  const latestPull = Object.values(runsMap)
    .reverse()
    .find((run) => run.kind === "pull" && run.result);
  const result = latestPull?.result as PullRunResult | undefined;
  if (!result) return null;

  const labels = new Map(sources.map((source) => [source.id, source.displayName]));
  const ids = new Set([
    ...Object.keys(result.totals ?? {}),
    ...Object.keys(result.upgraded ?? {}),
    ...Object.keys(result.skipped ?? {}),
    ...Object.keys(result.failures ?? {}),
  ]);

  return (
    <section aria-labelledby="sources-results" className="rounded-lg border bg-card p-4">
      <h2
        id="sources-results"
        className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground"
      >
        Latest pull result
      </h2>
      <ul className="mt-3 divide-y">
        {[...ids].map((id) => {
          const failed = Object.keys(result.failures?.[id] ?? {}).length;
          return (
            <li
              key={id}
              className="grid gap-2 py-2 text-sm md:grid-cols-[minmax(0,1fr)_repeat(4,auto)] md:items-center"
            >
              <span className="truncate font-medium">{labels.get(id) ?? id}</span>
              <span className="tabular-nums">+{result.totals?.[id] ?? 0} added</span>
              <span className="tabular-nums">{result.upgraded?.[id] ?? 0} upd</span>
              <span className="tabular-nums">{result.skipped?.[id] ?? 0} skip</span>
              <span className={failed ? "text-destructive" : "text-muted-foreground"}>
                {failed ? `${failed} failed` : "0 failed"}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function SourceSection({
  title,
  sources,
  selected,
  onToggleCheck,
  empty,
}: {
  title: string;
  sources: Source[];
  selected: Set<string>;
  onToggleCheck: (id: string) => void;
  empty: string;
}) {
  return (
    <section className="rounded-lg border bg-card px-4">
      <div className="flex min-h-12 items-center border-b">
        <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          {title}
        </h2>
      </div>
      {sources.length === 0 ? (
        <p className="py-5 text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul role="list">
          {sources.map((source) => (
            <SourceRow
              key={source.id}
              source={source}
              checked={selected.has(source.id)}
              onToggleCheck={onToggleCheck}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

export function SourcesManager() {
  const { data = [], isLoading } = useSources();
  const { launch } = useLaunchRun();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const boards = useMemo(() => data.filter((source) => source.type === "board"), [data]);
  const aggregators = useMemo(
    () => data.filter((source) => source.type === "aggregator"),
    [data],
  );

  const toggleSelected = (id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center gap-2">
        <AddSourceDialog />
        <Button
          variant="outline"
          size="sm"
          disabled={selected.size === 0}
          onClick={() =>
            launch(
              "pull",
              () => launchers.pullSources([...selected]),
              ["shortlist", "pipeline", "triage", "sources"],
            )
          }
        >
          Pull selected ({selected.size})
        </Button>
        <Button
          size="sm"
          onClick={() =>
            launch(
              "pull",
              () => launchers.pullSources(null),
              ["shortlist", "pipeline", "triage", "sources"],
            )
          }
        >
          Pull all
        </Button>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading sources...</p>
      ) : (
        <div className="grid gap-5">
          <SourceSection
            title="Boards & careers pages"
            sources={boards}
            selected={selected}
            onToggleCheck={toggleSelected}
            empty="No recurring boards yet."
          />
          <SourceSection
            title="Aggregators"
            sources={aggregators}
            selected={selected}
            onToggleCheck={toggleSelected}
            empty="No aggregators configured."
          />
          <LatestPullResult sources={data} />
        </div>
      )}
    </div>
  );
}

export function SourcesPage() {
  return (
    <div>
      <PageHeader
        kicker="Sources"
        title="Recurring job sources"
        sub="Manage the boards, careers pages, and feeds that supply the pull pipeline."
      />
      <SourcesManager />
    </div>
  );
}
