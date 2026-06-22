import { beforeEach, describe, expect, it } from "vitest";

import { getToken, setToken, unwrap } from "./client";

describe("token storage", () => {
  beforeEach(() => localStorage.clear());
  it("round-trips the bearer token", () => {
    expect(getToken()).toBeNull();
    setToken("abc");
    expect(getToken()).toBe("abc");
  });
});

describe("unwrap", () => {
  it("returns data when present", async () => {
    const r = await unwrap(Promise.resolve({ data: { ok: 1 }, error: undefined }));
    expect(r).toEqual({ ok: 1 });
  });
  it("throws the error envelope message", async () => {
    const env = { error: { error: { code: "NOT_FOUND", message: "nope" } }, data: undefined };
    await expect(unwrap(Promise.resolve(env))).rejects.toThrow("nope");
  });
});
