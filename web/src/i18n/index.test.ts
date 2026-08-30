import { afterEach, describe, expect, it } from "vitest";

import i18n, {
  changeLanguage,
  DEFAULT_LANGUAGE,
  LANGUAGE_STORAGE_KEY,
  normalizeLanguage,
  resolveInitialLanguage,
} from "./index";

describe("i18n locale resolution", () => {
  afterEach(async () => {
    localStorage.clear();
    await changeLanguage(DEFAULT_LANGUAGE);
  });

  it.each([
    ["en", "en"],
    ["en-US", "en"],
    ["zh", "zh-CN"],
    ["zh-Hans-CN", "zh-CN"],
    ["fr", null],
    [null, null],
  ] as const)("normalizes %s", (input, expected) => {
    expect(normalizeLanguage(input)).toBe(expected);
  });

  it("prefers a supported stored language, then the browser languages", () => {
    expect(resolveInitialLanguage("zh-CN", ["en-US"])).toBe("zh-CN");
    expect(resolveInitialLanguage("fr", ["fr-FR", "zh-TW", "en-US"])).toBe("zh-CN");
    expect(resolveInitialLanguage("fr", ["de-DE"])).toBe("en");
  });

  it("persists changes and synchronizes the document language", async () => {
    await changeLanguage("zh-CN");

    expect(i18n.t("nav.dashboard")).toBe("仪表盘");
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("zh-CN");
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(document.documentElement.dir).toBe("ltr");
    expect(document.title).toBe("求职助手");
  });
});
