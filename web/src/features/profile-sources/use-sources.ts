import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, getToken, unwrap } from "@/lib/api/client";

export type ProfileSource = {
  id: string;
  filename: string;
  mode: "literal" | "synthesis";
  primary: boolean;
  anchor: string | null;
  addedAt: string;
  fragmentStatus: string;
};

export type SkeletonEntry = { id: string; kind: string; label: string };

export function useSources() {
  return useQuery({
    queryKey: ["profile-sources"],
    queryFn: () =>
      unwrap(api.GET("/api/profile/sources", {} as never)) as Promise<ProfileSource[]>,
  });
}

export function useSkeleton() {
  return useQuery({
    queryKey: ["profile-skeleton"],
    queryFn: () =>
      unwrap(api.GET("/api/profile/skeleton", {} as never)) as Promise<SkeletonEntry[]>,
  });
}

async function postSource(file: File, mode?: string): Promise<ProfileSource> {
  const form = new FormData();
  form.append("file", file);
  if (mode) form.append("mode", mode);
  const headers: HeadersInit = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(`${window.location.origin}/api/profile/sources`, {
    method: "POST", body: form, headers,
  });
  const body = await resp.json();
  if (!resp.ok) throw new Error(body?.error?.message ?? "Upload failed");
  return body as ProfileSource;
}

export function useUploadSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, mode }: { file: File; mode?: string }) => postSource(file, mode),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile-sources"] });
      toast.success("Source added");
    },
    onError: (err: Error) => toast.error(err.message),
  });
}

export function usePatchSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...patch }: { id: string } & Partial<Pick<ProfileSource, "mode" | "anchor" | "primary">>) =>
      unwrap(api.PATCH("/api/profile/sources/{doc_id}", {
        params: { path: { doc_id: id } },
        body: patch,
      } as never)) as Promise<ProfileSource>,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profile-sources"] }),
    onError: (err: Error) => toast.error(err.message),
  });
}

export function useDeleteSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/profile/sources/{doc_id}", {
        params: { path: { doc_id: id } },
      } as never)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profile-sources"] }),
    onError: (err: Error) => toast.error(err.message),
  });
}
