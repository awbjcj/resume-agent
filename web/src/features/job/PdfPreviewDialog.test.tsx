import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { clearToken, setToken } from "@/lib/api/client";
import { PdfPreviewDialog } from "./PdfPreviewDialog";

const TITLE = "Round 0 preview";

function dialog(open: boolean) {
  return (
    <PdfPreviewDialog
      open={open}
      onOpenChange={() => undefined}
      title={TITLE}
      previewPath="/api/resume-versions/7/preview"
      downloadPath="/api/resume-versions/7/pdf"
    />
  );
}

function renderDialog(open = true) {
  return render(dialog(open));
}

/** A fetch whose resolution the test schedules, so races are deterministic. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

function pdfResponse(blob: Blob) {
  return { ok: true, blob: vi.fn().mockResolvedValue(blob) } as unknown as Response;
}

function pdf(content: string) {
  return new Blob([content], { type: "application/pdf" });
}

describe("PdfPreviewDialog", () => {
  afterEach(() => {
    clearToken();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("authenticates the preview request and renders the PDF blob in an iframe", async () => {
    setToken("preview-token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(pdfResponse(pdf("%PDF"))));
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    renderDialog();

    const frame = await screen.findByTitle(TITLE);
    expect(frame).toHaveAttribute("src", "blob:preview");
    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toContain("/api/resume-versions/7/preview");
    expect(new Headers(options?.headers).get("Authorization")).toBe(
      "Bearer preview-token",
    );
  });

  it("shows the API error envelope message instead of an iframe", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        json: vi
          .fn()
          .mockResolvedValue({ error: { message: "No rendered PDF for this version" } }),
      } as unknown as Response),
    );

    renderDialog();

    expect(
      await screen.findByText("No rendered PDF for this version"),
    ).toBeInTheDocument();
    expect(screen.queryByTitle(TITLE)).not.toBeInTheDocument();
  });

  it("revokes the object URL when the dialog closes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(pdfResponse(pdf("%PDF"))));
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview");
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);

    const { rerender } = renderDialog();
    await screen.findByTitle(TITLE);

    rerender(dialog(false));

    // Deferred past the exit animation rather than revoked on the spot.
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:preview"));
  });

  it("refetches and swaps in a fresh blob when the dialog is reopened", async () => {
    const second = pdf("second");
    const secondFetch = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(pdfResponse(pdf("first")))
        .mockReturnValueOnce(secondFetch.promise),
    );
    vi.spyOn(URL, "createObjectURL").mockImplementation((source) =>
      source === second ? "blob:second" : "blob:first",
    );
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    const { rerender } = renderDialog();
    expect(await screen.findByTitle(TITLE)).toHaveAttribute("src", "blob:first");

    rerender(dialog(false));
    rerender(dialog(true));

    // Synchronous: reopening settles the deferred reset immediately rather
    // than flashing the previous PDF until the exit timer happens to fire.
    expect(screen.getByLabelText("Loading preview")).toBeInTheDocument();
    expect(screen.queryByTitle(TITLE)).not.toBeInTheDocument();

    secondFetch.resolve(pdfResponse(second));
    await waitFor(() =>
      expect(screen.getByTitle(TITLE)).toHaveAttribute("src", "blob:second"),
    );
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2);
  });

  it("clears a previous failure when the dialog is reopened", async () => {
    const retry = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce({
          ok: false,
          json: vi.fn().mockResolvedValue({ error: { message: "Preview exploded" } }),
        } as unknown as Response)
        .mockReturnValueOnce(retry.promise),
    );
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:recovered");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    const { rerender } = renderDialog();
    expect(await screen.findByRole("alert")).toHaveTextContent("Preview exploded");

    rerender(dialog(false));
    rerender(dialog(true));

    // Synchronous for the same reason: the stale failure must not survive the
    // reopen even for the length of the exit animation.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    retry.resolve(pdfResponse(pdf("recovered")));
    expect(await screen.findByTitle(TITLE)).toHaveAttribute("src", "blob:recovered");
  });

  it("ignores a stale response that resolves after the reopened one", async () => {
    const stale = pdf("stale");
    const fresh = pdf("fresh");
    const firstFetch = deferred<Response>();
    const secondFetch = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockReturnValueOnce(firstFetch.promise)
        .mockReturnValueOnce(secondFetch.promise),
    );
    vi.spyOn(URL, "createObjectURL").mockImplementation((source) =>
      source === fresh ? "blob:fresh" : "blob:stale",
    );
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);

    const { rerender } = renderDialog();
    rerender(dialog(false));
    rerender(dialog(true));

    const [, firstOptions] = vi.mocked(fetch).mock.calls[0];
    expect(firstOptions?.signal?.aborted).toBe(true);

    secondFetch.resolve(pdfResponse(fresh));
    expect(await screen.findByTitle(TITLE)).toHaveAttribute("src", "blob:fresh");

    // The abandoned request resolves last; its blob must never reach the frame.
    firstFetch.resolve(pdfResponse(stale));
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:stale"));
    expect(screen.getByTitle(TITLE)).toHaveAttribute("src", "blob:fresh");
  });
});
