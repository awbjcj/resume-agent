import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { DocumentManager } from "./DocumentManager";

const DOCS = [{ id: "abc123", filename: "resume.pdf", docType: "resume",
  sizeBytes: 1234, uploadedAt: "2026-07-01T00:00:00+00:00" }];

describe("DocumentManager", () => {
  it("lists documents with their type", async () => {
    server.use(http.get("/api/profile/documents", () => HttpResponse.json(DOCS)));
    render(<DocumentManager />, { wrapper: withQueryClient });
    await waitFor(() => expect(screen.getByText("resume.pdf")).toBeInTheDocument());
    // "resume" also appears as the upload-type selector's default value, so
    // scope the assertion to the table row's type badge.
    const row = screen.getByText("resume.pdf").closest("tr")!;
    expect(within(row).getByText("resume")).toBeInTheDocument();
  });

  it("uploads a chosen file with the selected type", async () => {
    // The mock GET must reflect the POST's effect (like a real backend) —
    // useUploadDocument invalidates the list query, which refetches GET.
    let docs = DOCS;
    server.use(
      http.get("/api/profile/documents", () => HttpResponse.json(docs)),
      http.post("/api/profile/documents", () => {
        const newDoc = { id: "new456", filename: "transcript.pdf", docType: "transcript",
          sizeBytes: 99, uploadedAt: "2026-07-01T01:00:00+00:00" };
        docs = [...docs, newDoc];
        return HttpResponse.json(newDoc, { status: 201 });
      }),
    );

    const user = userEvent.setup();
    render(<DocumentManager />, { wrapper: withQueryClient });
    await waitFor(() => screen.getByText("resume.pdf"));
    const input = screen.getByTestId("file-input") as HTMLInputElement;
    await user.upload(input, new File(["x"], "transcript.pdf", { type: "application/pdf" }));
    await waitFor(() => expect(screen.getByText("transcript.pdf")).toBeInTheDocument());
  });

  it("deletes a document after confirming", async () => {
    let docs = DOCS;
    server.use(
      http.get("/api/profile/documents", () => HttpResponse.json(docs)),
      http.delete("/api/profile/documents/abc123", () => {
        docs = docs.filter((d) => d.id !== "abc123");
        return new HttpResponse(null, { status: 204 });
      }),
    );

    const user = userEvent.setup();
    render(<DocumentManager />, { wrapper: withQueryClient });
    await waitFor(() => screen.getByText("resume.pdf"));
    await user.click(screen.getByRole("button", { name: "Delete resume.pdf" }));
    await user.click(screen.getByRole("button", { name: "Delete document" }));
    await waitFor(() => expect(screen.queryByText("resume.pdf")).not.toBeInTheDocument());
  });
});
