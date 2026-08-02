import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useChatStream } from "./useChatStream";

class FakeEventSource {
  static last: FakeEventSource | null = null;
  static instances: FakeEventSource[] = [];
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeEventSource.last = this;
    FakeEventSource.instances.push(this);
  }
  close() {
    this.closed = true;
  }
  send(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

vi.stubGlobal("EventSource", FakeEventSource);
vi.mock("@/features/runs/use-launch-run", () => ({ cancelRun: vi.fn() }));

describe("useChatStream", () => {
  beforeEach(() => {
    FakeEventSource.last = null;
    FakeEventSource.instances = [];
    resetSseLinkTokenCache();
    localStorage.setItem("resume-agent-token", "token");
  });

  it("accumulates valid events and ignores malformed rows without advancing", async () => {
    const { result } = renderHook(() => useChatStream("run-1"));
    await waitFor(() => expect(FakeEventSource.last).not.toBeNull());
    act(() => FakeEventSource.last!.send({ i: "4", t: "text", v: { text: "bad" } }));
    act(() => FakeEventSource.last!.send({ i: 4, t: "text", v: { text: "gap" } }));
    act(() => FakeEventSource.last!.send({ i: 0, t: "text", v: { text: "hi" } }));
    await waitFor(() => expect(result.current.parts).toHaveLength(1));
    act(() => FakeEventSource.last!.onerror?.());
    await waitFor(() => expect(FakeEventSource.last!.url).toContain("offset=1"));
  });

  it("resets all state when run id changes", async () => {
    const { result, rerender } = renderHook(({ id }) => useChatStream(id), {
      initialProps: { id: "run-1" as string | null },
    });
    await waitFor(() => expect(FakeEventSource.last).not.toBeNull());
    act(() => FakeEventSource.last!.send({ i: 0, t: "text", v: { text: "old" } }));
    await waitFor(() => expect(result.current.parts).toHaveLength(1));
    rerender({ id: "run-2" });
    await waitFor(() => expect(result.current.parts).toEqual([]));
    expect(FakeEventSource.last!.url).toContain("run-2");
    expect(FakeEventSource.last!.url).toContain("offset=0");
  });

  it("discards partial output when stopped", async () => {
    const { result } = renderHook(() => useChatStream("run-1"));
    await waitFor(() => expect(FakeEventSource.last).not.toBeNull());
    act(() => FakeEventSource.last!.send({ i: 0, t: "text", v: { text: "partial" } }));
    await waitFor(() => expect(result.current.parts).toHaveLength(1));
    act(() => result.current.stop());
    expect(result.current.parts).toEqual([]);
    expect(result.current.status).toBe("idle");
  });

  it("marks visible prose settled without closing the stream", async () => {
    const { result } = renderHook(() => useChatStream("run-1"));
    await waitFor(() => expect(FakeEventSource.last).not.toBeNull());
    act(() => FakeEventSource.last!.send({ i: 0, t: "text", v: { text: "done" } }));
    act(() => FakeEventSource.last!.send({ i: 1, t: "settled", v: {} }));
    expect(result.current.status).toBe("settled");
    expect(FakeEventSource.last!.closed).toBe(false);
  });

  it("reuses one unexpired link token across consecutive runs", async () => {
    localStorage.removeItem("resume-agent-token");
    let requests = 0;
    server.use(http.post("/api/auth/link-token", () => {
      requests += 1;
      return HttpResponse.json({ token: "shared-link", expiresInSeconds: 60 });
    }));
    const { rerender } = renderHook(({ id }) => useChatStream(id), {
      initialProps: { id: "run-1" as string | null },
    });
    await waitFor(() => expect(FakeEventSource.last?.url).toContain("token=shared-link"));
    rerender({ id: "run-2" });
    await waitFor(() => expect(FakeEventSource.last?.url).toContain("run-2"));
    expect(requests).toBe(1);
  });

  it("re-mints a cached token once when its first connection fails", async () => {
    localStorage.removeItem("resume-agent-token");
    let requests = 0;
    server.use(http.post("/api/auth/link-token", () => {
      requests += 1;
      return HttpResponse.json({ token: `link-${requests}`, expiresInSeconds: 60 });
    }));
    renderHook(() => useChatStream("run-1"));
    await waitFor(() => expect(FakeEventSource.last?.url).toContain("token=link-1"));
    act(() => FakeEventSource.last!.onerror?.());
    await waitFor(() => expect(FakeEventSource.last?.url).toContain("token=link-2"));
    expect(requests).toBe(2);
  });
});
import { resetSseLinkTokenCache } from "@/lib/runs/linkToken";
import { server } from "@/test/server";
