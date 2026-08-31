import { createRequire } from "node:module";

import { transformAsync, type PluginItem } from "@babel/core";
import type { Plugin } from "vite";

const require = createRequire(import.meta.url);
const autoI18nPlugin = require("./i18n-auto-plugin.cjs") as PluginItem;

export function i18nTransform(): Plugin {
  return {
    name: "resume-tailor-harness-i18n-transform",
    enforce: "pre",
    async transform(code, id) {
      const filename = id.split("?", 1)[0];
      const normalized = filename.replaceAll("\\", "/");
      if (
        !/\.[jt]sx?$/.test(filename)
        || normalized.includes("/node_modules/")
        || normalized.includes("/src/i18n/")
        || /\.(test|spec)\.[jt]sx?$/.test(filename)
      ) return null;
      const result = await transformAsync(code, {
        filename,
        babelrc: false,
        configFile: false,
        parserOpts: { plugins: ["typescript", "jsx"] },
        plugins: [autoI18nPlugin],
        sourceMaps: true,
        sourceFileName: filename,
      });
      if (!result?.code) return null;
      return { code: result.code, map: result.map ?? null };
    },
  };
}
