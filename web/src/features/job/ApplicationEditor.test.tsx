import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { changeLanguage } from "@/i18n";

const mocks = vi.hoisted(() => ({ upsert: vi.fn() }));
vi.mock("./use-job-mutations", () => ({
  useUpsertApplication: () => ({ mutate: mocks.upsert, isPending: false }),
}));
vi.mock("./ApplicationTimeline", () => ({
  ApplicationTimeline: ({ jobId }: { jobId: number }) => <div>timeline for {jobId}</div>,
}));

import { ApplicationEditor } from "./ApplicationEditor";

const application = {
  id: 7,
  jobId: 42,
  status: "interview",
  notes: "applied via referral",
} as never;

describe("ApplicationEditor", () => {
  beforeEach(async () => {
    mocks.upsert.mockReset();
    await changeLanguage("en");
  });

  it("shows status as a header and notes as a textarea", () => {
    render(<ApplicationEditor jobId={42} application={application} />);
    expect(screen.getByText("Interview")).toBeInTheDocument();
    expect(screen.getByText("timeline for 42")).toBeInTheDocument();
    expect(screen.getByLabelText(/application notes/i).tagName).toBe("TEXTAREA");
  });

  it("reveals and saves a manual status override", async () => {
    const user = userEvent.setup();
    render(<ApplicationEditor jobId={42} application={application} />);
    expect(screen.queryByLabelText(/override status/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /override/i }));
    await user.selectOptions(screen.getByLabelText(/override status/i), "rejected");
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    expect(mocks.upsert).toHaveBeenCalledWith(
      expect.objectContaining({ status: "rejected", notes: "applied via referral" }),
    );
  });

  it("keeps status payload values canonical when the interface is Chinese", async () => {
    await changeLanguage("zh-CN");
    const user = userEvent.setup();
    render(<ApplicationEditor jobId={42} application={application} />);

    expect(screen.getByText("面试中")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /覆盖/ }));
    const status = screen.getByRole("combobox");
    expect(screen.getByRole("option", { name: "已拒绝" })).toHaveValue("rejected");
    await user.selectOptions(status, "rejected");
    await user.click(screen.getByRole("button", { name: "保存" }));

    expect(mocks.upsert).toHaveBeenCalledWith(
      expect.objectContaining({ status: "rejected", notes: "applied via referral" }),
    );
  });
});
