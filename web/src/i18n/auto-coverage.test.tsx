import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SalaryThresholdInput } from "@/components/SalaryThresholdInput";
import { changeLanguage } from "@/i18n";

describe("automatic interface localization", () => {
  it("translates production component copy and follows language changes", async () => {
    await changeLanguage("zh-CN");
    const { rerender } = render(
      <SalaryThresholdInput id="salary" value="" valid onChange={vi.fn()} />,
    );

    expect(screen.getByText("最低年薪（美元）")).toBeInTheDocument();
    expect(screen.getByText("不限年薪")).toBeInTheDocument();

    await changeLanguage("en");
    rerender(<SalaryThresholdInput id="salary" value="" valid onChange={vi.fn()} />);

    expect(screen.getByText("Min salary (USD)")).toBeInTheDocument();
    expect(screen.getByText("Any annual salary")).toBeInTheDocument();
  });
});
