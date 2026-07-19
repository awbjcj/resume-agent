import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type GmailStatus = components["schemas"]["GmailStatusOut"];
const KEY = ["gmail-status"];

export function useGmailStatus() {
  return useQuery<GmailStatus>({
    queryKey: KEY,
    queryFn: () => unwrap(api.GET("/api/gmail/status")),
  });
}

export function useGmailConnect() {
  return useMutation({
    mutationFn: async () => {
      const out = await unwrap(api.GET("/api/gmail/connect"));
      window.location.href = out.authUrl;
    },
    onError: (err: Error) => toast.error(err.message),
  });
}

export function useGmailDisconnect() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/gmail/token")),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY });
      toast.success("Gmail disconnected");
    },
    onError: (err: Error) => toast.error(err.message),
  });
}
