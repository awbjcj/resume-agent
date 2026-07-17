import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ProfileMatrix = components["schemas"]["MatrixOut"];

export function useMatrix() {
  return useQuery({
    queryKey: ["profile-matrix"],
    queryFn: () =>
      unwrap(api.GET("/api/profile/matrix", {} as never)) as Promise<ProfileMatrix>,
  });
}

export function useSetSkillGroup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: { key: string; group: string }) =>
      unwrap(
        api.PUT("/api/profile/skills/{key}/group", {
          params: { path: { key: variables.key } },
          body: { group: variables.group },
        }),
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["profile-matrix"] });
      toast.success("Skill group updated");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useClearSkillGroup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (key: string) =>
      unwrap(
        api.DELETE("/api/profile/skills/{key}/group", {
          params: { path: { key } },
        }),
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["profile-matrix"] });
      toast.success("Reverted to automatic grouping");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}
