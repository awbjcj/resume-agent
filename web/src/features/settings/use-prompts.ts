import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { paths } from "@/lib/api/schema";

export type AgentPromptItem =
  paths["/api/agents/prompts"]["get"]["responses"][200]["content"]["application/json"][number];

const PROMPTS_KEY = ["agent-prompts"] as const;

export function usePrompts() {
  return useQuery({
    queryKey: PROMPTS_KEY,
    queryFn: () =>
      unwrap(api.GET("/api/agents/prompts")) as Promise<AgentPromptItem[]>,
  });
}

export function useSaveGuidance() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ key, guidance }: { key: string; guidance: string }) =>
      unwrap(
        api.PUT("/api/agents/prompts/{key}", {
          params: { path: { key } },
          body: { guidance },
        }),
      ) as Promise<AgentPromptItem>,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROMPTS_KEY });
      toast.success("Guidance saved");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}
