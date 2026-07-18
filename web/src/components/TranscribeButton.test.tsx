import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TranscribeButton } from "./TranscribeButton";

const mocks = vi.hoisted(() => ({ unwrap: vi.fn(), get: vi.fn() }));

vi.mock("@/lib/api/client", () => ({
  api: { GET: mocks.get },
  unwrap: mocks.unwrap,
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const getUserMedia = vi.fn();

class FakeRecorder {
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  stream: { getTracks: () => { stop: () => void }[] };
  constructor(stream: { getTracks: () => { stop: () => void }[] }) {
    this.stream = stream;
  }
  start() {}
  stop() {
    this.ondataavailable?.({ data: new Blob(["audio"]) });
    this.onstop?.();
  }
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient();
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.unwrap.mockResolvedValue({ available: true });
  getUserMedia.mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] });
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => ({ text: "hello world" }) }),
  );
});

afterEach(() => vi.unstubAllGlobals());

describe("TranscribeButton", () => {
  it("renders nothing when transcription is unavailable", async () => {
    mocks.unwrap.mockResolvedValue({ available: false });
    const { container } = render(<TranscribeButton onText={vi.fn()} />, { wrapper });
    await waitFor(() => expect(mocks.unwrap).toHaveBeenCalled());
    expect(container.querySelector("button")).toBeNull();
  });

  it("records, uploads, and forwards the transcript", async () => {
    const onText = vi.fn();
    render(<TranscribeButton onText={onText} />, { wrapper });
    const record = await screen.findByRole("button", { name: /record a voice answer/i });

    await userEvent.click(record);
    const stop = await screen.findByRole("button", { name: /stop recording/i });
    await userEvent.click(stop);

    await waitFor(() => expect(onText).toHaveBeenCalledWith("hello world"));
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/transcribe",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("keeps the blob for retry after a failed upload", async () => {
    const onText = vi.fn();
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ ok: false });
    render(<TranscribeButton onText={onText} />, { wrapper });

    await userEvent.click(await screen.findByRole("button", { name: /record a voice answer/i }));
    await userEvent.click(await screen.findByRole("button", { name: /stop recording/i }));

    const retry = await screen.findByRole("button", { name: /retry transcription/i });
    expect(getUserMedia).toHaveBeenCalledTimes(1);

    await userEvent.click(retry);
    await waitFor(() => expect(onText).toHaveBeenCalledWith("hello world"));
    expect(getUserMedia).toHaveBeenCalledTimes(1); // no second capture
  });
});
