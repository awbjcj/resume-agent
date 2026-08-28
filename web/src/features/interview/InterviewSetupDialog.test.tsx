import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InterviewSetupDialog } from "./InterviewSetupDialog";

const mocks = vi.hoisted(() => ({ start: vi.fn(), audioAvailability: vi.fn() }));

vi.mock("./use-interview", () => ({
  useStartInterview: () => mocks.start(),
  useInterviewAudioAvailability: () => mocks.audioAvailability(),
}));

const versions = [
  {
    id: 3,
    createdAt: "2026-07-17T00:00:00Z",
    origin: "tailor",
    reviewScore: 90,
  },
] as never;

describe("InterviewSetupDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.audioAvailability.mockReturnValue({ data: { available: true }, isPending: false });
  });

  it("closes once the interview run is accepted", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ runId: "run-1" });
    const onOpenChange = vi.fn();
    mocks.start.mockReturnValue({ mutateAsync, isPending: false });

    render(
      <MemoryRouter>
        <InterviewSetupDialog
          jobId={7}
          versions={versions}
          open
          onOpenChange={onOpenChange}
        />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Start interview" }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        jobId: 7,
        resumeVersionId: 3,
        style: expect.objectContaining({
          stage: "hiring_manager",
          demeanor: "neutral",
          difficulty: "standard",
          questionCount: 8,
        }),
      }),
    );
  });

  it("stays open when launching the interview fails", async () => {
    const mutateAsync = vi.fn().mockRejectedValue(new Error("offline"));
    const onOpenChange = vi.fn();
    mocks.start.mockReturnValue({ mutateAsync, isPending: false });

    render(
      <MemoryRouter>
        <InterviewSetupDialog
          jobId={7}
          versions={versions}
          open
          onOpenChange={onOpenChange}
        />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Start interview" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledOnce());
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("submits audio preferred mode with an AI voice disclosure", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ runId: "run-1" });
    mocks.start.mockReturnValue({ mutateAsync, isPending: false });

    render(
      <MemoryRouter>
        <InterviewSetupDialog
          jobId={7}
          versions={versions}
          open
          onOpenChange={vi.fn()}
        />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole("radio", { name: /audio preferred/i }));
    expect(screen.getByText(/AI-generated voice/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start interview" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledOnce());
    expect(mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        style: expect.objectContaining({ responseMode: "audio_preferred" }),
      }),
    );
  });

  it("disables audio preferred mode when speech is unavailable", () => {
    mocks.start.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    mocks.audioAvailability.mockReturnValue({ data: { available: false }, isPending: false });

    render(
      <MemoryRouter>
        <InterviewSetupDialog
          jobId={7}
          versions={versions}
          open
          onOpenChange={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole("radio", { name: /audio preferred/i })).toBeDisabled();
    expect(screen.getByText(/configure an OpenAI speech model/i)).toBeInTheDocument();
  });
});
