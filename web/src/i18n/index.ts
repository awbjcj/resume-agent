import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { loadAutoTranslations, resources } from "./resources";

export const supportedLanguages = ["en", "zh-CN"] as const;
export type SupportedLanguage = (typeof supportedLanguages)[number];

export const LANGUAGE_STORAGE_KEY = "resume-tailor-harness-language";
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
  const normalized = normalizeLanguage(language) ?? DEFAULT_LANGUAGE;
  document.documentElement.lang = normalized;
  document.documentElement.dir = "ltr";
  document.title = i18n.t("app.documentTitle", { lng: normalized });
}

function languageChanged(language: string): void {
  const normalized = normalizeLanguage(language) ?? DEFAULT_LANGUAGE;
  syncDocumentLanguage(normalized);
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, normalized);
    } catch {
      // Changing language should still work when persistence is unavailable.
    }
  }
}

async function ensureLanguageResources(language: SupportedLanguage): Promise<void> {
  if (language === DEFAULT_LANGUAGE) return;
  const auto = await loadAutoTranslations(language);
  Object.assign(resources[language].translation.auto, auto);
  if (i18n.isInitialized) {
    i18n.addResourceBundle(language, "translation", { auto }, true, true);
  }
}

async function initializeI18n(): Promise<void> {
  const initialLanguage = getInitialLanguage();
  await ensureLanguageResources(initialLanguage);
  await i18n.use(initReactI18next).init({
    resources,
    lng: initialLanguage,
    fallbackLng: DEFAULT_LANGUAGE,
    supportedLngs: supportedLanguages,
    interpolation: { escapeValue: false },
    react: { useSuspense: false },
  });
  syncDocumentLanguage(i18n.resolvedLanguage ?? i18n.language);
  i18n.on("languageChanged", languageChanged);
}

export const i18nReady = initializeI18n();

export async function changeLanguage(language: SupportedLanguage): Promise<void> {
  await i18nReady;
  await ensureLanguageResources(language);
  await i18n.changeLanguage(language);
}

export default i18n;
