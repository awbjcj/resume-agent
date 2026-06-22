import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { RunPanel } from "./RunPanel";
import { useRunStore } from "@/lib/runs/store";

describe("RunPanel", () => {
  beforeEach(() => useRunStore.setState({ runs: {} }));

  it("renders an accessible progressbar for an active run", () => {
    useRunStore
      .getState()
      .upsert({ runId: "r1", kind: "pull", status: "running", percent: 42, phase: "adzuna" });
    render(<RunPanel />);
    const bar = screen.getByRole("progressbar", { name: /pull/i });
    expect(bar).toHaveAttribute("aria-valuenow", "42");
  });

  it("renders nothing when no runs", () => {
    const { container } = render(<RunPanel />);
    expect(container).toBeEmptyDOMElement();
  });
});
