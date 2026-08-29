import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ mutate: vi.fn() }));
vi.mock("@/features/triage/use-triage-mutations", () => ({
  useDeleteJob: () => ({ mutate: mocks.mutate }),
}));

import { TrackingTab } from "./TrackingTab";
import type { JobDetail } from "./use-job-detail";
import { server } from "@/test/server";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}

const baseJob = {
  id: 42,
  status: "shortlisted",
  hasProgress: false,
  application: null,
} as unknown as JobDetail;

describe("TrackingTab", () => {
  beforeEach(() => {
    mocks.mutate.mockReset();
    server.use(http.get("*/api/jobs/42/events", () => HttpResponse.json([])));
  });

  it("renders stage, application, and a fenced danger zone", () => {
    render(<TrackingTab job={baseJob} onDeleted={vi.fn()} />, { wrapper });

    expect(screen.getByLabelText("Stage")).toBeInTheDocument();
    expect(screen.getByText("Current status")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Override" })).toBeInTheDocument();
    expect(screen.getByLabelText("Application notes")).toBeInTheDocument();
    expect(screen.getByText("Danger zone")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /delete/i })).toBeEnabled();
  });

  it("disables delete when the job has progress", () => {
    render(
      <TrackingTab job={{ ...baseJob, hasProgress: true }} onDeleted={vi.fn()} />,
      { wrapper },
    );

    expect(screen.getByRole("button", { name: /delete/i })).toBeDisabled();
    expect(screen.getByText(/has progress/i)).toBeInTheDocument();
  });

  it("no longer exposes delete from the stage section", () => {
    render(<TrackingTab job={baseJob} onDeleted={vi.fn()} />, { wrapper });
    expect(screen.getAllByRole("button", { name: /delete/i })).toHaveLength(1);
  });

  it("closes only after the delete mutation succeeds", async () => {
    const onDeleted = vi.fn();
    const user = userEvent.setup();
    render(<TrackingTab job={baseJob} onDeleted={onDeleted} />, { wrapper });

    await user.click(screen.getByRole("button", { name: /delete job/i }));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    expect(onDeleted).not.toHaveBeenCalled();
    const [, options] = mocks.mutate.mock.calls[0] ?? [];
    options?.onSuccess?.();
    expect(onDeleted).toHaveBeenCalledOnce();
  });
});
