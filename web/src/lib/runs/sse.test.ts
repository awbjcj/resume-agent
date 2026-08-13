import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/server";
import { watchRun } from "./sse";
import { useRunStore, type RunRecord } from "./store";

class FakeEventSource {
  static current: FakeEventSource;
  url: string;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.current = this;
  }
}

describe("watchRun", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", FakeEventSource);
    FakeEventSource.current = undefined as never;
    useRunStore.setState({ runs: {} });
    server.use(
      http.post("/api/auth/link-token", () =>
        HttpResponse.json({ token: "sse-link", expiresInSeconds: 60 }),
      ),
    );
  });

  it("passes the terminal run record to the completion callback", async () => {
    let completed: RunRecord | undefined;
    watchRun("r1", "tailor", (run) => {
      completed = run;
    });
    await vi.waitFor(() => expect(FakeEventSource.current).toBeDefined());
    expect(FakeEventSource.current.url).toContain("token=sse-link");

    FakeEventSource.current.onmessage?.({
      data: JSON.stringify({
        state: "done",
        percent: 100,
        label: "Tailoring",
        current: 2,
        total: 2,
        result: { jobs: [{ jobId: 1, versionCount: 3 }] },
      }),
    } as MessageEvent);

    expect(completed?.status).toBe("succeeded");
    expect(completed?.result).toEqual({ jobs: [{ jobId: 1, versionCount: 3 }] });
  });

  it("represents an acknowledged cancellation request as cancelling", async () => {
    watchRun("r1", "tailor");
    await vi.waitFor(() => expect(FakeEventSource.current).toBeDefined());

    FakeEventSource.current.onmessage?.({
      data: JSON.stringify({ state: "cancelling", label: "Cancelling", percent: 20 }),
    } as MessageEvent);

    expect(useRunStore.getState().runs.r1.status).toBe("cancelling");
  });

  it("maps a pending backend record to queued", async () => {
    watchRun("r1", "suggestion");
    await vi.waitFor(() => expect(FakeEventSource.current).toBeDefined());

    FakeEventSource.current.onmessage?.({
      data: JSON.stringify({ state: "pending", label: "Queued" }),
    } as MessageEvent);

    expect(useRunStore.getState().runs.r1.status).toBe("queued");
  });

  it("keeps durable backend metadata on streamed run records", async () => {
    watchRun("r1", "coverLetter");
    await vi.waitFor(() => expect(FakeEventSource.current).toBeDefined());

    FakeEventSource.current.onmessage?.({
      data: JSON.stringify({
        state: "running",
        label: "Drafting",
        meta: { jobIds: [3, 8] },
      }),
    } as MessageEvent);

    expect(useRunStore.getState().runs.r1.meta).toEqual({ jobIds: [3, 8] });
  });

  it("does not erase optimistic metadata when an event omits meta", async () => {
    useRunStore.getState().upsert({
      runId: "r1",
      kind: "coverLetter",
      status: "running",
      percent: 0,
      phase: "Queued",
      current: 0,
      total: 0,
      etaText: null,
      meta: { jobIds: [3, 8] },
    });
    watchRun("r1", "coverLetter");
    await vi.waitFor(() => expect(FakeEventSource.current).toBeDefined());

    FakeEventSource.current.onmessage?.({
      data: JSON.stringify({ state: "running", label: "Drafting" }),
    } as MessageEvent);

    expect(useRunStore.getState().runs.r1.meta).toEqual({ jobIds: [3, 8] });
  });

  it("reports a transport error without marking the backend run failed", async () => {
    const onTransportError = vi.fn();
    watchRun("r1", "pull", undefined, onTransportError);
    await vi.waitFor(() => expect(FakeEventSource.current).toBeDefined());

    FakeEventSource.current.onerror?.();

    expect(onTransportError).toHaveBeenCalledOnce();
    expect(useRunStore.getState().runs.r1).toBeUndefined();
  });

  it("retains a failed revision so its retry instruction remains available", async () => {
    watchRun("r1", "revise");
    await vi.waitFor(() => expect(FakeEventSource.current).toBeDefined());

    FakeEventSource.current.onmessage?.({
      data: JSON.stringify({ state: "error", label: "Failed", error: "provider failed" }),
    } as MessageEvent);
    await vi.advanceTimersByTimeAsync(4000);

    expect(useRunStore.getState().runs.r1).toMatchObject({
      kind: "revise",
      status: "failed",
      error: "provider failed",
    });
  });
});
