import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Journey } from "./use-journey";
import { GettingStartedChecklist } from "./GettingStartedChecklist";

const mocks = vi.hoisted(() => ({ journey: vi.fn<() => Journey | null>() }));
vi.mock("./use-journey", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./use-journey")>()),
  useJourney: () => mocks.journey(),
}));

const incomplete: Journey = {
  stages: [
    { id: "profile", label: "Profile", task: "Build your profile", hint: "h", cta: { label: "Build your profile", to: "/profile" }, state: "done", count: 1 },
    { id: "sources", label: "Sources", task: "Add job sources", hint: "Enable a source.", cta: { label: "Add sources", to: "/settings/sources" }, state: "current", count: 0 },
    { id: "pull", label: "Pull", task: "Pull your first jobs", hint: "h", cta: { label: "Pull jobs", pull: true }, state: "upcoming", count: 0 },
    { id: "shortlist", label: "Shortlist", task: "Shortlist & approve", hint: "h", cta: { label: "Review shortlist", to: "/shortlist" }, state: "upcoming", count: 0 },
    { id: "tailor", label: "Tailor", task: "Tailor a resume", hint: "h", cta: { label: "Tailor a resume", to: "/pipeline?stage=approved" }, state: "upcoming", count: 0 },
  ],
  currentStep: "sources",
  completedCount: 1,
  total: 5,
  complete: false,
};

const renderChecklist = () =>
  render(<MemoryRouter><GettingStartedChecklist /></MemoryRouter>);

afterEach(() => localStorage.clear());

describe("GettingStartedChecklist", () => {
  it("renders nothing while loading, when complete, or when dismissed by storage", () => {
    mocks.journey.mockReturnValue(null);
    expect(renderChecklist().container).toBeEmptyDOMElement();

    mocks.journey.mockReturnValue({ ...incomplete, complete: true });
    expect(renderChecklist().container).toBeEmptyDOMElement();

    localStorage.setItem("resume-tailor-harness-getting-started-dismissed", "1");
    mocks.journey.mockReturnValue(incomplete);
    expect(renderChecklist().container).toBeEmptyDOMElement();
  });

  it("lists every step with progress and only the current step's action", async () => {
    mocks.journey.mockReturnValue(incomplete);
    const { container } = renderChecklist();

    expect(screen.getByText("Getting started")).toBeInTheDocument();
    expect(screen.getByText("1 of 5")).toBeInTheDocument();
    // all five imperative tasks are listed
    for (const task of ["Build your profile", "Add job sources", "Pull your first jobs", "Shortlist & approve", "Tailor a resume"]) {
      expect(screen.getByText(task)).toBeInTheDocument();
    }
    // only the current (sources) step exposes a CTA
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/settings/sources");

    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("dismisses and persists the choice", async () => {
    mocks.journey.mockReturnValue(incomplete);
    renderChecklist();
    await userEvent.click(screen.getByRole("button", { name: /dismiss getting started/i }));
    expect(screen.queryByText("Getting started")).not.toBeInTheDocument();
    expect(localStorage.getItem("resume-tailor-harness-getting-started-dismissed")).toBe("1");
  });
});
