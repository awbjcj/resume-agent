import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InterviewSetupDialog } from "./InterviewSetupDialog";

const mocks = vi.hoisted(() => ({ start: vi.fn() }));

vi.mock("./use-interview", () => ({
  useStartInterview: () => mocks.start(),
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
  beforeEach(() => vi.clearAllMocks());

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
});
