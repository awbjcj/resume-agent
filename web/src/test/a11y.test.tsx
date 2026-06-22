import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";

import { server } from "./server";
import { ShortlistContainer } from "@/features/shortlist/ShortlistContainer";

const wrap = (ui: ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("a11y", () => {
  it("shortlist (empty) has no axe violations", async () => {
    server.use(
      http.get("/api/shortlist", () =>
        HttpResponse.json({
          data: [],
          pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 0 },
        }),
      ),
    );
    const { container, findByText } = wrap(<ShortlistContainer />);
    await findByText(/nothing shortlisted yet/i);
    // Assert on results directly (vitest-axe's toHaveNoViolations matcher type
    // augmentation targets the old Vi namespace, incompatible with vitest 4).
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
