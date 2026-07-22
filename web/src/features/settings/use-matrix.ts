import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ProfileMatrix = components["schemas"]["MatrixOut"];
export type SuppressedSkill = components["schemas"]["SuppressedSkillOut"];

/** Every surface where a skill's presence or coverage is displayed. */
function invalidateMatrixSurfaces(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["profile-matrix"] });
  qc.invalidateQueries({ queryKey: ["suppressed-skills"] });
  qc.invalidateQueries({ queryKey: ["profile-skills"] });
  qc.invalidateQueries({ queryKey: ["job"] });
  for (const k of ["shortlist", "pipeline", "triage"]) {
    qc.invalidateQueries({ queryKey: [k] });
  }
}

export function useMatrix() {
  return useQuery({
    queryKey: ["profile-matrix"],
    queryFn: () =>
      unwrap(api.GET("/api/profile/matrix", {} as never)) as Promise<ProfileMatrix>,
  });
}

export function useSuppressedSkills() {
  return useQuery({
    queryKey: ["suppressed-skills"],
    queryFn: () =>
      unwrap(
        api.GET("/api/profile/suppressed-skills", {} as never),
      ) as Promise<SuppressedSkill[]>,
  });
}

export function useDeleteSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (key: string) =>
      unwrap(api.DELETE("/api/profile/skills/{key}", { params: { path: { key } } })),
    onSuccess: () => {
      invalidateMatrixSurfaces(queryClient);
      toast.success("Skill deleted");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useRestoreSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (token: string) =>
      unwrap(
        api.POST("/api/profile/suppressed-skills/{token}/restore", {
          params: { path: { token } },
        }),
      ),
    onSuccess: () => {
      invalidateMatrixSurfaces(queryClient);
      toast.success("Skill restored");
    },
    onError: (error: Error) => toast.error(error.message),
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
