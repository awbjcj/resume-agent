import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { watchRun } from "@/lib/runs/sse";
import { useRunStore } from "@/lib/runs/store";
import {
  targetId,
  type SuggestionState,
  type SuggestionTarget,
} from "./aggregate";
import {
  effectiveSuggestionState,
  useSuggestionRunRegistry,
} from "./suggestion-run-registry";

type BatchResult =
  | { outcome: "accepted"; kind: "skill" | "domain"; key: string; runId: string }
  | { outcome: "not_found"; kind: "skill" | "domain"; key: string };

export function useSuggestionRuns(
  persistedStateOf: (
    kind: "skill" | "domain",
    key: string,
  ) => "ready" | "stale" | undefined,
) {
  const queryClient = useQueryClient();
  const [generating, setGenerating] = useState(false);
  const entries = useSuggestionRunRegistry((state) => state.entries);
  const launchError = useSuggestionRunRegistry((state) => state.launchError);
  const runs = useRunStore((state) => state.runs);

  const generateAll = useCallback(
    async (targets: SuggestionTarget[]) => {
      if (targets.length === 0) return;
      const registry = useSuggestionRunRegistry.getState();
      registry.setLaunchError(null);
      setGenerating(true);
      try {
        const response = (await unwrap(
          api.POST("/api/suggestion-runs", {
            body: { targets: targets.map(({ kind, key }) => ({ kind, key })) },
          }),
        )) as { results: BatchResult[] };
        const labels = new Map(targets.map((target) => [targetId(target), target.label]));

        for (const result of response.results) {
          const target: SuggestionTarget = {
            kind: result.kind,
            key: result.key,
            label: labels.get(targetId(result)) ?? result.key,
          };
          if (result.outcome === "not_found") {
            registry.notFound(target);
            continue;
          }

          registry.register(target, result.runId);
          useRunStore.getState().upsert({
            runId: result.runId,
            kind: "suggestion",
            status: "queued",
            percent: 0,
            phase: "Queued",
            current: 0,
            total: 0,
            etaText: null,
            subject: { kind: target.kind, key: target.key },
          });
          watchRun(result.runId, "suggestion", (run) => {
            if (run.status === "failed") {
              registry.fail(target, run.error);
              return;
            }
            if (run.status === "cancelled") {
              registry.cancel(target);
              return;
            }
            registry.syncing(target);
            void queryClient
              .invalidateQueries(
                { queryKey: ["match-gap"] },
                { throwOnError: true },
              )
              .then(() => registry.clear(target))
              .catch((error: unknown) =>
                registry.fail(
                  target,
                  error instanceof Error
                    ? error.message
                    : "The refreshed dashboard could not be loaded.",
                ),
              );
          });
        }
      } catch (error) {
        registry.setLaunchError(
          error instanceof Error ? error.message : "The suggestion runs could not be started.",
        );
      } finally {
        setGenerating(false);
      }
    },
    [queryClient],
  );

  const stateOf = useCallback(
    (kind: "skill" | "domain", key: string): SuggestionState => {
      const entry = entries[targetId({ kind, key })];
      const live = entry?.runId ? runs[entry.runId]?.status : undefined;
      return effectiveSuggestionState(persistedStateOf(kind, key), entry, live);
    },
    [entries, persistedStateOf, runs],
  );

  return {
    generateAll,
    retry: (target: SuggestionTarget) => generateAll([target]),
    generating,
    launchError,
    stateOf,
  };
}
