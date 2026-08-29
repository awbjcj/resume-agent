import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { resources } from "./resources";

export const supportedLanguages = ["en", "zh-CN"] as const;
export type SupportedLanguage = (typeof supportedLanguages)[number];

export const LANGUAGE_STORAGE_KEY = "resume-agent-language";
export const DEFAULT_LANGUAGE: SupportedLanguage = "en";

export function normalizeLanguage(language: string | null | undefined): SupportedLanguage | null {
  if (!language) return null;
  const normalized = language.trim().toLowerCase();
  if (normalized === "en" || normalized.startsWith("en-")) return "en";
  if (normalized === "zh" || normalized.startsWith("zh-")) return "zh-CN";
  return null;
}

export function resolveInitialLanguage(
  storedLanguage?: string | null,
  browserLanguages: readonly string[] = [],
): SupportedLanguage {
  const stored = normalizeLanguage(storedLanguage);
  if (stored) return stored;
  for (const language of browserLanguages) {
    const resolved = normalizeLanguage(language);
    if (resolved) return resolved;
  }
  return DEFAULT_LANGUAGE;
}

function getInitialLanguage(): SupportedLanguage {
  if (typeof window === "undefined") return DEFAULT_LANGUAGE;
  let storedLanguage: string | null = null;
  try {
    storedLanguage = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
  } catch {
    // Storage can be unavailable in privacy-restricted browser contexts.
  }
  return resolveInitialLanguage(storedLanguage, navigator.languages);
}

function syncDocumentLanguage(language: string): void {
  if (typeof document === "undefined") return;
  document.documentElement.lang = normalizeLanguage(language) ?? DEFAULT_LANGUAGE;
  document.documentElement.dir = "ltr";
}

void i18n.use(initReactI18next).init({
  resources,
  lng: getInitialLanguage(),
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: supportedLanguages,
  interpolation: { escapeValue: false },
  react: { useSuspense: false },
});

syncDocumentLanguage(i18n.resolvedLanguage ?? i18n.language);
i18n.on("languageChanged", (language) => {
  const normalized = normalizeLanguage(language) ?? DEFAULT_LANGUAGE;
  syncDocumentLanguage(normalized);
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, normalized);
    } catch {
      // Changing language should still work when persistence is unavailable.
    }
  }
});

export async function changeLanguage(language: SupportedLanguage): Promise<void> {
  await i18n.changeLanguage(language);
}

export default i18n;
