import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("fires onConfirm only after the confirm action", async () => {
    const onConfirm = vi.fn();

    render(
      <ConfirmDialog
        trigger={<button>Delete</button>}
        title="Delete job?"
        description="This cannot be undone."
        confirmLabel="Confirm delete"
        onConfirm={onConfirm}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: /confirm delete/i }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
