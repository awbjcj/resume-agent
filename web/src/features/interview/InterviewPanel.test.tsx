import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  start: vi.fn(),
  submit: vi.fn(),
  sync: vi.fn(),
  addUrl: vi.fn(),
}));

vi.mock("./use-interview", () => ({
  useInterviewHistory: () => ({
    data: {
      rounds: [
        {
          roundId: "r0",
          askedAt: "2026-07-14T00:00:00+00:00",
          questions: [{ id: "q0", gap: "old gap", questionText: "Old question?" }],
          researchActions: [],
          answers: [
            { questionId: "q0", docId: "d0", answerText: "Old evidence." },
          ],
          submittedAt: "2026-07-14T01:00:00+00:00",
        },
      ],
    },
  }),
  useStartInterview: () => ({ mutateAsync: mocks.start, isPending: false }),
  useInterviewRound: (runId: string | null) =>
    runId
      ? {
          state: "done",
          error: null,
          round: {
            roundId: "r1",
            questions: [
              {
                id: "q1",
                gap: "Impact",
                whyItMatters: "Hiring teams need outcomes.",
                questionText: "What changed because of your work?",
                relatedRef: "experience:acme",
              },
            ],
            researchActions: [
              { kind: "harvest_repo", target: "acme/tool", why: "Project evidence" },
              { kind: "request_url", target: "Portfolio page", why: "Public proof" },
            ],
          },
        }
      : { state: "idle", error: null, round: null },
  useSubmitInterview: () => ({ mutateAsync: mocks.submit, isPending: false }),
}));

vi.mock("@/features/profile-sources/use-sources", () => ({
  useSyncGithub: () => ({ mutate: mocks.sync, isPending: false }),
  useAddUrl: () => ({ mutateAsync: mocks.addUrl, isPending: false }),
}));

import { InterviewPanel } from "./InterviewPanel";

describe("InterviewPanel", () => {
  beforeEach(() => {
    mocks.start.mockReset().mockResolvedValue({ runId: "run-1" });
    mocks.submit.mockReset().mockResolvedValue({ docIds: ["d1"] });
    mocks.sync.mockReset();
    mocks.addUrl.mockReset().mockResolvedValue({});
  });

  it("renders history and submits a complete round", async () => {
    const user = userEvent.setup();
    render(<InterviewPanel />);

    expect(screen.getByText("Old question?")).toBeInTheDocument();
    expect(screen.getByText("Old evidence.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /start interview/i }));
    await user.type(
      screen.getByLabelText("What changed because of your work?"),
      "Reduced deploy time by 40%.",
    );
    await user.click(screen.getByRole("button", { name: /send answers/i }));

    await waitFor(() =>
      expect(mocks.submit).toHaveBeenCalledWith({
        runId: "run-1",
        answers: [{ questionId: "q1", text: "Reduced deploy time by 40%." }],
        build: true,
      }),
    );
  });

  it("runs both research actions through existing source mutations", async () => {
    const user = userEvent.setup();
    render(<InterviewPanel />);
    await user.click(screen.getByRole("button", { name: /start interview/i }));
    await user.click(screen.getByRole("button", { name: /re-harvest repo/i }));
    await user.type(screen.getByLabelText(/url for portfolio page/i), "https://me.dev");
    await user.click(screen.getByRole("button", { name: /add page/i }));

    expect(mocks.sync).toHaveBeenCalledOnce();
    expect(mocks.addUrl).toHaveBeenCalledWith({ url: "https://me.dev" });
  });
});
