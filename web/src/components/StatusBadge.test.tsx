import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { changeLanguage } from "@/i18n";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  afterEach(async () => {
    await changeLanguage("en");
  });

  it("uses the Chinese pipeline label instead of a raw status value", async () => {
    await changeLanguage("zh-CN");
    render(<StatusBadge status="tailored" />);

    expect(screen.getByText("已定制")).toBeInTheDocument();
    expect(screen.queryByText("tailored")).not.toBeInTheDocument();
  });

  it.each([
    ["raw", "原始"],
    ["extracted", "已提取"],
    ["filtered", "已筛除"],
    ["rejected", "已拒绝"],
    ["shortlisted", "已加入候选"],
    ["approved", "已批准"],
    ["rendered", "已生成"],
  ])("translates the %s pipeline status", async (status, label) => {
    await changeLanguage("zh-CN");
    render(<StatusBadge status={status} />);

    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
