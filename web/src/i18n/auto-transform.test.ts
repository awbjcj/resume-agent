/// <reference types="node" />

import { transformAsync, type PluginItem } from "@babel/core";
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const autoI18nPlugin = require("../../i18n-auto-plugin.cjs") as PluginItem;

describe("automatic i18n build transform", () => {
  it("uses the selected language for implicit and fixed English locale formatting", async () => {
    const result = await transformAsync(
      `
        const number = (1234).toLocaleString("en-US");
        const date = new Date().toLocaleDateString();
        const currency = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" });
        const clock = Intl.DateTimeFormat().format(new Date());
      `,
      {
        babelrc: false,
        configFile: false,
        plugins: [autoI18nPlugin],
      },
    );

    expect(result?.code?.match(/resolvedLanguage/g)).toHaveLength(4);
    expect(result?.code).not.toContain('"en-US"');
  });
});
