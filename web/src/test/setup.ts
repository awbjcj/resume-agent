import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";

import { server } from "./server";
import {
  changeLanguage,
  DEFAULT_LANGUAGE,
  LANGUAGE_STORAGE_KEY,
} from "@/i18n";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(async () => {
  server.resetHandlers();
  await changeLanguage(DEFAULT_LANGUAGE);
  localStorage.removeItem(LANGUAGE_STORAGE_KEY);
});
afterAll(() => server.close());
