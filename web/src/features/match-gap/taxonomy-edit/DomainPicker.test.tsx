import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { DomainPicker } from "./DomainPicker";

const categories = [{ slug: "engineering", label: "Engineering", kind: "hard" as const }];
const categoryRows = [{ slug: "engineering", label: "Engineering", kind: "hard" as const, score: 1, jobCount: 1, skillCount: 0, gapCount: 0, adjacentCount: 0, domains: [{ id: "backend", label: "Backend", category: "engineering", score: 1, jobCount: 1, skillCount: 0, gapCount: 0, adjacentCount: 0, skills: [] }] }];

it("switches between grouped existing domains and a new-domain form", async () => {
  const onNewDomainChange = vi.fn();
  const { rerender } = render(<DomainPicker categoryRows={categoryRows} categories={categories} domainId="" newDomain={null} onDomainIdChange={vi.fn()} onNewDomainChange={onNewDomainChange} />);
  expect(screen.getByText("Domain")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "New domain…" }));
  expect(onNewDomainChange).toHaveBeenCalledWith({ label: "", category: "" });
  rerender(<DomainPicker categoryRows={categoryRows} categories={categories} domainId="" newDomain={{ label: "", category: "" }} onDomainIdChange={vi.fn()} onNewDomainChange={onNewDomainChange} />);
  expect(screen.getByLabelText("New domain label")).toBeInTheDocument();
});
