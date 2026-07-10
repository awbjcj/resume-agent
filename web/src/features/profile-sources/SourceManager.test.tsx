import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  sources: [
    { id: "r1", filename: "resume.pdf", mode: "literal", primary: true,
      anchor: null, addedAt: "2026-07-03", fragmentStatus: "cached" },
    { id: "d1", filename: "deck.pptx", mode: "synthesis", primary: false,
      anchor: null, addedAt: "2026-07-03", fragmentStatus: "missing" },
    { id: "n1", filename: "notes.md", mode: "literal", primary: false,
      anchor: null, addedAt: "2026-07-03", fragmentStatus: "cached" },
  ],
  skeleton: [{ id: "exp1", kind: "experience", label: "Acme — Engineer" }],
  patch: vi.fn(),
  remove: vi.fn(),
  upload: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("./use-sources", () => ({
  useSources: () => ({ data: mocks.sources, isLoading: false }),
  useSkeleton: () => ({ data: mocks.skeleton }),
  useUploadSource: () => ({ mutate: mocks.upload, isPending: false }),
  usePatchSource: () => ({ mutate: mocks.patch, isPending: false }),
  useDeleteSource: () => ({ mutate: mocks.remove, isPending: false }),
  useReplaceSource: () => ({ mutate: mocks.replace, isPending: false }),
}));

import { SourceManager } from "./SourceManager";

describe("SourceManager", () => {
  it("lists sources with mode and primary markers", () => {
    render(<SourceManager />);
    expect(screen.getByText("resume.pdf")).toBeInTheDocument();
    expect(screen.getByText("deck.pptx")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /resume\.pdf primary/i })).toBeInTheDocument();
  });

  it("gives native mode options explicit theme colors", () => {
    render(<SourceManager />);
    const options = screen.getByLabelText(/mode for deck.pptx/i).querySelectorAll("option");
    expect(options).not.toHaveLength(0);
    options.forEach((option) => {
      expect(option).toHaveClass("bg-popover", "text-popover-foreground");
    });
  });

  it("changes a source's anchor through the skeleton dropdown", async () => {
    render(<SourceManager />);
    const anchorSelect = screen.getByLabelText(/anchor for deck.pptx/i);
    await userEvent.selectOptions(anchorSelect, "exp1");
    expect(mocks.patch).toHaveBeenCalledWith({ id: "d1", anchor: "exp1" });
  });

  it("uploads with the selected mode and anchor", async () => {
    const { container } = render(<SourceManager />);
    await userEvent.selectOptions(screen.getByLabelText(/new source mode/i), "synthesis");
    await userEvent.selectOptions(screen.getByLabelText(/new source anchor/i), "exp1");

    const input = container.querySelector("input[type=file]") as HTMLInputElement;
    const file = new File(["deck"], "deck.md", { type: "text/markdown" });
    await userEvent.upload(input, file);

    expect(mocks.upload).toHaveBeenCalledWith({
      file,
      mode: "synthesis",
      anchor: "exp1",
    });
  });

  it("promotes a literal source to primary", async () => {
    render(<SourceManager />);
    await userEvent.click(screen.getByRole("button", { name: /make notes.md primary/i }));
    expect(mocks.patch).toHaveBeenCalledWith({ id: "n1", primary: true });
  });

  it("deletes a source", async () => {
    render(<SourceManager />);
    await userEvent.click(screen.getByRole("button", { name: /remove deck.pptx/i }));
    expect(mocks.remove).toHaveBeenCalledWith("d1");
  });

  it("replaces the primary resume's file", async () => {
    const { container } = render(<SourceManager />);
    await userEvent.click(screen.getByRole("button", { name: /replace resume\.pdf/i }));

    const inputs = container.querySelectorAll("input[type=file]");
    const replaceInput = inputs[inputs.length - 1] as HTMLInputElement;
    const file = new File(["resume v2"], "resume-v2.pdf", { type: "application/pdf" });
    await userEvent.upload(replaceInput, file);

    expect(mocks.replace).toHaveBeenCalledWith({ oldId: "r1", file });
  });

  it("does not offer replace/remove actions on non-primary sources", () => {
    render(<SourceManager />);
    expect(screen.queryByRole("button", { name: /replace deck.pptx/i })).not.toBeInTheDocument();
  });
});
