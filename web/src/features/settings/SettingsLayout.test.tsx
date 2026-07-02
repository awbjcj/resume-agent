import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { SettingsLayout, SETTINGS_NAV } from "./SettingsLayout";

describe("SettingsLayout", () => {
  it("renders one nav link per settings area", () => {
    render(
      <MemoryRouter initialEntries={["/settings/search"]}>
        <Routes>
          <Route path="/settings" element={<SettingsLayout />}>
            <Route path="search" element={<div>search page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    for (const item of SETTINGS_NAV) {
      expect(screen.getByRole("link", { name: item.label })).toBeInTheDocument();
    }
    expect(screen.getByText("search page")).toBeInTheDocument();
  });
});
