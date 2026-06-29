import { beforeEach, describe, expect, it, vi } from "vitest";

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
    useRunStore.setState({ runs: {} });
  });

  it("passes the terminal run record to the completion callback", () => {
    let completed: RunRecord | undefined;
    watchRun("r1", "tailor", (run) => {
      completed = run;
    });

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

  it("represents an acknowledged cancellation request as cancelling", () => {
    watchRun("r1", "tailor");

    FakeEventSource.current.onmessage?.({
      data: JSON.stringify({ state: "cancelling", label: "Cancelling", percent: 20 }),
    } as MessageEvent);

    expect(useRunStore.getState().runs.r1.status).toBe("cancelling");
  });

  it("maps a pending backend record to queued", () => {
    watchRun("r1", "suggestion");

    FakeEventSource.current.onmessage?.({
      data: JSON.stringify({ state: "pending", label: "Queued" }),
    } as MessageEvent);

    expect(useRunStore.getState().runs.r1.status).toBe("queued");
  });

  it("reports a transport error without marking the backend run failed", () => {
    const onTransportError = vi.fn();
    watchRun("r1", "pull", undefined, onTransportError);

    FakeEventSource.current.onerror?.();

    expect(onTransportError).toHaveBeenCalledOnce();
    expect(useRunStore.getState().runs.r1).toBeUndefined();
  });
});
