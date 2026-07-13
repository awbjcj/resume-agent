import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, it } from "vitest";

import { server } from "@/test/server";
import { ImportJobsDialog } from "./ImportJobsDialog";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
  );
}

it("shows the report and row errors after a CSV import", async () => {
  server.use(
    http.post("/api/jobs/import", () =>
      HttpResponse.json({
        added: 1,
        upgraded: 0,
        skipped: 0,
        errors: [{ row: 2, reason: "jd_text is required" }],
      }),
    ),
  );
  render(<ImportJobsDialog open onOpenChange={() => undefined} />, { wrapper });

  await userEvent.upload(
    screen.getByLabelText(/import file/i),
    new File(["title,company\n"], "jobs.csv", { type: "text/csv" }),
  );
  await userEvent.click(screen.getByRole("button", { name: /^import$/i }));

  await waitFor(() => expect(screen.getByText(/1 added/i)).toBeInTheDocument());
  expect(screen.getByText(/row 2.*jd_text is required/i)).toBeInTheDocument();
});
