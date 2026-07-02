import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ActionQueue, QUEUE_CARDS } from "./ActionQueue";
import { SUMMARY } from "./fixtures";

const renderQueue = (summary = SUMMARY) =>
  render(
    <MemoryRouter>
      <ActionQueue summary={summary} />
    </MemoryRouter>,
  );

describe("ActionQueue", () => {
  it("renders four cards linking to their boards", () => {
    renderQueue();
    expect(QUEUE_CARDS.map((c) => c.key)).toEqual([
      "triage",
      "approve",
      "tailor",
      "apply",
    ]);
    expect(screen.getByRole("link", { name: /triage 2/i })).toHaveAttribute(
      "href",
      "/triage",
    );
    expect(screen.getByRole("link", { name: /approve 4/i })).toHaveAttribute(
      "href",
      "/shortlist",
    );
    expect(screen.getByRole("link", { name: /tailor 1/i })).toHaveAttribute(
      "href",
      "/pipeline?stage=approved",
    );
    expect(screen.getByRole("link", { name: /apply 1/i })).toHaveAttribute(
      "href",
      "/pipeline?stage=rendered",
    );
  });

  it("keeps zero-count cards visible", () => {
    renderQueue({
      ...SUMMARY,
      queues: { triage: 0, approve: 0, tailor: 0, apply: 0 },
    });
    expect(screen.getAllByRole("link")).toHaveLength(4);
  });
});
