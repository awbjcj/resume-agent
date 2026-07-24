import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { emptyFilterState } from "@/lib/filters/types";

import { TriageFilters } from "./TriageFilters";

describe("TriageFilters", () => {
  it("submits bounded text filters without exposing fit controls", () => {
    const filter = emptyFilterState();
    const onChange = vi.fn();

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <TriageFilters
          filter={filter}
          facets={{ status: { raw: 2, rejected: 3 }, source: { adzuna: 5 } }}
          total={5}
          archived={false}
          onArchivedChange={vi.fn()}
          onChange={onChange}
        />
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByRole("searchbox", { name: "Search" }), {
      target: { value: "designer" },
    });
    fireEvent.change(screen.getByRole("searchbox", { name: "Rejection reason" }), {
      target: { value: "sponsorship" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(onChange).toHaveBeenCalledWith({
      ...filter,
      q: "designer",
      rejectReason: "sponsorship",
    });
    expect(screen.getByRole("button", { name: "Status" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Source" })).toBeInTheDocument();
    expect(screen.getByLabelText("Posted age")).toBeInTheDocument();
    expect(screen.queryByText(/low fit/i)).not.toBeInTheDocument();

    const searchField = screen.getByRole("searchbox", { name: "Search" })
      .closest('[data-slot="field"]');
    const reasonField = screen.getByRole("searchbox", { name: "Rejection reason" })
      .closest('[data-slot="field"]');
    expect(searchField?.parentElement).toBe(reasonField?.parentElement);
    expect(searchField).toHaveClass("sm:flex-1");
    expect(reasonField).toHaveClass("sm:flex-1");
  });

  it("resyncs text drafts when committed URL filters change", () => {
    const filter = emptyFilterState();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const view = render(
      <QueryClientProvider client={queryClient}>
        <TriageFilters
          filter={filter}
          facets={{}}
          total={0}
          archived={false}
          onArchivedChange={vi.fn()}
          onChange={vi.fn()}
        />
      </QueryClientProvider>,
    );
    fireEvent.change(screen.getByRole("searchbox", { name: "Search" }), {
      target: { value: "uncommitted" },
    });

    view.rerender(
      <QueryClientProvider client={queryClient}>
        <TriageFilters
          filter={{ ...filter, q: "from-history", rejectReason: "salary" }}
          facets={{}}
          total={0}
          archived={false}
          onArchivedChange={vi.fn()}
          onChange={vi.fn()}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue(
      "from-history",
    );
    expect(
      screen.getByRole("searchbox", { name: "Rejection reason" }),
    ).toHaveValue("salary");
  });
});
