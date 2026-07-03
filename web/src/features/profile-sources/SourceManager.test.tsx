import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  sources: [
    { id: "r1", filename: "resume.pdf", mode: "literal", primary: true,
      anchor: null, addedAt: "2026-07-03", fragmentStatus: "cached" },
    { id: "d1", filename: "deck.pptx", mode: "synthesis", primary: false,
      anchor: null, addedAt: "2026-07-03", fragmentStatus: "missing" },
  ],
  skeleton: [{ id: "exp1", kind: "experience", label: "Acme — Engineer" }],
  patch: vi.fn(),
  remove: vi.fn(),
  upload: vi.fn(),
}));

vi.mock("./use-sources", () => ({
  useSources: () => ({ data: mocks.sources, isLoading: false }),
  useSkeleton: () => ({ data: mocks.skeleton }),
  useUploadSource: () => ({ mutate: mocks.upload, isPending: false }),
  usePatchSource: () => ({ mutate: mocks.patch, isPending: false }),
  useDeleteSource: () => ({ mutate: mocks.remove, isPending: false }),
}));

import { SourceManager } from "./SourceManager";

describe("SourceManager", () => {
  it("lists sources with mode and primary markers", () => {
    render(<SourceManager />);
    expect(screen.getByText("resume.pdf")).toBeInTheDocument();
    expect(screen.getByText("deck.pptx")).toBeInTheDocument();
    expect(screen.getByText(/primary/i)).toBeInTheDocument();
  });

  it("changes a source's anchor through the skeleton dropdown", async () => {
    render(<SourceManager />);
    const anchorSelect = screen.getByLabelText(/anchor for deck.pptx/i);
    await userEvent.selectOptions(anchorSelect, "exp1");
    expect(mocks.patch).toHaveBeenCalledWith({ id: "d1", anchor: "exp1" });
  });

  it("deletes a source", async () => {
    render(<SourceManager />);
    await userEvent.click(screen.getByRole("button", { name: /remove deck.pptx/i }));
    expect(mocks.remove).toHaveBeenCalledWith("d1");
  });
});
