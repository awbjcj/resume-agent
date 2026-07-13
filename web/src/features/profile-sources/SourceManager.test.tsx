import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  sources: [
    { id: "r1", filename: "resume.pdf", mode: "literal", primary: true,
      anchor: null, addedAt: "2026-07-03", fragmentStatus: "cached", origin: "upload" },
    { id: "d1", filename: "deck.pptx", mode: "synthesis", primary: false,
      anchor: null, addedAt: "2026-07-03", fragmentStatus: "missing", origin: "upload" },
    { id: "n1", filename: "notes.md", mode: "literal", primary: false,
      anchor: null, addedAt: "2026-07-03", fragmentStatus: "cached", origin: "upload" },
    { id: "g1", filename: "github--repo.md", mode: "project", primary: false,
      anchor: null, addedAt: "2026-07-03", fragmentStatus: "cached", origin: "github" },
    { id: "p1", filename: "portfolio-dossier.md", mode: "project", primary: false,
      anchor: null, addedAt: "2026-07-03", fragmentStatus: "cached", origin: "upload" },
  ],
  skeleton: [{ id: "exp1", kind: "experience", label: "Acme — Engineer" }],
  patch: vi.fn(),
  remove: vi.fn(),
  uploadAll: vi.fn(),
  replace: vi.fn(),
  addNote: vi.fn(),
  addUrl: vi.fn(),
  syncGithub: vi.fn(),
}));

vi.mock("./use-sources", () => ({
  useSources: () => ({ data: mocks.sources, isLoading: false }),
  useSkeleton: () => ({ data: mocks.skeleton }),
  useUploadSources: () => ({ uploadAll: mocks.uploadAll }),
  usePatchSource: () => ({ mutate: mocks.patch, isPending: false }),
  useDeleteSource: () => ({ mutate: mocks.remove, isPending: false }),
  useReplaceSource: () => ({ mutate: mocks.replace, isPending: false }),
  useAddNote: () => ({ mutate: mocks.addNote, isPending: false }),
  useAddUrl: () => ({ mutate: mocks.addUrl, isPending: false }),
  useSyncGithub: () => ({ mutate: mocks.syncGithub, isPending: false }),
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

    expect(mocks.uploadAll).toHaveBeenCalledWith([file], "synthesis", "exp1");
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

  it("badges github sources and keeps project mode read-only", () => {
    render(<SourceManager />);
    const row = screen.getByRole("row", { name: /github--repo\.md/i });
    expect(row).toHaveTextContent("GitHub");
    expect(row).toHaveTextContent("Synced");
    expect(screen.queryByLabelText(/mode for github--repo\.md/i)).not.toBeInTheDocument();

    const dossier = screen.getByRole("row", { name: /portfolio-dossier\.md/i });
    expect(dossier).toHaveTextContent("Read-only");
    expect(dossier).not.toHaveTextContent("GitHub");
    expect(screen.queryByRole("button", { name: /remove github--repo\.md/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove portfolio-dossier\.md/i })).toBeInTheDocument();
  });

  it("submits note and URL intake through labelled dialogs", async () => {
    const user = userEvent.setup();
    render(<SourceManager />);

    await user.click(screen.getByRole("button", { name: /add note/i }));
    await user.type(screen.getByLabelText("Note title"), "On-call");
    await user.type(screen.getByLabelText("Note text"), "Led the rotation.");
    await user.click(screen.getByRole("button", { name: /save note/i }));
    expect(mocks.addNote).toHaveBeenCalledWith(
      { title: "On-call", text: "Led the rotation." },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
    act(() => mocks.addNote.mock.calls[0][1].onSuccess());

    await waitFor(() => expect(screen.getByRole("button", { name: /add url/i })).toBeVisible());
    await user.click(screen.getByRole("button", { name: /add url/i }));
    await user.type(screen.getByLabelText("Public URL"), "https://example.com/work");
    await user.click(screen.getByRole("button", { name: /ingest page/i }));
    expect(mocks.addUrl).toHaveBeenCalledWith(
      { url: "https://example.com/work" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("launches tracked github sync", async () => {
    render(<SourceManager />);
    await userEvent.click(screen.getByRole("button", { name: /sync github/i }));
    expect(mocks.syncGithub).toHaveBeenCalledTimes(1);
  });
});
