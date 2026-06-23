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
export function withTokenParam(path: string): string {
  const token = getToken();
  if (!token) return path;
  const hashIndex = path.indexOf("#");
  const beforeHash = hashIndex === -1 ? path : path.slice(0, hashIndex);
  const hash = hashIndex === -1 ? "" : path.slice(hashIndex);
  const separator = beforeHash.includes("?") ? "&" : "?";
  return `${beforeHash}${separator}token=${encodeURIComponent(token)}${hash}`;
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

interface PageEnvelope<T> {
  data: T[];
  pagination: { totalPages: number };
}

/**
 * Fetch every page of a paginated board endpoint (the API caps pageSize at 200),
 * so client-side filtering sees all rows. Page 1 reveals totalPages; only then
 * are the remaining pages requested, so single-page boards cost one request.
 */
export async function fetchAllPages<T>(
  getPage: (page: number) => Promise<{ data?: unknown; error?: ErrorEnvelope | unknown }>,
): Promise<T[]> {
  const first = (await unwrap(getPage(1))) as PageEnvelope<T>;
  const all = [...first.data];
  for (let page = 2; page <= first.pagination.totalPages; page++) {
    const next = (await unwrap(getPage(page))) as PageEnvelope<T>;
    all.push(...next.data);
  }
  return all;
}
