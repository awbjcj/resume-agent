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

export const api = createClient<paths>({ baseUrl: "/" });

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
