import { api, unwrap } from "@/lib/api/client";

const EXPIRY_MARGIN_MS = 30_000;

let cached: { token: string; expiresAt: number } | null = null;
let pending: Promise<string> | null = null;

export function invalidateSseLinkToken(token?: string) {
  if (!token || cached?.token === token) cached = null;
}

export function resetSseLinkTokenCache() {
  cached = null;
  pending = null;
}

export function getSseLinkToken(): Promise<string> {
  if (cached && cached.expiresAt - EXPIRY_MARGIN_MS > Date.now()) {
    return Promise.resolve(cached.token);
  }
  if (pending) return pending;
  pending = unwrap(api.POST("/api/auth/link-token", { body: { purpose: "sse" } }))
    .then((link) => {
      cached = {
        token: link.token,
        expiresAt: Date.now() + link.expiresInSeconds * 1000,
      };
      return link.token;
    })
    .finally(() => {
      pending = null;
    });
  return pending;
}
