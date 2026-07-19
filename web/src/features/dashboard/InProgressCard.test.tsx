import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { InProgressCard } from "./InProgressCard";
import { SUMMARY } from "./fixtures";

describe("InProgressCard", () => {
  it("lists active interviews and the coach session", () => {
    render(<MemoryRouter><InProgressCard summary={{ ...SUMMARY, activeInterviews: [{ sessionId: "s1", jobId: 1, company: "Acme", title: "SWE", askedCount: 3, questionCount: 8, startedAt: "2026-07-18T12:00:00Z", endedAt: null, status: "active", overallScore: null, archivedAt: null }], activeCoachSession: { sessionId: "c1", status: "active", startedAt: "2026-07-18T12:00:00Z", endedAt: null, topicCount: 4, savedNoteCount: 1, archivedAt: null } }} /></MemoryRouter>);
    expect(screen.getByText("Acme · SWE")).toBeInTheDocument();
    expect(screen.getByText(/Question 3 of 8/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /resume acme/i })).toHaveAttribute("href", "/interview?session=s1");
    expect(screen.getByText("Profile coaching in progress")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /resume profile coaching/i })).toHaveAttribute("href", "/coach");
  });

  it("renders a quiet empty line when nothing is in progress", () => {
    render(<MemoryRouter><InProgressCard summary={SUMMARY} /></MemoryRouter>);
    expect(screen.getByText(/Nothing in progress/i)).toBeInTheDocument();
  });
});
