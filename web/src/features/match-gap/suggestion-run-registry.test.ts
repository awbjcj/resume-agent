import { beforeEach, expect, it } from "vitest";

import { useRunStore } from "@/lib/runs/store";
import {
  effectiveSuggestionState,
  useSuggestionRunRegistry,
} from "./suggestion-run-registry";

const target = { kind: "skill" as const, key: "python", label: "Python" };

beforeEach(() => {
  useRunStore.setState({ runs: {} });
  useSuggestionRunRegistry.setState({ entries: {}, launchError: null });
});

it("tracks one run by typed target and keeps failure retryable", () => {
  useSuggestionRunRegistry.getState().register(target, "r1");
  useSuggestionRunRegistry.getState().fail(target, "Research failed");

  expect(useSuggestionRunRegistry.getState().entryFor(target)).toEqual(
    expect.objectContaining({ state: "failed", error: "Research failed" }),
  );
  expect(
    effectiveSuggestionState(
      "ready",
      useSuggestionRunRegistry.getState().entryFor(target),
      undefined,
    ),
  ).toBe("failed");
});

it("uses live run state before persisted status", () => {
  useSuggestionRunRegistry.getState().register(target, "r1");

  expect(
    effectiveSuggestionState(
      "ready",
      useSuggestionRunRegistry.getState().entryFor(target),
      "running",
    ),
  ).toBe("researching");
});

it("keeps a retained synchronization failure visible after the run succeeds", () => {
  useSuggestionRunRegistry.getState().register(target, "r1");
  useSuggestionRunRegistry.getState().fail(target, "Refresh failed");

  expect(
    effectiveSuggestionState(
      undefined,
      useSuggestionRunRegistry.getState().entryFor(target),
      "succeeded",
    ),
  ).toBe("failed");
});
