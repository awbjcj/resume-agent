import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { expect, it, vi } from "vitest";

import type { SuggestionState, SuggestionTarget } from "./aggregate";
import { SelectionTray } from "./SelectionTray";

const targets: SuggestionTarget[] = [
  { kind: "theme", key: "cloud:platform", label: "Cloud platform" },
  { kind: "skill", key: "c++", label: "C++" },
];

it("renders typed targets, statuses, removal, retry, and ordered generation accessibly", async () => {
  const remove = vi.fn();
  const retry = vi.fn();
  const generateAll = vi.fn();
  const stateOf = (kind: "skill" | "theme"): SuggestionState =>
    kind === "theme" ? "failed" : "ready";
  const { container } = render(
    <SelectionTray
      targets={targets}
      stateOf={stateOf}
      onRemove={remove}
      onClear={vi.fn()}
      onGenerateAll={generateAll}
      onRetry={retry}
      generating={false}
      launchError="One launch failed"
    />,
  );

  expect(screen.getAllByText("Theme").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Skill").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Failed").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Ready").length).toBeGreaterThan(0);

  const desktop = screen.getByTestId("desktop-selection-tray");
  await userEvent.click(within(desktop).getByRole("button", { name: "Retry Cloud platform" }));
  expect(retry).toHaveBeenCalledWith(targets[0]);

  await userEvent.click(within(desktop).getByRole("button", { name: "Remove C++" }));
  expect(remove).toHaveBeenCalledWith(targets[1]);

  await userEvent.click(within(desktop).getByRole("button", { name: "Generate all" }));
  expect(generateAll).toHaveBeenCalledWith(targets);

  const results = await axe(container);
  expect(results.violations).toEqual([]);
});

it("opens a titled mobile sheet from the selection action", async () => {
  render(
    <SelectionTray
      targets={targets}
      stateOf={() => "queued"}
      onRemove={vi.fn()}
      onClear={vi.fn()}
      onGenerateAll={vi.fn()}
      onRetry={vi.fn()}
      generating={false}
      launchError={null}
    />,
  );

  const trigger = screen.getByRole("button", { name: "Open selection tray" });
  await userEvent.click(trigger);
  const sheet = screen.getByRole("dialog");
  expect(within(sheet).getByRole("heading", { name: "Research selection" })).toBeInTheDocument();
  await userEvent.click(within(sheet).getByRole("button", { name: "Close" }));
  expect(trigger).toHaveFocus();
});
