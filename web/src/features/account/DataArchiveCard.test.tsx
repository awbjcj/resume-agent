import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DataArchiveCard } from "./DataArchiveCard";

describe("DataArchiveCard", () => {
  it("gates a selected archive behind typed destructive confirmation", async () => {
    render(
      <DataArchiveCard
        title="My workspace data"
        description="Export and restore this workspace."
        exportLabel="Export my data"
        exportPath="/api/account/export"
        importPath="/api/account/import"
        successMessage="Workspace imported"
      />,
    );

    expect(screen.getByRole("button", { name: "Export my data" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Import archive" }));
    const confirm = screen.getByLabelText(/type replace/i);
    const submit = screen.getByRole("button", { name: "Replace data" });
    expect(submit).toBeDisabled();
    await userEvent.upload(
      screen.getByLabelText(/archive file/i),
      new File(["archive"], "workspace.tar.gz", { type: "application/gzip" }),
    );
    await userEvent.type(confirm, "REPLACE");
    expect(submit).toBeEnabled();
  });
});
