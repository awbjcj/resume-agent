import { useQuery } from "@tanstack/react-query";

import { useLaunchRun } from "@/features/runs/use-launch-run";
import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useRunStore } from "@/lib/runs/store";

export type SuggestionEnvelope = components["schemas"]["SuggestionEnvelope"];
export type SuggestionKind = "skill" | "domain";

export function suggestionQueryKey(kind: SuggestionKind, key: string): string {
  return `suggestion:${kind}:${key}`;
}

export function useSuggestion(
  kind: SuggestionKind,
  key: string | null,
  enabled: boolean,
) {
  const queryKey = suggestionQueryKey(kind, key ?? "");
  return useQuery({
    queryKey: [queryKey],
    enabled: enabled && Boolean(key),
    queryFn: (): Promise<SuggestionEnvelope> =>
      unwrap(
        api.GET("/api/suggestions", {
          params: { query: { kind, key: key ?? "" } },
        }),
      ) as Promise<SuggestionEnvelope>,
  });
}

export function useGenerateSuggestion() {
  const { launch } = useLaunchRun();
  const generating = useRunStore((state) =>
    Object.values(state.runs).some(
      (run) =>
        run.kind === "suggestion" &&
        (run.status === "running" || run.status === "cancelling"),
    ),
  );
  const generate = (kind: SuggestionKind, key: string) =>
    launch(
      "suggestion",
      () =>
        unwrap(
          api.POST("/api/suggestions/generate", {
            body: { kind, key },
          }),
        ),
      [suggestionQueryKey(kind, key)],
    );

  return { generate, generating };
}
