import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { SourceConnection } from "./source-connection";

export type Source = {
  id: string;
  kind: string;
  type: "board" | "aggregator";
  displayName: string;
  enabled: boolean;
  pullable: boolean;
  detail: string;
  limit: number | null;
};

export type Preview = {
  ok: boolean;
  url: string;
  kind?: string | null;
  token?: string | null;
  label?: string | null;
  roleCount?: number | null;
  error?: string | null;
};

export function useSources() {
  return useQuery({
    queryKey: ["sources"],
    queryFn: () => unwrap(api.GET("/api/sources")) as Promise<Source[]>,
  });
}

export function previewSource(body: SourceConnection): Promise<Preview> {
  return unwrap(
    api.POST("/api/sources/preview", { body }),
  ) as Promise<Preview>;
}

export function useAddSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SourceConnection) =>
      unwrap(api.POST("/api/sources", { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sources"] }),
  });
}

export function useSetEnabled() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      unwrap(
        api.PATCH("/api/sources/{source_id}", {
          params: { path: { source_id: id } },
          body: { enabled },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sources"] }),
  });
}

export function useSetSourceLimit() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, limit }: { id: string; limit: number | null }) =>
      unwrap(
        api.PATCH("/api/sources/{source_id}", {
          params: { path: { source_id: id } },
          body: { limit },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sources"] }),
  });
}

export function useRemoveSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/api/sources/{source_id}", {
          params: { path: { source_id: id } },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sources"] }),
  });
}
