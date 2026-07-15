import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  addSource: vi.fn(),
  launch: vi.fn(),
  result: {
    state: "done" as const,
    error: null,
    result: {
      scrapeAvailable: true,
      scrapeUnavailableReason: null as string | null,
      candidates: [
        {
          company: "Acme",
          url: "https://job-boards.greenhouse.io/acme",
          reason: "Matches the prompt",
          confidence: "high" as const,
          status: "validated" as const,
          ats: "greenhouse",
          token: "acme",
          roleCount: 4,
          error: null,
          errorCode: null,
        },
        {
          company: "Plain",
          url: "https://plain.example/careers",
          reason: "No supported ATS",
          confidence: "low" as const,
          status: "unverified" as const,
          ats: null,
          token: null,
          roleCount: null,
          error: null,
          errorCode: "ATS_NOT_DETECTED",
        },
      ],
    },
  },
}));

vi.mock("./use-sources", () => ({
  useAddSource: () => ({ mutateAsync: mocks.addSource, isPending: false }),
}));
vi.mock("./use-discover", () => ({
  useDiscoverCompanies: () => ({ mutateAsync: mocks.launch, isPending: false }),
  useDiscoverResult: () => mocks.result,
}));

import { DiscoverCompaniesDialog } from "./DiscoverCompaniesDialog";

describe("DiscoverCompaniesDialog", () => {
  beforeEach(() => {
    mocks.addSource.mockReset().mockResolvedValue({});
    mocks.launch.mockReset().mockResolvedValue({ runId: "run-1" });
    mocks.result.result.scrapeAvailable = true;
    mocks.result.result.scrapeUnavailableReason = null;
  });

  it("adds selected validated and scrape candidates through the existing endpoint", async () => {
    const user = userEvent.setup();
    render(<DiscoverCompaniesDialog />);
    await user.click(screen.getByRole("button", { name: /discover companies/i }));

    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("4 roles")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /select acme/i }));
    await user.click(screen.getByRole("checkbox", { name: /select plain/i }));
    await user.click(screen.getByRole("button", { name: /add selected/i }));

    await waitFor(() => expect(mocks.addSource).toHaveBeenCalledTimes(2));
    expect(mocks.addSource).toHaveBeenNthCalledWith(1, {
      provider: "auto",
      url: "https://job-boards.greenhouse.io/acme",
      label: "Acme",
      country: "com",
    });
    expect(mocks.addSource).toHaveBeenNthCalledWith(2, {
      provider: "scrape",
      url: "https://plain.example/careers",
      label: "Plain",
      country: "com",
    });
  });

  it("disables scrape approval when the runtime has no browser", async () => {
    mocks.result.result.scrapeAvailable = false;
    mocks.result.result.scrapeUnavailableReason = "Scrape targets require a local browser.";
    const user = userEvent.setup();
    render(<DiscoverCompaniesDialog />);
    await user.click(screen.getByRole("button", { name: /discover companies/i }));

    expect(screen.getByRole("checkbox", { name: /select plain/i })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getByText(/local browser/i)).toBeInTheDocument();
  });
});
