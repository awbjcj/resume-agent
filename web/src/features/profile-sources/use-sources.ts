import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, getToken, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useActiveRun } from "@/features/runs/use-active-run";
import { launchers, useLaunchRun } from "@/features/runs/use-launch-run";

export type ProfileSource =
  components["schemas"]["resume_tailor_harness__api__schemas__profile__SourceOut"];
export type NoteInput = components["schemas"]["NoteIn"];
export type UrlInput = components["schemas"]["UrlIn"];

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

async function postSource(
  file: File,
  mode?: string,
  anchor?: string | null,
  primary?: boolean,
): Promise<ProfileSource> {
  const form = new FormData();
  form.append("file", file);
  if (mode) form.append("mode", mode);
  if (anchor) form.append("anchor", anchor);
  if (primary) form.append("primary", "true");
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
    mutationFn: ({
      file,
      mode,
      anchor,
    }: {
      file: File;
      mode?: string;
      anchor?: string | null;
    }) => postSource(file, mode, anchor),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile-sources"] });
      toast.success("Source added");
    },
    onError: (err: Error) => toast.error(err.message),
  });
}

export function useUploadSources() {
  const qc = useQueryClient();
  const uploadAll = async (
    files: File[],
    mode?: string,
    anchor?: string | null,
  ): Promise<{ ok: number; failed: [string, string][] }> => {
    let ok = 0;
    const failed: [string, string][] = [];
    for (const file of files) {
      try {
        await postSource(file, mode, anchor);
        ok += 1;
      } catch (error) {
        failed.push([file.name, (error as Error).message]);
      }
    }
    await qc.invalidateQueries({ queryKey: ["profile-sources"] });
    if (failed.length === 0) {
      toast.success(`${ok} file(s) added`);
    } else {
      toast.warning(
        `${ok} added, ${failed.length} failed: ${failed
          .map(([name]) => name)
          .join(", ")}`,
      );
    }
    return { ok, failed };
  };
  return { uploadAll };
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

export function useAddNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: NoteInput) =>
      unwrap(api.POST("/api/profile/sources/note", { body })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile-sources"] });
      toast.success("Note added");
    },
    onError: (err: Error) => toast.error(err.message),
  });
}

export function useAddUrl() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: UrlInput) =>
      unwrap(api.POST("/api/profile/sources/url", { body })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile-sources"] });
      toast.success("Page added");
    },
    onError: (err: Error) => toast.error(err.message),
  });
}

export function useSyncGithub() {
  const { launch } = useLaunchRun();
  const active = useActiveRun("github-sync");
  const [launching, setLaunching] = useState(false);
  const runPending =
    active?.status === "queued" ||
    active?.status === "running" ||
    active?.status === "cancelling";
  return {
    mutate: () => {
      if (launching || runPending) return;
      setLaunching(true);
      void launch("github-sync", launchers.githubSync, ["profile-sources"])
        .finally(() => setLaunching(false));
    },
    isPending: launching || runPending,
  };
}

// Replaces a source's file in place: the new upload takes over as primary,
// then the doc it displaces is deleted — the two-step swap `add_source` /
// `remove_source` already support, so no new backend endpoint is needed.
export function useReplaceSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ oldId, file }: { oldId: string; file: File }) => {
      const next = await postSource(file, "literal", null, true);
      // add_source dedupes by content hash: replacing with a byte-identical
      // file returns the same doc as oldId. Deleting it then would wipe out
      // the only/primary source instead of a no-op replace.
      if (next.id !== oldId) {
        await unwrap(api.DELETE("/api/profile/sources/{doc_id}", {
          params: { path: { doc_id: oldId } },
        } as never));
      }
      return next;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile-sources"] });
      toast.success("Resume replaced");
    },
    onError: (err: Error) => {
      // The upload can succeed before a later failure (e.g. the delete step),
      // leaving the server ahead of the cached list — refresh it either way.
      qc.invalidateQueries({ queryKey: ["profile-sources"] });
      toast.error(err.message);
    },
  });
}
