import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SecretsForm } from "./SecretsForm";

const STATUSES = [
  { key: "anthropicApiKey", isSet: true, hint: "cd12" },
  { key: "openaiApiKey", isSet: false, hint: null },
];

describe("SecretsForm", () => {
  it("shows hint for set keys and never a value input by default", () => {
    render(<SecretsForm statuses={STATUSES} saving={false} onSave={vi.fn()} />);
    expect(screen.getByText(/cd12/)).toBeInTheDocument();
    expect(screen.queryAllByLabelText(/new value/i)).toHaveLength(0);
  });

  it("saves a newly entered key", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(<SecretsForm statuses={STATUSES} saving={false} onSave={onSave} />);
    await user.click(screen.getByRole("button", { name: "Add OpenAI API key" }));
    await user.type(screen.getByLabelText("OpenAI API key new value"), "sk-oai-123");
    await user.click(screen.getByRole("button", { name: "Save key" }));
    expect(onSave).toHaveBeenCalledWith({ openaiApiKey: "sk-oai-123" });
  });

  it("clears a set key with null", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(<SecretsForm statuses={STATUSES} saving={false} onSave={onSave} />);
    await user.click(screen.getByRole("button", { name: "Clear Anthropic API key" }));
    expect(onSave).toHaveBeenCalledWith({ anthropicApiKey: null });
  });

  it("shows a readable label, description, and plain-text input for the Google OAuth client ID", async () => {
    const user = userEvent.setup();
    render(
      <SecretsForm
        statuses={[
          { key: "googleOauthClientId", isSet: false, hint: null },
          { key: "googleOauthClientSecret", isSet: false, hint: null },
        ]}
        saving={false}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByText("Google OAuth client ID")).toBeInTheDocument();
    expect(screen.getByText("Google OAuth client secret")).toBeInTheDocument();
    expect(screen.queryByText("googleOauthClientId")).not.toBeInTheDocument();
    expect(screen.getByText(/Web application OAuth client/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add Google OAuth client ID" }));
    expect(screen.getByLabelText("Google OAuth client ID new value")).toHaveAttribute(
      "type",
      "text",
    );
  });
});
