import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { RefreshClustersButton } from "./RefreshClustersButton";

describe("RefreshClustersButton", () => {
  it("shows launch failure and resets the busy state", async () => {
    render(
      <RefreshClustersButton
        unassignedCount={3}
        onRegroup={async () => false}
        onMaintain={async () => true}
        canUndo={false}
        onUndo={async () => true}
        maintenanceDue
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /regroup unassigned/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(/couldn't start/i);
    expect(screen.getByRole("button", { name: /regroup unassigned/i })).toBeEnabled();
  });

  it("disables regroup at zero while leaving maintenance available", () => {
    render(
      <RefreshClustersButton
        unassignedCount={0}
        onRegroup={async () => true}
        onMaintain={async () => true}
        canUndo={false}
        onUndo={async () => true}
        maintenanceDue={false}
      />,
    );

    expect(screen.getByRole("button", { name: "Regroup unassigned (0)" })).toBeDisabled();
    // Named for what it does: this action reorganizes domains and cannot
    // assign an unassigned skill, which "Maintain taxonomy" implied it could.
    expect(screen.getByRole("button", { name: "Reorganize domains" })).toBeEnabled();
  });
});
