import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useRunStore } from "@/lib/runs/store";
import { RecentRuns } from "./RecentRuns";

const base = { percent: 0, phase: "", current: 0, total: 0, etaText: null };

describe("RecentRuns", () => {
  beforeEach(() => useRunStore.setState({ runs: {} }));

  it("shows an empty hint when there are no runs", () => {
    render(<RecentRuns />);
    expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
  });

  it("lists active runs before finished ones", () => {
    useRunStore.getState().upsert({
      ...base,
      runId: "a",
      kind: "pull",
      status: "succeeded",
      percent: 100,
    });
    useRunStore.getState().upsert({
      ...base,
      runId: "b",
      kind: "discover",
      status: "running",
      percent: 40,
    });
    render(<RecentRuns />);
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("discover");
    expect(items[1]).toHaveTextContent("pull");
    expect(items[1]).toHaveTextContent(/done/i);
    expect(items[1]).toHaveTextContent(/just now/i);
  });

  it("caps the list at five runs", () => {
    for (let i = 0; i < 7; i++) {
      useRunStore.getState().upsert({
        ...base,
        runId: `r${i}`,
        kind: "pull",
        status: "succeeded",
        percent: 100,
      });
    }
    render(<RecentRuns />);
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
  });
});
