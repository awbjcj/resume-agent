import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, getToken, unwrap } from "@/lib/api/client";

export type ProfileDocument = {
  id: string; filename: string; docType: string; sizeBytes: number; uploadedAt: string;
};

export function useDocuments() {
  return useQuery({
    queryKey: ["profile-documents"],
    queryFn: () =>
      unwrap(api.GET("/api/profile/documents", {} as never)) as Promise<ProfileDocument[]>,
  });
}

async function postDocument(file: File, docType: string): Promise<ProfileDocument> {
  const form = new FormData();
  form.append("file", file);
  form.append("docType", docType);
  const headers: HeadersInit = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(`${window.location.origin}/api/profile/documents`, {
    method: "POST", body: form, headers,
  });
  const body = await resp.json();
  if (!resp.ok) throw new Error(body?.error?.message ?? "Upload failed");
  return body as ProfileDocument;
}

export function useUploadDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, docType }: { file: File; docType: string }) =>
      postDocument(file, docType),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile-documents"] });
      qc.invalidateQueries({ queryKey: ["setup-status"] });
      toast.success("Document uploaded");
    },
    onError: (err: Error) => toast.error(err.message),
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) =>
      unwrap(api.DELETE("/api/profile/documents/{doc_id}", {
        params: { path: { doc_id: docId } },
      } as never)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile-documents"] });
      qc.invalidateQueries({ queryKey: ["setup-status"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });
}
