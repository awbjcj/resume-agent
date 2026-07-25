import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RedoDialog } from "./RedoDialog";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function setup(props: Partial<React.ComponentProps<typeof RedoDialog>> = {}) {
  const onLaunch = vi.fn().mockResolvedValue(true);
  render(
    <RedoDialog
      open
      jobIds={[1, 2, 3]}
      initialStages={["tailor"]}
      onOpenChange={() => {}}
      onLaunch={onLaunch}
      {...props}
    />,
    { wrapper },
  );
  return { onLaunch };
}

describe("RedoDialog", () => {
  it("states the exact job count in the confirm button", () => {
    setup();
    expect(
      screen.getByRole("button", { name: /re-tailor 3 jobs/i }),
    ).toBeInTheDocument();
  });

  it("pre-ticks the stages it was opened with", () => {
    setup();
    expect(screen.getByRole("checkbox", { name: /re-tailor resume/i })).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: /re-pull job description/i }),
    ).not.toBeChecked();
  });

  it("pre-ticks re-extract when re-pull is ticked", async () => {
    const user = userEvent.setup();
    setup({ initialStages: [] });

    await user.click(screen.getByRole("checkbox", { name: /re-pull job description/i }));

    expect(
      screen.getByRole("checkbox", { name: /re-extract criteria/i }),
    ).toBeChecked();
  });

  it("lets you untick the auto-ticked re-extract", async () => {
    const user = userEvent.setup();
    setup({ initialStages: [] });

    await user.click(screen.getByRole("checkbox", { name: /re-pull job description/i }));
    await user.click(screen.getByRole("checkbox", { name: /re-extract criteria/i }));

    expect(
      screen.getByRole("checkbox", { name: /re-extract criteria/i }),
    ).not.toBeChecked();
  });

  it("launches with the ticked stages in pipeline order", async () => {
    const user = userEvent.setup();
    const { onLaunch } = setup({ initialStages: ["tailor"] });

    await user.click(screen.getByRole("checkbox", { name: /re-render pdf/i }));
    await user.click(screen.getByRole("button", { name: /re-tailor/i }));

    expect(onLaunch).toHaveBeenCalledWith([1, 2, 3], ["tailor", "render"], false);
  });

  it("disables launch when nothing is ticked", async () => {
    const user = userEvent.setup();
    setup({ initialStages: ["tailor"] });

    await user.click(screen.getByRole("checkbox", { name: /re-tailor resume/i }));

    expect(screen.getByRole("button", { name: /choose a stage/i })).toBeDisabled();
  });

  it("shows the deep-review switch only when re-tailor is ticked", async () => {
    const user = userEvent.setup();
    setup({ initialStages: [] });
    expect(screen.queryByRole("switch", { name: /deep review/i })).toBeNull();

    await user.click(screen.getByRole("checkbox", { name: /re-tailor resume/i }));

    expect(screen.getByRole("switch", { name: /deep review/i })).toBeInTheDocument();
  });

  it("does not strand a stray '0 jobs' popup when the caller clears open and jobIds together (AttentionCard retry pattern)", async () => {
    const user = userEvent.setup();
    const onLaunch = vi.fn().mockResolvedValue(true);

    function Harness() {
      const [retry, setRetry] = useState<{ jobId: number } | null>({ jobId: 42 });
      return (
        <RedoDialog
          open={retry !== null}
          jobIds={retry ? [retry.jobId] : []}
          initialStages={["tailor"]}
          onOpenChange={(open) => {
            if (!open) setRetry(null);
          }}
          onLaunch={onLaunch}
        />
      );
    }
    render(<Harness />, { wrapper });

    expect(document.body.querySelector('[data-slot="dialog-content"]')).not.toBeNull();

    await user.click(screen.getByRole("button", { name: /cancel/i }));

    // The caller clears its target (jobIds -> []) in the same update that
    // closes the dialog. That must not remount the popup body mid-close: a
    // fresh "0 jobs" instance would mount already-closed, Base UI would
    // never animate it, and it would never disappear -- and its own
    // Cancel/Close would call back into an already-null target and do
    // nothing. The popup must simply close.
    expect(document.body.querySelector('[data-slot="dialog-content"]')).toBeNull();
  });
});
