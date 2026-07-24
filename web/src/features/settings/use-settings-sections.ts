import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { paths } from "@/lib/api/schema";

export type SettingsSection =
  paths["/api/settings/sections"]["get"]["responses"][200]["content"]["application/json"]["sections"][number];

export const SETTINGS_SECTIONS_KEY = ["settings-sections"] as const;

export function useSettingsSections() {
  return useQuery({
    queryKey: SETTINGS_SECTIONS_KEY,
    queryFn: async () => {
      const body = await unwrap(api.GET("/api/settings/sections"));
      return (body as { sections: SettingsSection[] }).sections;
    },
  });
}

export function useResetSection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ sectionId }: { sectionId: string }) =>
      unwrap(
        api.POST("/api/settings/sections/{section_id}/reset", {
          params: { path: { section_id: sectionId } },
        }),
      ) as Promise<SettingsSection>,
    onSuccess: (section) => {
      // A reset rewrites files other settings pages read, so drop everything
      // rather than trying to name each affected query key.
      void queryClient.invalidateQueries();
      toast.success(`${section.label} reset to defaults`);
    },
    onError: (error: Error) => toast.error(error.message),
  });
}
