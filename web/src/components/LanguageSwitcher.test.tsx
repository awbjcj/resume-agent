import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { DEFAULT_LANGUAGE, changeLanguage } from "@/i18n";
import { LanguageSwitcher } from "./LanguageSwitcher";

describe("LanguageSwitcher", () => {
  afterEach(async () => {
    await changeLanguage(DEFAULT_LANGUAGE);
  });

  it("switches the interface language", async () => {
    const user = userEvent.setup();
    render(<LanguageSwitcher />);

    await user.selectOptions(screen.getByRole("combobox", { name: "Language" }), "zh-CN");

    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: "语言" })).toHaveValue("zh-CN");
    });
  });
});
