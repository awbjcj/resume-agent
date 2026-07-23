import { afterEach, describe, expect, it, vi } from "vitest";

import { clearToken, setToken } from "@/lib/api/client";
import { openTemplatePreview } from "./use-render-templates";

describe("openTemplatePreview", () => {
  afterEach(() => {
    clearToken();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("reserves a window synchronously and authenticates the preview request", async () => {
    setToken("preview-token");
    const replace = vi.fn();
    const close = vi.fn();
    const previewWindow = { opener: window, location: { replace }, close };
    const open = vi.spyOn(window, "open").mockReturnValue(previewWindow as never);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        blob: vi.fn().mockResolvedValue(new Blob(["%PDF"], { type: "application/pdf" })),
      } as unknown as Response),
    );
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    const pending = openTemplatePreview("custom:mine");
    expect(open).toHaveBeenCalledWith("about:blank", "_blank");
    await pending;

    const [, options] = vi.mocked(fetch).mock.calls[0];
    expect(new Headers(options?.headers).get("Authorization")).toBe(
      "Bearer preview-token",
    );
    expect(replace).toHaveBeenCalledWith("blob:preview");
    expect(close).not.toHaveBeenCalled();
  });
});
