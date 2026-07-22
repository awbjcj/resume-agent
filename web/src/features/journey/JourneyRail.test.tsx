import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";

import type { Journey } from "./use-journey";
import { JourneyRail } from "./JourneyRail";

const mocks = vi.hoisted(() => ({ journey: vi.fn<() => Journey | null>() }));
vi.mock("./use-journey", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./use-journey")>()),
  useJourney: () => mocks.journey(),
}));

const incomplete: Journey = {
  stages: [
    { id: "profile", label: "Profile", task: "Build your profile", hint: "h", cta: { label: "Build your profile", to: "/profile" }, state: "done", count: 1 },
    { id: "sources", label: "Sources", task: "Add job sources", hint: "Enable at least one source.", cta: { label: "Add sources", to: "/settings/sources" }, state: "current", count: 0 },
    { id: "pull", label: "Pull", task: "Pull your first jobs", hint: "h", cta: { label: "Pull jobs", pull: true }, state: "upcoming", count: 0 },
    { id: "shortlist", label: "Shortlist", task: "Shortlist & approve", hint: "h", cta: { label: "Review shortlist", to: "/shortlist" }, state: "upcoming", count: 0 },
    { id: "tailor", label: "Tailor", task: "Tailor a resume", hint: "h", cta: { label: "Tailor a resume", to: "/pipeline?stage=approved" }, state: "upcoming", count: 0 },
  ],
  currentStep: "sources",
  completedCount: 1,
  total: 5,
  complete: false,
};

const renderRail = () => render(<MemoryRouter><JourneyRail /></MemoryRouter>);

describe("JourneyRail", () => {
  it("renders nothing while the journey is loading", () => {
    mocks.journey.mockReturnValue(null);
    const { container } = renderRail();
    expect(container).toBeEmptyDOMElement();
  });

  it("marks the current step and surfaces its single next action", async () => {
    mocks.journey.mockReturnValue(incomplete);
    const { container } = renderRail();

    const journey = screen.getByRole("list", { name: undefined });
    expect(journey).toBeInTheDocument();
    // exactly one step is aria-current
    expect(screen.getAllByRole("listitem").filter((li) => li.getAttribute("aria-current") === "step")).toHaveLength(1);
    // the next-action bar shows the current step's hint + CTA
    expect(screen.getByText(/enable at least one source/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /add sources/i })).toHaveAttribute("href", "/settings/sources");

    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("recedes to a quiet single line once the loop is complete", () => {
    mocks.journey.mockReturnValue({
      ...incomplete,
      stages: incomplete.stages.map((s) => ({ ...s, state: "done" as const })),
      currentStep: null,
      completedCount: 5,
      complete: true,
    });
    renderRail();
    expect(screen.getByText(/running the full loop/i)).toBeInTheDocument();
    // no call-to-action once complete
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
