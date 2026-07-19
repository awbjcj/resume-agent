import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type GmailStatus = components["schemas"]["GmailStatusOut"];
const KEY = ["gmail-status"];

// The OAuth callback (unguarded, no SPA context) can only signal its result by
// redirecting to /settings/keys?gmail=<outcome>. Surface it here so failures
// aren't silent, then strip the param so a refresh doesn't re-toast.
const CONNECT_OUTCOMES: Record<string, { ok: boolean; message: string }> = {
  connected: { ok: true, message: "Gmail connected." },
  error: {
    ok: false,
    message: "Couldn’t connect Gmail — the sign-in didn’t complete. Please try again.",
  },
  invalid: {
    ok: false,
    message: "Gmail sign-in link expired or was invalid. Please try connecting again.",
  },
  denied: { ok: false, message: "Gmail connection was cancelled." },
};

export function useGmailConnectOutcome() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const outcome = params.get("gmail");
  useEffect(() => {
    if (!outcome) return;
    const entry = CONNECT_OUTCOMES[outcome];
    if (entry?.ok) {
      toast.success(entry.message);
      qc.invalidateQueries({ queryKey: KEY });
    } else if (entry) {
      toast.error(entry.message);
    }
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.delete("gmail");
        return next;
      },
      { replace: true },
    );
  }, [outcome, qc, setParams]);
}

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
