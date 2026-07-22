import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type SkillEntry = components["schemas"]["SkillEntryOut"];

function invalidateSkillSurfaces(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["profile-skills"] });
  qc.invalidateQueries({ queryKey: ["profile-matrix"] });
  qc.invalidateQueries({ queryKey: ["job"] });
  for (const k of ["shortlist", "pipeline", "triage"]) {
    qc.invalidateQueries({ queryKey: [k] });
  }
}

export function useProfileSkills(enabled = true) {
  return useQuery({
    queryKey: ["profile-skills"],
    enabled,
    queryFn: () =>
      unwrap(api.GET("/api/profile/skills", {} as never)) as Promise<SkillEntry[]>,
  });
}

export function useAddSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { name: string; category?: "hard" | "soft" | "domain" | null }) =>
      unwrap(api.POST("/api/profile/skills", { body: vars })),
    onSuccess: () => {
      invalidateSkillSurfaces(qc);
      toast.success("Added to your skills");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useAddSkillAlias() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { skillId: string; alias: string }) =>
      unwrap(
        api.POST("/api/profile/skills/{skill_id}/aliases", {
          params: { path: { skill_id: vars.skillId } },
          body: { alias: vars.alias },
        }),
      ),
    onSuccess: () => {
      invalidateSkillSurfaces(qc);
      toast.success("Added to your skills");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}
