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
  "Any annual salary": "不限年薪",
  "Annual bonus": "年度奖金",
  "Avg fit in view": "当前视图平均匹配度",
  "Awaiting review": "等待审核",
  "Base": "基本工资",
  "Base salary": "基本工资",
  "Blocking — any claim not traceable to a profile fact fails the round.": "阻断项——任何无法追溯到个人资料事实的表述都将导致本轮不通过。",
  "Certified filings": "已认证申请",
  "Choose a member": "选择成员",
  "Choose a tier": "选择等级",
  "Confidence": "置信度",
  "Complete": "已完成",
  "Collapse": "收起",
  "Could not add": "无法添加",
  "Coverage of the job description's stated requirements.": "职位描述中明确要求的覆盖程度。",
  "Data version": "数据版本",
  "Deleted {{v0}} cover letter{{v1}}": "已删除 {{v0}} 封求职信",
  "Deleted {{v0}} version{{v1}}": "已删除 {{v0}} 个简历版本",
  "Density — cuts padding without cutting evidence.": "信息密度——精简冗余，同时保留证据。",
  "Depth and credibility of the evidence for this specific role.": "针对该职位的证据深度与可信度。",
  "Drafting now": "正在起草",
  "Distinct skills": "不同技能数",
  "Drafting studio": "起草工作室",
  "Domain updated": "领域已更新",
  "Domains merged": "领域已合并",
  "Equity per year": "年度股权",
  "Equity / year": "年度股权",
  "Enter a non-negative annual salary.": "请输入不小于零的年薪。",
  "Expires": "到期时间",
  "Expand": "展开",
  "Filing periods": "申请期间",
  "Filings": "申请数",
  "Fit >= {{v0}}": "匹配度 ≥ {{v0}}",
  "Fit <= {{v0}}": "匹配度 ≤ {{v0}}",
  "Fit band": "匹配度区间",
  "Filtered jobs": "筛选后的职位",
  "Focused rehearsal": "专注演练",
  "Generate another": "再生成一封",
  "Generate cover letter": "生成求职信",
  "Gmail connected.": "Gmail 已连接。",
  "Guided discovery": "引导式探索",
  "Guided evidence discovery": "引导式证据发掘",
  "Job": "职位",
  "job": "职位",
  "Jobs": "职位",
  "Loaded": "已加载",
  "Message": "消息",
  "Matching": "匹配数",
  "Min salary (USD)": "最低年薪（美元）",
  "Must": "必须项",
  "Nice": "加分项",
  "No date": "无日期",
  "Not reported": "未报告",
  "Not shown": "未体现",
  "Open gaps": "未补足差距",
  "Nothing is waiting on you": "目前没有需要你处理的事项",
  "Per-pull job limit for {{v0}}": "{{v0}} 每次获取的职位上限",
  "Proposal": "建议",
  "Pull jobs": "获取职位",
  "Question {{v0}} of {{v1}}": "第 {{v0}} 题，共 {{v1}} 题",
  "Queued": "已排队",
  "Related experience": "相关经验",
  "Researching": "研究中",
  "Retrieved": "获取时间",
  "Rendered in view": "当前视图已生成",
  "Salary >= {{v0}}": "薪资 ≥ {{v0}}",
  "Scored {{v0}}/5": "评分 {{v0}}/5",
  "Share of evidenced must-have requirements actually rendered.": "有证据支持且实际呈现的必备要求占比。",
  "Signing bonus": "签约奖金",
  "Signing": "签约奖金",
  "Skill added": "技能已添加",
  "Skill moved": "技能已移动",
  "Skill removed": "技能已移除",
  "Skills merged": "技能已合并",
  "Sources tracked": "已跟踪来源",
  "Sponsorship offered in view": "当前视图提供担保",
  "Stages active": "活跃阶段数",
  "Six-second skim: does the top of the page land?": "六秒快速浏览：页面顶部是否抓住重点？",
  "Supported": "有直接证据",
  "Select {{v0}} {{v1}}": "选择 {{v0}} {{v1}}",
  "Tech {{v0}}": "技术面试 {{v0}}",
  "Tech": "技术",
  "{{v0}} / {{v1}}": "{{v0}} / {{v1}}",
  "{{v0}} job{{v1}}": "{{v0}} 个职位",
  "{{v0}} percent": "百分之 {{v0}}",
  "{{v0}} turns": "{{v0}} 轮对话",
  "{{v0}}h": "{{v0}} 小时",
  "{{v0}}h {{v1}}m": "{{v0}} 小时 {{v1}} 分钟",
  "{{v0}}m": "{{v0}} 分钟",
  "· ~{{v0}} left": " · 约剩 {{v0}}",
  "· {{v0}} skipped": " · 跳过 {{v0}} 个",
  "({{v0}} pending)": "（{{v0}} 个待处理）",
  "Bonus": "奖金",
  "cover letter": "求职信",
  "done": "已完成",
  "every {{v0}}": "每 {{v0}}",
  "every {{v0}} {{v1}}s": "每 {{v0}} {{v1}}",
  "Keep {{v0}}": "保持 {{v0}}",
  "Local time {{v0}} {{v1}} does not exist in {{v2}}": "{{v2}} 时区不存在本地时间 {{v0}} {{v1}}",
  "resume version": "简历版本",
  "stage": "阶段",
  "${{v0}}+ / year": "${{v0}}+ / 年",
  "${{v0}}k+ / year": "${{v0}}k+ / 年",
  "${{v0}}M+ / year": "${{v0}}M+ / 年",
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
  "caption",
  "confirmLabel",
  "description",
  "detail",
  "emptyMessage",
  "eyebrow",
  "errorMessage",
  "footer",
  "heading",
  "header",
  "help",
  "helpText",
  "hint",
  "kicker",
  "label",
  "message",
  "note",
  "noun",
  "placeholder",
  "sub",
  "subtitle",
  "successMessage",
  "task",
  "title",
]);

const UI_VARIABLE = /(action|badge|caption|date|description|detail|empty|error|eyebrow|fallback|heading|help|hint|label|message|notice|note|placeholder|progress|reason|status|subtitle|success|suffix|summary|text|title)$/i;
const UI_COLLECTION = /(actions|cards|columns|copy|descriptions|details|errors|fields|filters|items|kinds|labels|messages|meta|modalities|names|nav|options|outcomes|parts|results|rows|scopes|sections|stages|statuses|steps|tabs|titles)$/i;

function variableInit(declaration) {
  let init = declaration.get("init");
  while (init.isTSAsExpression() || init.isTSSatisfiesExpression() || init.isTypeCastExpression()) init = init.get("expression");
  return init;
}

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
  const init = variableInit(declaration);
  if (init.node === pathRef.node) return { name: declaration.node.id.name, array: false };
  if (pathRef.parentPath?.isArrayExpression() && init.node === pathRef.parentPath.node) {
    return { name: declaration.node.id.name, array: true };
  }
  let current = pathRef;
  while (current.parentPath?.isConditionalExpression() || current.parentPath?.isLogicalExpression()) current = current.parentPath;
  if (current?.node === init.node) return { name: declaration.node.id.name, array: false };
  return null;
}

function uiCollectionValue(pathRef) {
  const declaration = pathRef.findParent((candidate) => candidate.isVariableDeclarator());
  if (!declaration || declaration.node.id.type !== "Identifier" || !UI_COLLECTION.test(declaration.node.id.name)) return false;
  const init = variableInit(declaration);
  if (!init.isArrayExpression() && !init.isObjectExpression()) return false;
  let current = pathRef;
  while (current.parentPath && current.parentPath.node !== init.node && !current.parentPath.isFunction()) {
    if (current.parentPath.isArrayExpression() && current.parentPath.parentPath?.node === init.node) {
      return current.listKey === "elements"
        && (Number(current.key) > 0
          || /\s|^[A-Z][a-z]/.test(pathRef.isStringLiteral() ? pathRef.node.value : templateSource(pathRef.node)));
    }
    current = current.parentPath;
  }
  if (current.parentPath?.node !== init.node) return false;
  if (init.isObjectExpression() && /(COPY|DESCRIPTIONS|ERRORS|LABELS|MESSAGES|NAMES|NOTES|TITLES)$/i.test(declaration.node.id.name)) {
    return pathRef.parentPath?.isObjectProperty()
      && pathRef.parentPath.parentPath?.node === init.node
      && pathRef.parentPath.get("value").node === pathRef.node;
  }
  if (init.isObjectExpression()) return false;
  return current.node === pathRef.node && current.listKey === "elements";
}

function jsxAttribute(pathRef) {
  let current = pathRef;
  while (current.parentPath) {
    const parent = current.parentPath;
    if (parent.isJSXAttribute()) return parent;
    if (parent.isJSXExpressionContainer() && parent.parentPath?.isJSXAttribute()) return parent.parentPath;
    if (!isValueWrapper(current, parent)) return null;
    current = parent;
  }
  return null;
}

function uiObjectProperty(pathRef) {
  let current = pathRef;
  while (current.parentPath) {
    const parent = current.parentPath;
    if (parent.isObjectProperty()) return parent.get("value").node === current.node && UI_PROPS.has(propertyName(parent.node));
    if (!isValueWrapper(current, parent)) return false;
    current = parent;
  }
  return false;
}

function uiDefaultParameter(pathRef) {
  const assignment = pathRef.findParent((candidate) => candidate.isAssignmentPattern() || candidate.isFunction());
  return Boolean(assignment?.isAssignmentPattern()
    && assignment.node.left.type === "Identifier"
    && UI_VARIABLE.test(assignment.node.left.name));
}

function uiSetterCall(pathRef) {
  const call = pathRef.findParent((candidate) => candidate.isCallExpression() || candidate.isFunction());
  if (!call?.isCallExpression()) return false;
  const callee = call.node.callee;
  if (callee.type === "Identifier") return /^set.*(Error|Message|Notice|Summary)$/.test(callee.name);
  return callee.type === "MemberExpression"
    && callee.property.type === "Identifier"
    && /^(fail|set.*(?:Error|Message|Notice|Summary))$/.test(callee.property.name);
}

function uiErrorMessage(pathRef) {
  const creation = pathRef.findParent((candidate) => candidate.isNewExpression() || candidate.isFunction());
  return Boolean(creation?.isNewExpression()
    && creation.node.callee.type === "Identifier"
    && (creation.node.callee.name === "Error" || creation.node.callee.name === "RangeError"));
}

function uiAttributeFunctionValue(pathRef) {
  const fn = pathRef.findParent((candidate) => candidate.isArrowFunctionExpression() || candidate.isFunctionExpression() || candidate.isFunctionDeclaration());
  if (!fn || fn.isFunctionDeclaration()) return false;
  const attribute = fn.findParent((candidate) => candidate.isJSXAttribute() || candidate.isFunction());
  if (!attribute?.isJSXAttribute()) return false;
  const name = jsxAttributeName(attribute.node);
  if (!name || (name !== "formatter" && !UI_VARIABLE.test(name))) return false;
  let current = pathRef;
  while (current.parentPath && current.parentPath !== fn) {
    const parent = current.parentPath;
    if (parent.isArrayExpression() || parent.isReturnStatement() || isRenderedBranch(current, parent)) {
      current = parent;
      continue;
    }
    return false;
  }
  return current.parentPath === fn;
}

function uiRenderedCallbackValue(pathRef) {
  const fn = pathRef.findParent((candidate) => candidate.isArrowFunctionExpression() || candidate.isFunctionExpression());
  if (!fn || !outputPosition(fn)) return false;
  let current = pathRef;
  while (current.parentPath && current.parentPath !== fn) {
    const parent = current.parentPath;
    if (parent.isReturnStatement() || isValueWrapper(current, parent)) {
      current = parent;
      continue;
    }
    return false;
  }
  return current.parentPath === fn;
}

function uiNamedObjectMap(pathRef) {
  const property = pathRef.parentPath;
  const object = property?.parentPath;
  const declaration = object?.parentPath;
  return Boolean(property?.isObjectProperty()
    && property.get("value").node === pathRef.node
    && object?.isObjectExpression()
    && declaration?.isVariableDeclarator()
    && declaration.node.id.type === "Identifier"
    && (/(COPY|DESCRIPTIONS|ERRORS|LABELS|MESSAGES|NAMES|NOTES|TITLES)$/i.test(declaration.node.id.name)
      || UI_VARIABLE.test(declaration.node.id.name)));
}

function uiNamedCall(pathRef) {
  const call = pathRef.findParent((candidate) => candidate.isCallExpression() || candidate.isFunction());
  return Boolean(call?.isCallExpression()
    && call.node.callee.type === "Identifier"
    && (call.node.callee.name === "label"
      || call.node.callee.name === "pluralLabel"
      || /Message$/.test(call.node.callee.name)));
}

function uiChartName(pathRef) {
  const attribute = jsxAttribute(pathRef);
  if (!attribute?.isJSXAttribute() || jsxAttributeName(attribute.node) !== "name") return false;
  const opening = attribute.parentPath;
  const elementName = opening?.isJSXOpeningElement() && opening.node.name.type === "JSXIdentifier"
    ? opening.node.name.name
    : "";
  return ["Area", "Bar", "Line", "Pie", "Radar", "RadialBar", "Scatter"].includes(elementName);
}

function uiJsxCollectionValue(pathRef) {
  const attribute = pathRef.findParent((candidate) => candidate.isJSXAttribute() || candidate.isFunction());
  if (!attribute?.isJSXAttribute()) return false;
  const name = jsxAttributeName(attribute.node);
  if (name !== "items") return false;
  const tuple = pathRef.parentPath;
  return Boolean(tuple?.isArrayExpression()
    && tuple.parentPath?.isArrayExpression()
    && pathRef.listKey === "elements"
    && Number(pathRef.key) === 0);
}

function namedUiFunction(pathRef) {
  const fn = pathRef.findParent((candidate) => candidate.isFunctionDeclaration() || candidate.isFunctionExpression() || candidate.isArrowFunctionExpression());
  if (!fn) return false;
  let name = fn.node.id?.name;
  if (!name && fn.parentPath?.isVariableDeclarator() && fn.parentPath.node.id.type === "Identifier") {
    name = fn.parentPath.node.id.name;
  }
  if (!name || (!UI_VARIABLE.test(name) && !/(label|title|formatDate|formatCountdown|recency)/i.test(name))) return false;
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
  while (current.parentPath) {
    const parent = current.parentPath;
    if (parent.isJSXExpressionContainer()) {
      return Boolean(parent.parentPath?.isJSXElement() || parent.parentPath?.isJSXFragment());
    }
    if (!isValueWrapper(current, parent)) return false;
    current = parent;
  }
  return false;
}

function isValueWrapper(current, parent) {
  return isRenderedBranch(current, parent)
    || (parent.isArrayExpression()
      && (!(current.isStringLiteral?.() || current.isTemplateLiteral?.())
        || Number(current.key) > 0
        || /\s|^[A-Z][a-z]/.test(current.isStringLiteral?.() ? current.node.value : templateSource(current.node))))
    || parent.isTemplateLiteral()
    || parent.isSpreadElement()
    || (parent.isCallExpression() && current.key === "callee")
    || parent.isMemberExpression()
    || parent.isOptionalMemberExpression?.()
    || parent.isAwaitExpression()
    || parent.isUnaryExpression();
}

function isRenderedBranch(current, parent) {
  if (parent.isConditionalExpression()) return current.key === "consequent" || current.key === "alternate";
  if (parent.isLogicalExpression()) return current.key === "right";
  if (parent.isBinaryExpression()) return parent.node.operator === "+";
  return parent.isTSAsExpression() || parent.isTSSatisfiesExpression() || parent.isParenthesizedExpression();
}

function isTranslationKey(pathRef) {
  const call = pathRef.findParent((candidate) => candidate.isCallExpression() || candidate.isFunction());
  if (!call?.isCallExpression()) return false;
  const callee = call.node.callee;
  return (callee.type === "Identifier" && callee.name === "t")
    || (callee.type === "MemberExpression" && callee.property.type === "Identifier" && callee.property.name === "t");
}

export function isLocalizableStringPath(pathRef) {
  if (pathRef.isJSXText()) return isHumanText(pathRef.node.value);
  if (!pathRef.isStringLiteral() && !pathRef.isTemplateLiteral()) return false;
  if (pathRef.findParent((candidate) => candidate.isTSLiteralType() || candidate.isTSTypeAnnotation() || candidate.isTSUnionType())) return false;
  const value = pathRef.isTemplateLiteral() ? templateSource(pathRef.node) : pathRef.node.value;
  if (!isHumanText(value)) return false;
  if (pathRef.parentPath?.isMemberExpression() && pathRef.key === "property") return false;
  if (isTranslationKey(pathRef)) return false;

  const parent = pathRef.parentPath;
  const attribute = jsxAttribute(pathRef);
  if (attribute) {
    const name = jsxAttributeName(attribute.node);
    return Boolean(name && (UI_PROPS.has(name) || UI_VARIABLE.test(name) || uiChartName(pathRef) || uiJsxCollectionValue(pathRef)));
  }
  if (outputPosition(pathRef) || isToastCall(pathRef) || uiCollectorCall(pathRef) || uiSetterCall(pathRef) || uiErrorMessage(pathRef) || uiAttributeFunctionValue(pathRef) || uiRenderedCallbackValue(pathRef) || uiJsxCollectionValue(pathRef) || uiNamedCall(pathRef) || uiChartName(pathRef)) return true;
  if ((parent?.isObjectProperty() && UI_PROPS.has(propertyName(parent.node))) || uiObjectProperty(pathRef)) return true;
  if (uiNamedObjectMap(pathRef)) return true;
  if (uiDefaultParameter(pathRef)) return true;

  const variable = directVariable(pathRef);
  if (variable && !variable.array && UI_VARIABLE.test(variable.name)) return true;
  if (variable?.array && UI_COLLECTION.test(variable.name)) return true;
  if (uiCollectionValue(pathRef)) return true;
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

function refineCatalog() {
  for (const [source, entry] of Object.entries(catalog)) {
    entry["zh-CN"] = refineTranslation(source, entry["zh-CN"]);
  }
  const sorted = Object.fromEntries(Object.entries(catalog).sort(([left], [right]) => left.localeCompare(right)));
  fs.writeFileSync(catalogPath, `${JSON.stringify(sorted, null, 2)}\n`);
  console.log(`Refined ${Object.keys(sorted).length} catalog entries.`);
}

function pruneCatalog() {
  const pruned = Object.fromEntries(
    Object.entries(catalog)
      .filter(([source]) => candidates.has(source))
      .sort(([left], [right]) => left.localeCompare(right)),
  );
  fs.writeFileSync(catalogPath, `${JSON.stringify(pruned, null, 2)}\n`);
  console.log(`Pruned catalog to ${Object.keys(pruned).length} current UI entries.`);
}

function validateCatalog() {
  const invalid = [];
  const keys = new Set();
  for (const [source, entry] of Object.entries(catalog)) {
    if (!entry || entry.en !== source || typeof entry["zh-CN"] !== "string" || !entry["zh-CN"].trim()) {
      invalid.push(source);
      continue;
    }
    if (keys.has(entry.key)) invalid.push(source);
    keys.add(entry.key);
    const sourceVariables = new Set(source.match(/\{\{v\d+\}\}/g) ?? []);
    const translatedVariables = entry["zh-CN"].match(/\{\{v\d+\}\}/g) ?? [];
    if (translatedVariables.some((variable) => !sourceVariables.has(variable))) invalid.push(source);
  }
  return [...new Set(invalid)];
}

const keyFlagIndex = process.argv.indexOf("--key");

if (process.argv.includes("--refine")) {
  refineCatalog();
} else if (process.argv.includes("--prune")) {
  pruneCatalog();
} else if (process.argv.includes("--unclassified")) {
  const unclassified = collectUnclassified();
  process.stdout.write(`${JSON.stringify(Object.fromEntries(unclassified), null, 2)}\n`);
} else if (keyFlagIndex !== -1) {
  const source = process.argv[keyFlagIndex + 1];
  if (!source) {
    console.error("Usage: node scripts/i18n-catalog.mjs --key \"<source text>\"");
    process.exitCode = 1;
  } else {
    console.log(stableKey(source));
  }
} else if (process.argv.includes("--json")) {
  process.stdout.write(`${JSON.stringify(Object.fromEntries(candidates), null, 2)}\n`);
} else {
  const invalid = validateCatalog();
  if (missing.length) {
    console.error(`Missing ${missing.length} UI translations. Every entry is a fixed, hand-written`);
    console.error(`translation — there is no machine-translation fallback. For each string below,`);
    console.error(`run \`node scripts/i18n-catalog.mjs --key "<source text>"\` to get its key, then`);
    console.error(`add { "key": "...", "en": "<source text>", "zh-CN": "<hand-written translation>" }`);
    console.error(`to src/i18n/auto-catalog.json:`);
    for (const [source, locations] of missing) {
      console.error(`- ${JSON.stringify(source)} (${locations.slice(0, 3).join(", ")})`);
    }
  }
  if (stale.length) console.error(`Catalog contains ${stale.length} unused entries.`);
  if (invalid.length) console.error(`Catalog contains ${invalid.length} invalid entries.`);
  if (!missing.length && !stale.length && !invalid.length) {
    console.log(`i18n catalog covers ${candidates.size} user-facing literals.`);
  }
  process.exitCode = missing.length || stale.length || invalid.length ? 1 : 0;
}
