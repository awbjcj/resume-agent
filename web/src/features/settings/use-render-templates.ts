import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, apiUrl, authHeaders, unwrap } from "@/lib/api/client";
import type { paths } from "@/lib/api/schema";

export type TemplateListItem =
  paths["/api/config/render/templates"]["get"]["responses"][200]["content"]["application/json"][number];

const TEMPLATES_KEY = ["render-templates"] as const;

export function useRenderTemplates() {
  return useQuery({
    queryKey: TEMPLATES_KEY,
    queryFn: () =>
      unwrap(api.GET("/api/config/render/templates")) as Promise<TemplateListItem[]>,
  });
}

export function useUploadTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      const response = await fetch(apiUrl("/api/config/render/templates"), {
        method: "POST",
        body,
        credentials: "include",
        headers: authHeaders(),
      });
      const payload = await response.json();
      if (!response.ok) {
        const detail =
          payload?.error?.details ?? payload?.error?.message ?? "Upload failed";
        throw new Error(String(detail));
      }
      return payload as TemplateListItem;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY });
      toast.success("Template uploaded");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useDeleteTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (stem: string) =>
      unwrap(
        api.DELETE("/api/config/render/templates/{stem}", {
          params: { path: { stem } },
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY });
      queryClient.invalidateQueries({ queryKey: ["config", "/api/config/render"] });
      toast.success("Template deleted");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

export async function openTemplatePreview(templateId: string): Promise<void> {
  const previewWindow = window.open("about:blank", "_blank");
  if (!previewWindow) {
    toast.error("Allow popups to preview this template");
    return;
  }
  previewWindow.opener = null;
  try {
    const encodedId = encodeURIComponent(templateId);
    const response = await fetch(
      apiUrl(`/api/config/render/templates/${encodedId}/preview`),
      { credentials: "include", headers: authHeaders() },
    );
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload?.error?.message ?? "Preview failed");
    }
    const objectUrl = URL.createObjectURL(await response.blob());
    previewWindow.location.replace(objectUrl);
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  } catch (error) {
    previewWindow.close();
    toast.error(error instanceof Error ? error.message : "Preview failed");
  }
}
