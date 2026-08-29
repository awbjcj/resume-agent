import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EventFormDialog } from "./EventFormDialog";

describe("EventFormDialog", () => {
  it("submits a minimal all-day event", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<EventFormDialog trigger={<button>Add event</button>} onSubmit={onSubmit} />);
    await user.click(screen.getByRole("button", { name: "Add event" }));
    await user.type(screen.getByLabelText(/^date$/i), "2026-03-09");
    await user.click(screen.getByRole("button", { name: /^save event$/i }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "application_submitted",
        occurredAt: expect.stringContaining("2026-03-09"),
        allDay: true,
      }),
    );
  });

  it("requires a custom label", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<EventFormDialog trigger={<button>Add event</button>} onSubmit={onSubmit} />);
    await user.click(screen.getByRole("button", { name: "Add event" }));
    await user.selectOptions(screen.getByLabelText(/stage/i), "custom");
    await user.click(screen.getByRole("button", { name: /^save event$/i }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/label is required/i)).toBeInTheDocument();
  });

  it("reveals offer compensation fields", async () => {
    const user = userEvent.setup();
    render(<EventFormDialog trigger={<button>Add event</button>} onSubmit={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Add event" }));
    expect(screen.queryByLabelText(/base salary/i)).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/stage/i), "offer_received");
    expect(screen.getByLabelText(/base salary/i)).toBeInTheDocument();
  });

  it("prefills an existing event", async () => {
    const user = userEvent.setup();
    render(
      <EventFormDialog
        trigger={<button>Edit event</button>}
        event={{
          id: 1,
          kind: "technical_round",
          notes: "LRU cache",
          occurredAt: "2026-03-09T19:00:00Z",
          allDay: false,
        } as never}
        onSubmit={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Edit event" }));
    expect(screen.getByLabelText(/notes/i)).toHaveValue("LRU cache");
  });

  it("shows only a persisted manual round override in the sequence field", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <EventFormDialog
        trigger={<button>Edit auto event</button>}
        event={{
          id: 1,
          kind: "technical_round",
          sequence: 3,
          sequenceOverride: null,
          occurredAt: "2026-03-09T19:00:00Z",
          allDay: false,
        } as never}
        onSubmit={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Edit auto event" }));
    expect(screen.getByLabelText(/round number/i)).toHaveValue(null);
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    rerender(
      <EventFormDialog
        trigger={<button>Edit manual event</button>}
        event={{
          id: 2,
          kind: "technical_round",
          sequence: 3,
          sequenceOverride: 9,
          occurredAt: "2026-03-09T19:00:00Z",
          allDay: false,
        } as never}
        onSubmit={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Edit manual event" }));
    expect(screen.getByLabelText(/round number/i)).toHaveValue(9);
  });

  it("prefills an all-day event with its stored calendar date", async () => {
    const user = userEvent.setup();
    render(
      <EventFormDialog
        trigger={<button>Edit all-day event</button>}
        event={{
          id: 2,
          kind: "offer_deadline",
          occurredAt: "2026-03-09T00:00:00Z",
          allDay: true,
        } as never}
        onSubmit={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Edit all-day event" }));
    expect(screen.getByLabelText(/^date$/i)).toHaveValue("2026-03-09");
  });

  it("shows a validation error for an invalid timed-event timezone", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<EventFormDialog trigger={<button>Add timed event</button>} onSubmit={onSubmit} />);
    await user.click(screen.getByRole("button", { name: "Add timed event" }));
    await user.type(screen.getByLabelText(/^date$/i), "2026-03-09");
    await user.click(screen.getByRole("checkbox", { name: /all day/i }));
    await user.clear(screen.getByLabelText(/timezone/i));
    await user.type(screen.getByLabelText(/timezone/i), "Mars/Olympus");
    await user.click(screen.getByRole("button", { name: /^save event$/i }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/valid IANA timezone/i);
  });

  it("rejects a nonexistent spring-forward wall time without submitting", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<EventFormDialog trigger={<button>Add timed event</button>} onSubmit={onSubmit} />);
    await user.click(screen.getByRole("button", { name: "Add timed event" }));
    await user.type(screen.getByLabelText(/^date$/i), "2026-03-08");
    await user.click(screen.getByRole("checkbox", { name: /all day/i }));
    await user.clear(screen.getByLabelText(/^time$/i));
    await user.type(screen.getByLabelText(/^time$/i), "02:30");
    await user.clear(screen.getByLabelText(/timezone/i));
    await user.type(screen.getByLabelText(/timezone/i), "America/New_York");
    await user.click(screen.getByRole("button", { name: /^save event$/i }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/does not exist/i);
  });

  it("persists the effective browser timezone when a timed timezone is cleared", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<EventFormDialog trigger={<button>Add timed event</button>} onSubmit={onSubmit} />);
    await user.click(screen.getByRole("button", { name: "Add timed event" }));
    await user.type(screen.getByLabelText(/^date$/i), "2026-03-09");
    await user.click(screen.getByRole("checkbox", { name: /all day/i }));
    await user.clear(screen.getByLabelText(/timezone/i));
    await user.click(screen.getByRole("button", { name: /^save event$/i }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      }),
    );
  });

  it("keeps the completed draft open when saving fails", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockRejectedValue(new Error("Server unavailable"));
    render(<EventFormDialog trigger={<button>Add event</button>} onSubmit={onSubmit} />);
    await user.click(screen.getByRole("button", { name: "Add event" }));
    await user.type(screen.getByLabelText(/^date$/i), "2026-03-09");
    await user.type(screen.getByLabelText(/notes/i), "Keep this draft");
    await user.click(screen.getByRole("button", { name: /^save event$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Server unavailable");
    expect(screen.getByLabelText(/notes/i)).toHaveValue("Keep this draft");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
