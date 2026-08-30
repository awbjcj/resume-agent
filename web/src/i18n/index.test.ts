import { afterEach, describe, expect, it } from "vitest";

import autoCatalog from "./auto-catalog.json";
import autoZhCN from "./auto-zh-CN.json";
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

  it("keeps workspace product names consistent in navigation and generated copy", async () => {
    await changeLanguage("zh-CN");

    const terms = [
      { navKey: "nav.profileCoach", english: /Profile Coach/, chinese: "个人资料教练" },
      { navKey: "nav.mockInterviews", english: /Mock interviews?/i, chinese: "模拟面试" },
      { navKey: "nav.careerLab", english: /Career Lab/, chinese: "职业实验室" },
      { navKey: "nav.discoveryScout", english: /Scout/, chinese: "职位探索助手" },
    ] as const;

    for (const term of terms) {
      expect(i18n.t(term.navKey)).toBe(term.chinese);
      const translated = Object.values(autoCatalog)
        .filter((entry) => term.english.test(entry.en))
        .map((entry) => autoZhCN[entry.key as keyof typeof autoZhCN]);

      expect(translated.length).toBeGreaterThan(0);
      expect(translated.every((value) => value.includes(term.chinese))).toBe(true);
    }
  });
});
