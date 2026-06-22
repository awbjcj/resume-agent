import createClient from "openapi-fetch";

import type { paths } from "./schema";

const TOKEN_KEY = "resume-agent-token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

// Absolute same-origin base. The schema paths already start with "/api", so we
// only need the origin. Using window.location.origin (rather than "" or "/")
// keeps requests same-origin in the browser and yields an absolute URL under
// jsdom/Node fetch, which rejects relative URLs as "Invalid URL".
const baseUrl = typeof window !== "undefined" ? window.location.origin : "";
// Defer to globalThis.fetch at call time (not capture-at-construct): lets MSW —
// which patches the global in test setup after this module loads — intercept.
export const api = createClient<paths>({
  baseUrl,
  fetch: (request: Request) => globalThis.fetch(request),
});

api.use({
  onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
});

type ErrorEnvelope = { error?: { code: string; message: string; details?: unknown } };

/** Unwrap an openapi-fetch result, throwing the API error-envelope message. */
export async function unwrap<T>(
  p: Promise<{ data?: T; error?: ErrorEnvelope | unknown }>,
): Promise<T> {
  const { data, error } = await p;
  if (error) {
    const env = error as ErrorEnvelope;
    throw new Error(env?.error?.message ?? "Request failed");
  }
  return data as T;
}
