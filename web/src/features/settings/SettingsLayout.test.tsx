import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { SETTINGS_GROUPS, SETTINGS_NAV, SettingsLayout } from "./SettingsLayout";

describe("SettingsLayout", () => {
  it("renders one nav link per settings area, bucketed into labelled groups", () => {
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
      expect(screen.getAllByRole("link", { name: item.label })).toHaveLength(2);
    }
    for (const group of SETTINGS_GROUPS) {
      expect(screen.getByText(group.label)).toBeInTheDocument();
    }
    expect(screen.getByText("search page")).toBeInTheDocument();
  });

  it("no longer surfaces the relocated profile tab", () => {
    expect(SETTINGS_NAV.some((i) => i.to === "/settings/profile")).toBe(false);
  });
});
