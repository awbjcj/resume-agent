import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ launch: vi.fn(), api: { DELETE: vi.fn(), POST: vi.fn() } }));

vi.mock("@/features/runs/use-launch-run", () => ({
  useLaunchRun: () => ({ launch: mocks.launch }),
}));

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  api: mocks.api,
  openDownload: vi.fn(),
}));

import { useRunStore } from "@/lib/runs/store";
import { ResumeVersionsTab } from "./ResumeVersionsTab";

function wrap(ui: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>,
  );
}

function version(id: number, round: number) {
  return {
    id,
    jobId: 3,
    round,
    origin: "tailor",
    reviewScore: 80,
    factCheckPassed: true,
    pdfPath: null,
    critiqueJson: null,
    createdAt: "2026-08-11T00:00:00Z",
    failedGates: [],
    hasEvidencePortfolio: false,
  } as never;
}

describe("ResumeVersionsTab", () => {
  beforeEach(() => {
    useRunStore.setState({ runs: {} });
    mocks.launch.mockReset();
    mocks.api.DELETE.mockReset().mockResolvedValue({ data: {} });
    mocks.api.POST.mockReset().mockResolvedValue({ data: { deleted: 2 } });
  });

  it("hides the cleanup bar when nothing is deletable", () => {
    // A single applied version: there is no cleanup to offer.
    wrap(
      <ResumeVersionsTab jobId={3} versions={[version(1, 0)]} appliedVersionId={1} />,
    );

    expect(screen.queryByText("Select all")).not.toBeInTheDocument();
  });

  it("cannot select or delete the applied version", () => {
    wrap(
      <ResumeVersionsTab
        jobId={3}
        versions={[version(1, 0), version(2, 1)]}
        appliedVersionId={1}
      />,
    );

    // Base UI's Checkbox is a <span role="checkbox">, not a native input, so
    // its disabled state is aria-disabled rather than the DOM `disabled` prop.
    expect(screen.getByLabelText("Select round 0 for deletion")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getByLabelText("Delete round 0")).toBeDisabled();
    expect(
      screen.getByLabelText("Select round 1 for deletion"),
    ).not.toHaveAttribute("aria-disabled", "true");
  });

  it("select-all skips the applied version", async () => {
    const user = userEvent.setup();
    wrap(
      <ResumeVersionsTab
        jobId={3}
        versions={[version(1, 0), version(2, 1), version(3, 2)]}
        appliedVersionId={1}
      />,
    );

    await user.click(screen.getByLabelText("Select all deletable versions"));

    expect(screen.getByText("2 selected")).toBeInTheDocument();
  });

  it("sends one bulk request for a multi-row delete", async () => {
    const user = userEvent.setup();
    wrap(
      <ResumeVersionsTab
        jobId={3}
        versions={[version(1, 0), version(2, 1)]}
        appliedVersionId={null}
      />,
    );

    await user.click(screen.getByLabelText("Select all deletable versions"));
    await user.click(screen.getByRole("button", { name: /Delete 2 selected/ }));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    expect(mocks.api.POST).toHaveBeenCalledWith(
      "/api/resume-versions/bulk-delete",
      { body: { ids: [1, 2] } },
    );
  });

  it("sends the single-item endpoint when one row is deleted", async () => {
    const user = userEvent.setup();
    wrap(
      <ResumeVersionsTab
        jobId={3}
        versions={[version(1, 0), version(2, 1)]}
        appliedVersionId={null}
      />,
    );

    await user.click(screen.getByLabelText("Delete round 0"));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    expect(mocks.api.DELETE).toHaveBeenCalledWith(
      "/api/resume-versions/{version_id}",
      { params: { path: { version_id: 1 } } },
    );
    expect(mocks.api.POST).not.toHaveBeenCalled();
  });

  it("unselects an applied version through the Applied toggle", async () => {
    const user = userEvent.setup();
    wrap(
      <ResumeVersionsTab jobId={3} versions={[version(1, 0)]} appliedVersionId={1} />,
    );

    await user.click(screen.getByRole("button", { name: /Applied/ }));

    expect(mocks.api.DELETE).toHaveBeenCalledWith(
      "/api/jobs/{job_id}/select-resume",
      { params: { path: { job_id: 3 } } },
    );
  });
});
