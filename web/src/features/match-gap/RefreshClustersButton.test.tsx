import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { RefreshClustersButton } from "./RefreshClustersButton";

describe("RefreshClustersButton", () => {
  it("shows launch failure and resets the busy state", async () => {
    render(<RefreshClustersButton stale onRefresh={async () => false} />);

    await userEvent.click(screen.getByRole("button", { name: /refresh.*clusters/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(/couldn't start/i);
    expect(screen.getByRole("button", { name: /refresh.*clusters/i })).toBeEnabled();
  });
});
