import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LaunchDialog } from "./LaunchDialog";

const jobs = [
  { jobId: 1, company: "Acme", title: "Senior Backend Engineer" },
  { jobId: 2, company: "Globex", title: "Platform Engineer" },
];

describe("LaunchDialog", () => {
  it("launches the selected subset with deep review and closes on success", async () => {
    const user = userEvent.setup();
    const onLaunch = vi.fn().mockResolvedValue(true);
    const onOpenChange = vi.fn();
    render(
      <LaunchDialog
        mode="tailor"
        jobs={jobs}
        open
        onOpenChange={onOpenChange}
        onLaunch={onLaunch}
      />,
    );

    await user.click(screen.getByRole("checkbox", { name: /Globex/ }));
    await user.click(screen.getByRole("switch", { name: /deep review/i }));
    await user.click(screen.getByRole("button", { name: /tailor 1 job/i }));

    expect(onLaunch).toHaveBeenCalledWith([1], true);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("stays open when launch creation fails", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(
      <LaunchDialog
        mode="tailor"
        jobs={jobs}
        open
        onOpenChange={onOpenChange}
        onLaunch={vi.fn().mockResolvedValue(false)}
      />,
    );

    await user.click(screen.getByRole("button", { name: /tailor 2 jobs/i }));

    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("hides deep review for cover letters and disables empty selection", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <LaunchDialog
        mode="coverLetter"
        jobs={jobs}
        open
        onOpenChange={() => {}}
        onLaunch={vi.fn().mockResolvedValue(true)}
      />,
    );
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /write 2 cover letters/i })).toBeEnabled();

    rerender(
      <LaunchDialog
        mode="tailor"
        jobs={[jobs[0]]}
        open
        onOpenChange={() => {}}
        onLaunch={vi.fn().mockResolvedValue(true)}
      />,
    );
    await user.click(screen.getByRole("checkbox", { name: /Acme/ }));
    expect(screen.getByRole("button", { name: /^tailor/i })).toBeDisabled();
  });

  it("represents loading and query errors", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const { rerender } = render(
      <LaunchDialog
        mode="tailor"
        jobs={[]}
        open
        isLoading
        onOpenChange={() => {}}
        onLaunch={vi.fn().mockResolvedValue(true)}
      />,
    );
    expect(screen.getByText(/loading approved jobs/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^tailor/i })).toBeDisabled();

    rerender(
      <LaunchDialog
        mode="tailor"
        jobs={[]}
        open
        error="Could not load approved jobs"
        onRetry={onRetry}
        onOpenChange={() => {}}
        onLaunch={vi.fn().mockResolvedValue(true)}
      />,
    );
    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
