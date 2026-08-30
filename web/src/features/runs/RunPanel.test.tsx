import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { RunPanel } from "./RunPanel";
import { changeLanguage } from "@/i18n";
import { useRunStore } from "@/lib/runs/store";

describe("RunPanel", () => {
  beforeEach(() => useRunStore.setState({ runs: {} }));
  afterEach(async () => {
    await changeLanguage("en");
  });

  it("renders an accessible progressbar for an active run", () => {
    useRunStore.getState().upsert({
      runId: "r1",
      kind: "pull",
      status: "running",
      percent: 42,
      phase: "adzuna",
      current: 5,
      total: 12,
      etaText: null,
    });
    render(<RunPanel />);
    const bar = screen.getByRole("progressbar", { name: /pull/i });
    expect(bar).toHaveAttribute("aria-valuenow", "42");
  });

  it("labels a run that is waiting for its worker lane", () => {
    useRunStore.getState().upsert({
      runId: "r-queued",
      kind: "suggestion",
      status: "queued",
      percent: 0,
      phase: "Waiting",
      current: 0,
      total: 0,
      etaText: null,
    });
    render(<RunPanel />);
    expect(screen.getByRole("progressbar", { name: /suggestion progress queued/i })).toBeInTheDocument();
  });

  it("shows ETA, counts, and a cancel button for a running op", () => {
    useRunStore.getState().upsert({
      runId: "r1",
      kind: "discover",
      status: "running",
      percent: 30,
      phase: "Scoring fit",
      current: 6,
      total: 20,
      etaText: "2m",
    });
    render(<RunPanel />);
    expect(screen.getByText("6/20")).toBeInTheDocument();
    expect(screen.getByText(/~2m left/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  it("hides the cancel button once terminal", () => {
    useRunStore.getState().upsert({
      runId: "r1",
      kind: "pull",
      status: "cancelled",
      percent: 40,
      phase: "adzuna",
      current: 4,
      total: 10,
      etaText: null,
    });
    render(<RunPanel />);
    expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();
    expect(screen.getByText(/cancelled/)).toBeInTheDocument();
  });

  it("localizes dynamic run kinds and backend phases in Chinese", async () => {
    await changeLanguage("zh-CN");
    useRunStore.getState().upsert({
      runId: "profile-build",
      kind: "profile-build",
      status: "running",
      percent: 0,
      phase: "Extracting and merging source documents",
      current: 0,
      total: 3,
      etaText: null,
    });
    render(<RunPanel />);

    expect(screen.getByText(/个人资料构建 · 正在提取并合并源文档/)).toBeInTheDocument();
    expect(screen.queryByText(/PROFILE-BUILD|EXTRACTING AND MERGING SOURCE DOCUMENTS/)).not.toBeInTheDocument();
  });

  it("localizes a running ETA in Chinese", async () => {
    await changeLanguage("zh-CN");
    useRunStore.getState().upsert({
      runId: "profile-build-eta",
      kind: "profile-build",
      status: "running",
      percent: 33,
      phase: "Extracting and merging source documents",
      current: 0,
      total: 3,
      etaText: "10m 14s",
    });
    render(<RunPanel />);

    expect(screen.getByText(/33% · 约剩 10 分 14 秒/)).toBeInTheDocument();
    expect(screen.queryByText(/left/i)).not.toBeInTheDocument();
  });

  it("renders nothing when no runs", () => {
    const { container } = render(<RunPanel />);
    expect(container).toBeEmptyDOMElement();
  });
});
