import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

import { parse } from "@babel/parser";
import traverseModule from "@babel/traverse";

const traverse = traverseModule.default ?? traverseModule;
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sourceRoot = path.join(root, "src");
const catalogPath = path.join(sourceRoot, "i18n", "auto-catalog.json");

const EXACT_TRANSLATIONS = {
  "100% · done": "100% · 已完成",
  "Fit >= {{v0}}": "匹配度 ≥ {{v0}}",
  "Fit <= {{v0}}": "匹配度 ≤ {{v0}}",
  "Job": "职位",
  "job": "职位",
  "Jobs": "职位",
  "Nothing is waiting on you": "目前没有需要你处理的事项",
  "Per-pull job limit for {{v0}}": "{{v0}} 每次获取的职位上限",
  "Proposal": "建议",
  "Pull jobs": "获取职位",
  "Salary >= {{v0}}": "薪资 ≥ {{v0}}",
  "{{v0}} job{{v1}} waiting on you": "有 {{v0}} 个职位等待你处理",
  "{{v0}}…": "{{v0}}…",
};

function refineTranslation(source, translation) {
  if (EXACT_TRANSLATIONS[source]) return EXACT_TRANSLATIONS[source];
  let refined = translation;
  if (/\bjobs?\b/i.test(source)) refined = refined.replaceAll("作业", "职位").replaceAll("工作", "职位");
  if (/\bprofiles?\b/i.test(source)) refined = refined.replaceAll("配置文件", "个人资料");
  if (/\bapplications?\b/i.test(source)) refined = refined.replaceAll("应用程序", "申请");
  if (/\bresumes?\b/i.test(source)) refined = refined.replaceAll("恢复", "简历");
  if (/\btailor(?:ed|ing)?\b/i.test(source)) refined = refined.replaceAll("剪裁", "定制");
  return refined;
}

const UI_PROPS = new Set([
  "actionLabel",
  "alt",
  "aria-label",
  "assistantName",
  "body",
  "cancelLabel",
  "confirmLabel",
  "description",
  "detail",
  "emptyMessage",
  "errorMessage",
  "footer",
  "heading",
  "helpText",
  "hint",
  "kicker",
  "label",
  "placeholder",
  "sub",
  "subtitle",
  "successMessage",
  "task",
  "title",
]);

const UI_VARIABLE = /(action|caption|description|detail|empty|error|heading|help|hint|label|message|placeholder|status|subtitle|success|text|title)$/i;
const UI_COLLECTION = /(actions|cards|fields|filters|items|kinds|labels|modalities|nav|options|outcomes|results|rows|scopes|sections|stages|statuses|steps|tabs)$/i;

function filesUnder(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const resolved = path.join(directory, entry.name);
    if (entry.isDirectory()) return filesUnder(resolved);
    if (!/\.(ts|tsx)$/.test(entry.name) || /\.(test|spec)\.(ts|tsx)$/.test(entry.name)) return [];
    if (resolved.includes(`${path.sep}i18n${path.sep}`)) return [];
    return [resolved];
  });
}

function clean(value) {
  return value.replace(/\s+/g, " ").trim();
}

function isHumanText(value) {
  const text = clean(value);
  if (!text || !/[A-Za-z]/.test(text)) return false;
  if (/^(https?:|\/api\/|[.#@]|[a-z]+:\/\/)/i.test(text)) return false;
  if (/(^|\s)(sm|md|lg|xl|2xl|dark|hover|focus|data|group|peer):/.test(text)) return false;
  if (/(^|\s)(flex|grid|block|hidden|relative|absolute|w-|h-|p[trblxy]?-[\d[]|m[trblxy]?-[\d[]|text-|bg-|border-|rounded-|gap-|items-|justify-|space-|min-|max-|overflow-|shadow-|ring-)/.test(text)) return false;
  if (/\b(?:text|bg|border|rounded|tracking|leading|font|w|h|min|max|p[trblxy]?|m[trblxy]?|gap|items|justify|shadow|ring|opacity)-[^\s]+/.test(text) && !/[.!?]/.test(text)) return false;
  return true;
}

function jsxAttributeName(node) {
  if (node.name.type === "JSXIdentifier") return node.name.name;
  return null;
}

function propertyName(node) {
  if (node.computed) return null;
  if (node.key.type === "Identifier" || node.key.type === "StringLiteral") return node.key.name ?? node.key.value;
  return null;
}

function directVariable(pathRef) {
  const declaration = pathRef.findParent((candidate) => candidate.isVariableDeclarator());
  if (!declaration || declaration.node.id.type !== "Identifier") return null;
  const init = declaration.get("init");
  if (init === pathRef) return { name: declaration.node.id.name, array: false };
  if (pathRef.parentPath?.isArrayExpression() && init === pathRef.parentPath) {
    return { name: declaration.node.id.name, array: true };
  }
  let current = pathRef.parentPath;
  while (current?.isConditionalExpression() || current?.isLogicalExpression()) current = current.parentPath;
  if (current === init) return { name: declaration.node.id.name, array: false };
  return null;
}

function jsxAttribute(pathRef) {
  if (pathRef.parentPath?.isJSXAttribute()) return pathRef.parentPath;
  if (pathRef.parentPath?.isJSXExpressionContainer() && pathRef.parentPath.parentPath?.isJSXAttribute()) {
    return pathRef.parentPath.parentPath;
  }
  return null;
}

function namedUiFunction(pathRef) {
  const fn = pathRef.findParent((candidate) => candidate.isFunctionDeclaration() || candidate.isFunctionExpression() || candidate.isArrowFunctionExpression());
  if (!fn) return false;
  let name = fn.node.id?.name;
  if (!name && fn.parentPath?.isVariableDeclarator() && fn.parentPath.node.id.type === "Identifier") {
    name = fn.parentPath.node.id.name;
  }
  if (!name || !UI_VARIABLE.test(name)) return false;
  let current = pathRef;
  while (current.parentPath?.isConditionalExpression() || current.parentPath?.isLogicalExpression()) current = current.parentPath;
  if (current.parentPath?.isReturnStatement()) {
    return current.parentPath.findParent((candidate) => candidate.isFunction()) === fn;
  }
  return fn.isArrowFunctionExpression() && fn.get("body") === current;
}

function uiCollectorCall(pathRef) {
  const call = pathRef.findParent((candidate) => candidate.isCallExpression());
  if (!call) return false;
  let argument = pathRef;
  while (argument.parentPath && argument.parentPath !== call) argument = argument.parentPath;
  if (argument.parentPath !== call || argument.listKey !== "arguments") return false;
  if (call.node.callee.type === "Identifier") {
    return call.node.callee.name === "scalar" && argument.key === 1;
  }
  const callee = call.node.callee;
  if (!(callee.type === "MemberExpression"
    && callee.object.type === "Identifier"
    && callee.property.type === "Identifier"
    && callee.property.name === "push"
    && UI_COLLECTION.test(callee.object.name))) return false;
  if (argument === pathRef) return true;
  return argument.isArrayExpression() && argument.get("elements.0") === pathRef;
}

function isToastCall(pathRef) {
  const call = pathRef.findParent((candidate) => candidate.isCallExpression());
  if (!call) return false;
  const callee = call.node.callee;
  return callee.type === "MemberExpression"
    && callee.object.type === "Identifier"
    && callee.object.name === "toast";
}

function outputPosition(pathRef) {
  let current = pathRef;
  if (current.parentPath?.isConditionalExpression()) {
    if (current.key !== "consequent" && current.key !== "alternate") return false;
    current = current.parentPath;
  }
  const container = current.parentPath;
  return Boolean(
    container?.isJSXExpressionContainer()
      && (container.parentPath?.isJSXElement() || container.parentPath?.isJSXFragment()),
  );
}

export function isLocalizableStringPath(pathRef) {
  if (pathRef.isJSXText()) return isHumanText(pathRef.node.value);
  if (!pathRef.isStringLiteral() && !pathRef.isTemplateLiteral()) return false;
  const value = pathRef.isTemplateLiteral() ? templateSource(pathRef.node) : pathRef.node.value;
  if (!isHumanText(value)) return false;

  const parent = pathRef.parentPath;
  const attribute = jsxAttribute(pathRef);
  if (attribute) {
    return UI_PROPS.has(jsxAttributeName(attribute.node));
  }
  if (outputPosition(pathRef) || isToastCall(pathRef) || uiCollectorCall(pathRef)) return true;
  if (parent?.isObjectProperty() && UI_PROPS.has(propertyName(parent.node))) return true;

  const variable = directVariable(pathRef);
  if (variable && !variable.array && UI_VARIABLE.test(variable.name)) return true;
  if (variable?.array && UI_COLLECTION.test(variable.name)) return true;
  return namedUiFunction(pathRef);
}

function templateSource(node) {
  return node.quasis
    .map((quasi, index) => `${quasi.value.cooked ?? quasi.value.raw}${index < node.expressions.length ? `{{v${index}}}` : ""}`)
    .join("");
}

function collect() {
  const found = new Map();
  for (const filename of filesUnder(sourceRoot)) {
    const source = fs.readFileSync(filename, "utf8");
    const ast = parse(source, {
      sourceType: "module",
      plugins: ["typescript", "jsx"],
    });
    traverse(ast, {
      JSXText(pathRef) {
        if (!isLocalizableStringPath(pathRef)) return;
        record(pathRef.node.value, filename, pathRef.node.loc?.start.line);
      },
      StringLiteral(pathRef) {
        if (!isLocalizableStringPath(pathRef)) return;
        record(pathRef.node.value, filename, pathRef.node.loc?.start.line);
      },
      TemplateLiteral(pathRef) {
        if (!isLocalizableStringPath(pathRef)) return;
        record(templateSource(pathRef.node), filename, pathRef.node.loc?.start.line);
      },
    });
  }
  return found;

  function record(value, filename, line) {
    const source = clean(value);
    const locations = found.get(source) ?? [];
    locations.push(`${path.relative(root, filename).replaceAll("\\", "/")}:${line ?? 1}`);
    found.set(source, locations);
  }
}

function collectUnclassified() {
  const found = new Map();
  for (const filename of filesUnder(sourceRoot)) {
    const source = fs.readFileSync(filename, "utf8");
    const ast = parse(source, { sourceType: "module", plugins: ["typescript", "jsx"] });
    traverse(ast, {
      StringLiteral(pathRef) {
        if (isLocalizableStringPath(pathRef) || !isHumanText(pathRef.node.value)) return;
        record(pathRef.node.value, filename, pathRef.node.loc?.start.line);
      },
      TemplateLiteral(pathRef) {
        const value = templateSource(pathRef.node);
        if (isLocalizableStringPath(pathRef) || !isHumanText(value)) return;
        record(value, filename, pathRef.node.loc?.start.line);
      },
    });
  }
  return found;

  function record(value, filename, line) {
    const source = clean(value);
    const locations = found.get(source) ?? [];
    locations.push(`${path.relative(root, filename).replaceAll("\\", "/")}:${line ?? 1}`);
    found.set(source, locations);
  }
}

const candidates = collect();
const catalog = JSON.parse(fs.readFileSync(catalogPath, "utf8"));
const missing = [...candidates.entries()].filter(([source]) => !catalog[source]);
const stale = Object.keys(catalog).filter((source) => !candidates.has(source));

function stableKey(source) {
  return `ui_${createHash("sha256").update(source).digest("hex").slice(0, 12)}`;
}

async function translate(source) {
  const query = new URLSearchParams({ q: source, langpair: "en|zh-CN" });
  let lastError;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      const response = await fetch(`https://api.mymemory.translated.net/get?${query}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const translated = payload?.responseData?.translatedText?.trim();
      if (!translated) throw new Error("empty translation");
      return translated;
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
    }
  }
  throw lastError;
}

async function syncMachineTranslations() {
  const queue = missing.map(([source]) => source);
  let completed = 0;
  const workers = Array.from({ length: Math.min(4, queue.length) }, async () => {
    while (queue.length) {
      const source = queue.shift();
      if (!source) return;
      const zhCN = await translate(source);
      catalog[source] = { key: stableKey(source), en: source, "zh-CN": refineTranslation(source, zhCN) };
      completed += 1;
      if (completed % 50 === 0 || completed === missing.length) {
        console.log(`Translated ${completed}/${missing.length}`);
      }
    }
  });
  await Promise.all(workers);
  const sorted = Object.fromEntries(Object.entries(catalog).sort(([left], [right]) => left.localeCompare(right)));
  fs.writeFileSync(catalogPath, `${JSON.stringify(sorted, null, 2)}\n`);
  console.log(`Wrote ${Object.keys(sorted).length} catalog entries to ${path.relative(root, catalogPath)}.`);
}

function refineCatalog() {
  for (const [source, entry] of Object.entries(catalog)) {
    entry["zh-CN"] = refineTranslation(source, entry["zh-CN"]);
  }
  const sorted = Object.fromEntries(Object.entries(catalog).sort(([left], [right]) => left.localeCompare(right)));
  fs.writeFileSync(catalogPath, `${JSON.stringify(sorted, null, 2)}\n`);
  console.log(`Refined ${Object.keys(sorted).length} catalog entries.`);
}

if (process.argv.includes("--refine")) {
  refineCatalog();
} else if (process.argv.includes("--unclassified")) {
  const unclassified = collectUnclassified();
  process.stdout.write(`${JSON.stringify(Object.fromEntries(unclassified), null, 2)}\n`);
} else if (process.argv.includes("--sync-machine")) {
  await syncMachineTranslations();
} else if (process.argv.includes("--json")) {
  process.stdout.write(`${JSON.stringify(Object.fromEntries(candidates), null, 2)}\n`);
} else {
  if (missing.length) {
    console.error(`Missing ${missing.length} UI translations:`);
    for (const [source, locations] of missing) {
      console.error(`- ${JSON.stringify(source)} (${locations.slice(0, 3).join(", ")})`);
    }
  }
  if (stale.length) console.warn(`Catalog contains ${stale.length} unused entries.`);
  if (!missing.length) console.log(`i18n catalog covers ${candidates.size} user-facing literals.`);
  process.exitCode = missing.length ? 1 : 0;
}
