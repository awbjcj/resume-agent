import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChatSessionHistory } from "./ChatSessionHistory";

describe("ChatSessionHistory", () => {
  it("keeps session selection and lifecycle actions in one reusable surface", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onRename = vi.fn();
    const onArchive = vi.fn();
    const onDelete = vi.fn();
    const onShowArchivedChange = vi.fn();

    render(
      <ChatSessionHistory
        items={[
          { id: "active", title: "Current thread", detail: "Drafting now · 2 turns", status: "active" },
          { id: "ended", title: "Completed thread", detail: "Completed · 4 turns", status: "ended" },
        ]}
        selectedId="active"
        onSelect={onSelect}
        showArchived={false}
        onShowArchivedChange={onShowArchivedChange}
        emptyMessage="No sessions"
        createLabel="New session"
        onCreate={vi.fn()}
        onRename={onRename}
        onArchive={onArchive}
        onDelete={onDelete}
      />,
    );

    await user.click(screen.getByRole("button", { name: /^Current thread/ }));
    expect(onSelect).toHaveBeenCalledWith("active");
    await user.click(screen.getByRole("checkbox", { name: "Show archived" }));
    expect(onShowArchivedChange).toHaveBeenCalledWith(true);

    await user.click(screen.getByRole("button", { name: "Actions for Current thread" }));
    await user.click(await screen.findByRole("menuitem", { name: "Rename" }));
    const title = screen.getByRole("textbox", { name: "Session title" });
    await user.clear(title);
    await user.type(title, "Better title");
    await user.click(screen.getByRole("button", { name: "Save title" }));
    expect(onRename).toHaveBeenCalledWith("active", "Better title");

    await user.click(screen.getByRole("button", { name: "Actions for Completed thread" }));
    await user.click(await screen.findByRole("menuitem", { name: "Archive" }));
    expect(onArchive).toHaveBeenCalledWith("ended");

    await user.click(screen.getByRole("button", { name: "Actions for Completed thread" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledWith("ended");
  });
});
