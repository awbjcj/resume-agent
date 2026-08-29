import { Languages } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  changeLanguage,
  normalizeLanguage,
  type SupportedLanguage,
} from "@/i18n";

const languageOptions: {
  value: SupportedLanguage;
  labelKey: "common.english" | "common.chinese";
}[] = [
  { value: "en", labelKey: "common.english" },
  { value: "zh-CN", labelKey: "common.chinese" },
];

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  const currentLanguage = normalizeLanguage(i18n.resolvedLanguage ?? i18n.language) ?? "en";

  return (
    <label className="relative inline-flex shrink-0 items-center">
      <span className="sr-only">{t("common.language")}</span>
      <Languages
        className="pointer-events-none absolute left-2.5 size-4 text-muted-foreground"
        aria-hidden="true"
      />
      <select
        className="h-10 appearance-none rounded-lg border border-transparent bg-transparent py-1 pl-8 pr-2 text-sm font-medium text-foreground outline-none transition-colors hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        aria-label={t("common.language")}
        value={currentLanguage}
        onChange={(event) => void changeLanguage(event.target.value as SupportedLanguage)}
      >
        {languageOptions.map((option) => (
          <option key={option.value} value={option.value} lang={option.value}>
            {t(option.labelKey)}
          </option>
        ))}
      </select>
    </label>
  );
}
