import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

import { parse } from "@babel/parser";
import traverseModule from "@babel/traverse";

const traverse = traverseModule.default ?? traverseModule;
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sourceRoot = path.join(root, "src");
const catalogPath = path.join(sourceRoot, "i18n", "auto-catalog.json");
const dynamicZhCNPath = path.join(sourceRoot, "i18n", "dynamic-zh-CN.json");
const backendSourceRoot = path.resolve(root, "..", "src", "resume_tailor_harness");
const runtimeCatalogPaths = {
  en: path.join(sourceRoot, "i18n", "auto-en.json"),
  "zh-CN": path.join(sourceRoot, "i18n", "auto-zh-CN.json"),
};
const require = createRequire(import.meta.url);
const {
  clean,
  isHumanText,
  isLocalizableStringPath,
  templateSource,
} = require("../i18n-classifier.cjs");

// These are the terms where product context matters more than a literal
// translation. They are deliberately authored and checked against the catalog;
// the catalog is never generated from a translation service.
const FIXED_ZH_CN_TRANSLATIONS = {
  "100% · {{v0}}": "{{v0}}（100%）",
  "100% · done": "100% · 已完成",
  "A gated reviewer blocks the round outright, so it is never scored — its weight and score bands are disabled rather than silently ignored.": "启用硬性门槛的评审会直接阻断本轮，因此不参与评分；其权重和评分区间会被禁用，而非悄然忽略。",
  "Application timeline grid": "申请时间线表格",
  "Ask the Scout": "咨询职位探索助手",
  "Any annual salary": "不限年薪",
  "Apps": "应用",
  "Annual bonus": "年度奖金",
  "Avg fit in view": "当前视图平均匹配度",
  "Awaiting review": "等待审核",
  "Base": "基本工资",
  "Base salary": "基本工资",
  "Blocking — any claim not traceable to a profile fact fails the round.": "阻断项——任何无法追溯到个人资料事实的表述都将导致本轮不通过。",
  "Certified filings": "已认证申请",
  "Choose a member": "选择成员",
  "Choose a tailored job. Jobs with an interview in progress are hidden so you can resume them from the sessions list.": "请选择已定制的职位。正在进行面试的职位会被隐藏，以便你从会话列表中继续。",
  "Choose a tier": "选择等级",
  "Career Lab": "职业实验室",
  "Confidence": "置信度",
  "Complete": "已完成",
  "Collapse": "收起",
  "Could not add": "无法添加",
  "Coverage of the job description's stated requirements.": "职位描述中明确要求的覆盖程度。",
  "Create Scout session": "创建职位探索助手会话",
  "Data version": "数据版本",
  "Deleted {{v0}} cover letter{{v1}}": "已删除 {{v0}} 封求职信",
  "Deleted {{v0}} version{{v1}}": "已删除 {{v0}} 个简历版本",
  "Density — cuts padding without cutting evidence.": "信息密度——精简冗余，同时保留证据。",
  "Depth and credibility of the evidence for this specific role.": "针对该职位的证据深度与可信度。",
  "Describe the search": "说明搜索条件",
  "Discovery goal": "职位探索目标",
  "Discovery request": "职位探索请求",
  "Discovery Scout": "职位探索助手",
  "Discovery Scout is unavailable": "职位探索助手暂不可用",
  "Discovery Scout sessions": "职位探索助手会话",
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
  "Export grid": "导出表格",
  "Filing periods": "申请期间",
  "Filings": "申请数",
  "Fit >= {{v0}}": "匹配度 ≥ {{v0}}",
  "Fit <= {{v0}}": "匹配度 ≤ {{v0}}",
  "Fit band": "匹配度区间",
  "Filtered jobs": "筛选后的职位",
  "Focused rehearsal": "专注演练",
  "Generate another": "再生成一封",
  "Generate cover letter": "生成求职信",
  "Gate": "硬性门槛",
  "Gmail connected.": "Gmail 已连接。",
  "Guided discovery": "引导式职位探索",
  "Guided evidence discovery": "引导式证据发掘",
  "Job": "职位",
  "job": "职位",
  "Jobs": "职位",
  "Integrity gate — read-only": "完整性校验（只读）",
  "Listen first, with interviewer text hidden until you reveal it.": "先收听；在你主动显示前，面试官文字将保持隐藏。",
  "Loading gap-closing advice": "正在加载弥补差距建议",
  "Loaded": "已加载",
  "Message": "消息",
  "Matching": "匹配数",
  "Min salary (USD)": "最低年薪（美元）",
  "Mid tier model": "标准型模型",
  "Model tier": "模型档位",
  "Model tiers": "模型档位",
  "Models are grouped into one block and their immutable versions stay newest-first. Sort any column to rank model groups by the latest version.": "模型按组归类，各不可变版本按最新优先排序。可按任意列排序，按每组最新版本对模型组排名。",
  "Mock interview": "模拟面试",
  "Mock interviews": "模拟面试",
  "Must": "必须项",
  "Nice": "加分项",
  "No date": "无日期",
  "No saved research": "暂无已保存的调研结果",
  "Not reported": "未报告",
  "Not shown": "未体现",
  "Open gaps": "未补足差距",
  "Offer": "录用通知",
  "Offer %": "录用通知占比",
  "Offer application ids": "录用通知对应的申请 ID",
  "Offer comparison": "录用通知对比",
  "Offer comparison references": "录用通知对比参考",
  "Offer deadline": "录用通知截止日期",
  "Offer deadline: {{v0}}": "录用通知截止日期：{{v0}}",
  "Offer received": "已收到录用通知",
  "Offers": "录用通知",
  "offer": "录用通知",
  "Nothing is waiting on you": "目前没有需要你处理的事项",
  "New Scout session": "新建职位探索助手会话",
  "No Scout sessions yet. Start one when you are ready to shape your search.": "还没有职位探索助手会话。准备好明确求职方向时，即可开始一次探索。",
  "Per-pull job limit for {{v0}}": "{{v0}} 每次获取的职位上限",
  "Premium": "高价位",
  "Premium tier model": "高级型模型",
  "Proposal": "建议",
  "Profile Coach": "个人资料教练",
  "Pull jobs": "获取职位",
  "Question {{v0}} of {{v1}}": "第 {{v0}} 题，共 {{v1}} 题",
  "Queued": "已排队",
  "Related experience": "相关经验",
  "Researching": "调研中",
  "Review the research": "查看调研结果",
  "Retrieved": "获取时间",
  "Rendered in view": "当前视图已生成",
  "Salary >= {{v0}}": "薪资 ≥ {{v0}}",
  "Scored {{v0}}/5": "评分 {{v0}}/5",
  "Share of evidenced must-have requirements actually rendered.": "有证据支持且实际呈现的必备要求占比。",
  "Signing bonus": "签约奖金",
  "Signing": "签约奖金",
  "Scout could not reply": "职位探索助手未能回复",
  "Scout could not start": "职位探索助手无法启动",
  "Scout proposals": "职位探索助手建议",
  "Scout request failed": "职位探索助手请求失败",
  "Scout researching": "职位探索助手正在调研",
  "Shape a smarter search": "让搜索更精准",
  "Skill added": "技能已添加",
  "Skill moved": "技能已移动",
  "Skill removed": "技能已移除",
  "Skills merged": "技能已合并",
  "Sources tracked": "已跟踪来源",
  "Sponsorship offered in view": "当前视图提供担保",
  "Stages active": "活跃阶段数",
  "Tell the Scout what you want to find. It will research companies and search terms, then wait for your approval before changing anything.": "告诉职位探索助手你想寻找什么。它会调研公司和搜索词，并在更改任何设置前等待你的批准。",
  "The Scout could not finish that step": "职位探索助手未能完成这一步",
  "The Scout returns separate, cited proposals instead of changing settings silently.": "职位探索助手会给出彼此独立且附带引用的建议，不会在未告知的情况下更改设置。",
  "Six-second skim: does the top of the page land?": "六秒快速浏览：页面顶部是否抓住重点？",
  "Supported": "有直接证据",
  "Select {{v0}} {{v1}}": "选择 {{v0}} {{v1}}",
  "Tech {{v0}}": "技术面试 {{v0}}",
  "Tech": "技术",
  "not scored": "不计分",
  "Warnings": "警示信息",
  "Warm": "亲和",
  "{{v0}} / {{v1}}": "{{v0}} / {{v1}}",
  "{{v0}} · stale": "{{v0}} · 已过期",
  "{{v0}} {{v1}}: {{v2}}": "{{v0}} {{v1}}：{{v2}}",
  "{{v0}} job{{v1}}": "{{v0}} 个职位",
  "{{v0}} percent": "百分之 {{v0}}",
  "{{v0}} turns": "{{v0}} 轮对话",
  "{{v0}}h": "{{v0}} 小时",
  "{{v0}}h {{v1}}m": "{{v0}} 小时 {{v1}} 分钟",
  "{{v0}}m": "{{v0}} 分钟",
  "{{v0}}% · {{v1}}": "{{v1}}（{{v0}}%）",
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
  "Untitled Scout session": "未命名职位探索助手会话",
  "${{v0}}+ / year": "${{v0}}+ / 年",
  "${{v0}}k+ / year": "${{v0}}k+ / 年",
  "${{v0}}M+ / year": "${{v0}}M+ / 年",
  "{{v0}} job{{v1}} waiting on you": "有 {{v0}} 个职位等待你处理",
  "{{v0}} gate": "{{v0}} 硬性门槛",
  "{{v0}} model tier": "{{v0}} 模型档位",
  "{{v0}}…": "{{v0}}…",
  "Your browser blocked autoplay. Press play to listen.": "浏览器阻止了自动播放。请点击播放以收听。",
  "Corroborated": "多来源印证",
  "Single source": "单一来源",
  "Inference": "推断",
  "Company official": "公司官方来源",
  "Government or regulatory": "政府或监管来源",
  "Reputable independent": "可信独立来源",
  "Employee or community": "员工或社区来源",
  "Other public source": "其他公开来源",
  "Conflicting evidence:": "存在冲突的证据：",
  "Published": "发布时间",
  "research": "研究",
  "Version": "版本",
  "What changed": "本次变化",
  "Added {{v0}} source(s)": "新增 {{v0}} 个来源",
  "Removed {{v0}} source(s)": "移除 {{v0}} 个来源",
  "No material evidence changes were detected.": "未发现实质性证据变化。",
  "Research history": "研究历史",
  "Loading history…": "正在加载研究历史…",
  "Quick scan prioritizes the strongest official and current independent evidence.": "快速扫描优先采用最有力的官方来源和近期独立证据。",
  "Standard balances coverage and cost across every supported research axis.": "标准研究在所有有证据支持的研究维度之间平衡覆盖度与成本。",
  "Deep seeks corroboration, dates, and credible conflicting evidence.": "深度研究会寻找多来源印证、日期信息以及可信的冲突证据。",
  "{{v0}} Refreshing updates every job at this company.": "{{v0}} 刷新后会更新该公司的所有职位。",
  "Company research depth": "公司研究深度",
  "Quick": "快速",
  "Job-specific planning": "职位专项规划",
  "Role preparation": "职位准备",
  "Turn the frozen company dossier, exact job description, selected documents, and earlier-round notes into an interview-ready brief.": "根据冻结的公司档案、准确的职位描述、已选文档和前序面试记录生成可直接用于面试的准备简报。",
  "Generation is explicit. Existing briefs stay frozen until you regenerate them.": "仅在你明确操作时生成；现有简报在重新生成前保持不变。",
  "Regenerate brief": "重新生成简报",
  "Generate brief": "生成简报",
  "Role preparation failed. The last saved brief is unchanged.": "职位准备生成失败。上次保存的简报保持不变。",
  "Loading role preparation…": "正在加载职位准备…",
  "Company research v": "公司研究版本",
  "Resume v": "简历版本",
  "Inputs changed": "输入已变更",
  "Generated": "生成时间",
  "The job, selected documents, company dossier, or interview notes changed after this brief was generated. The saved brief remains unchanged until you regenerate it.": "生成此简报后，职位、已选文档、公司档案或面试记录已发生变化。保存的简报将在你重新生成前保持不变。",
  "Earlier-round focus": "前序面试重点",
  "Priority competencies": "优先能力项",
  "Concerns to prepare": "需要准备的风险点",
  "Likely questions": "可能的问题",
  "Story prompt:": "案例提示：",
  "Questions to ask": "向面试官提问",
  "Recruiter verification": "向招聘人员确认",
  "No role brief yet": "尚无职位准备简报",
  "Generate company research first, then build a role-specific brief.": "请先生成公司研究，再创建职位专项简报。",
  "{{v0}} copied": "已复制{{v0}}",
  "Copy {{v0}}": "复制{{v0}}",
  "Copy": "复制",
  "Single public source": "单一公开来源",
  "Public source": "公开来源",
  "Email draft": "电子邮件草稿",
  "Short message draft": "短消息草稿",
  "Public-source people research": "公开来源人员研究",
  "Hiring contacts": "招聘联系人",
  "Find publicly verified people who may be relevant to this role, then prepare copy-only drafts.": "查找与该职位相关且可通过公开来源验证的人员，并准备仅供复制的草稿。",
  "No private enrichment, login-gated scraping, or automatic outreach.": "不使用私人数据补全、登录后抓取或自动联系。",
  "Refresh contacts": "刷新联系人",
  "Research contacts": "研究联系人",
  "Draft only. This feature never sends messages. Verify every person's current role before use.": "仅提供草稿；此功能绝不会发送消息。使用前请确认每个人当前的职位。",
  "Contact research failed. The last saved result is unchanged.": "联系人研究失败。上次保存的结果保持不变。",
  "No named contact was confirmed from public sources.": "未能通过公开来源确认具名联系人。",
  "Role-addressed drafts": "面向职位的草稿",
  "Use these when no named person is verified or when a general recruiting channel is more appropriate.": "在没有已验证的具名联系人，或通用招聘渠道更合适时使用这些草稿。",
  "Generic email draft": "通用电子邮件草稿",
  "Generic short message": "通用短消息",
  "No contact research yet": "尚无联系人研究",
  "Loading hiring-contact intelligence…": "正在加载招聘联系人情报…",
  "Compare up to three roles at a time": "一次最多比较三个职位",
  "Role comparison controls": "职位比较控件",
  "Compare roles": "比较职位",
  "Select two or three application rows. {{v0}} selected.": "请选择两到三条申请记录。已选择 {{v0}} 条。",
  "Comparing…": "正在比较…",
  "Compare selected": "比较所选职位",
  "Role comparison could not be loaded. The selected applications are unchanged.": "无法加载职位比较。所选申请保持不变。",
  "Compare": "比较",
  "Select {{v0}} {{v1}} for comparison": "选择 {{v0}} 的 {{v1}} 进行比较",
  "Stored evidence only": "仅使用已存证据",
  "Role comparison": "职位比较",
  "Missing values stay explicit; this table does not call a model or guess an answer.": "缺失值会明确显示；此表不会调用模型或猜测答案。",
  "Company evidence": "公司证据",
  "H-1B evidence": "H-1B 证据",
  "Latest offer": "最新录用方案",
  "Unknown role": "未知职位",
  "Not scored": "未评分",
  "No structured offer": "无结构化录用方案",
};

const UNCHANGED_ZH_CN_SOURCES = new Set([
  "00:00 UTC",
  "acme",
  "Acme",
  "America/New_York",
  "Ashby",
  "ATS",
  "BambooHR",
  "Breezy HR",
  "CoderPad",
  "CodeSignal",
  "GitHub",
  "Gmail",
  "Google",
  "Google Meet",
  "Greenhouse",
  "HackerRank",
  "JazzHR",
  "Karat",
  "Lever",
  "Microsoft Teams",
  "n=",
  "OA",
  "Personio",
  "portfolio, flagship-project",
  "Recruitee",
  "Résumé Tailor Harness",
  "SmartRecruiters",
  "wd5",
  "Webex",
  "Workable",
  "Workday",
]);

function isFormattingOnly(value) {
  return /^[\s·•—#%→/…{}v\d–]+$/.test(value);
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

function pythonFilesUnder(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const resolved = path.join(directory, entry.name);
    if (entry.isDirectory()) return pythonFilesUnder(resolved);
    return entry.name.endsWith(".py") ? [resolved] : [];
  });
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
const dynamicZhCN = JSON.parse(fs.readFileSync(dynamicZhCNPath, "utf8"));
const missing = [...candidates.entries()].filter(([source]) => !catalog[source]);
const stale = Object.keys(catalog).filter((source) => !candidates.has(source));

function normalizeBackendProgressLabel(label) {
  return label.replace(/\{[^{}]+\}/g, "{{value}}");
}

function reporterCallArguments(source, start) {
  const open = source.indexOf("(", start);
  let depth = 0;
  let quote = null;
  for (let index = open; index < source.length; index += 1) {
    const char = source[index];
    if (quote) {
      if (char === "\\") {
        index += 1;
      } else if (char === quote) {
        quote = null;
      }
      continue;
    }
    if (char === "\"" || char === "'") {
      quote = char;
    } else if (char === "(") {
      depth += 1;
    } else if (char === ")") {
      depth -= 1;
      if (depth === 0) return source.slice(open + 1, index);
    }
  }
  return "";
}

function collectBackendProgressLabels() {
  const labels = new Map();
  for (const filename of pythonFilesUnder(backendSourceRoot)) {
    const source = fs.readFileSync(filename, "utf8");
    for (const call of source.matchAll(/\b\w*reporter\.(?:begin|step)\(/g)) {
      const start = call.index ?? 0;
      const match = /,\s*(?:label\s*=\s*)?(?:f)?(["'])([\s\S]*?)\1/.exec(reporterCallArguments(source, start));
      if (!match) continue;
      const label = normalizeBackendProgressLabel(match[2]);
      const locations = labels.get(label) ?? [];
      const line = source.slice(0, start).split("\n").length;
      locations.push(`${path.relative(root, filename).replaceAll("\\", "/")}:${line}`);
      labels.set(label, locations);
    }
  }
  return labels;
}

const backendProgressLabels = collectBackendProgressLabels();
const missingBackendProgressTranslations = [...backendProgressLabels.entries()]
  .filter(([label]) => typeof dynamicZhCN.runPhases?.[label] !== "string" || !dynamicZhCN.runPhases[label].trim());
const invalidDynamicValues = [
  ["sourceModes", ["literal", "synthesis", "project"]],
  ["sourceFragmentStatuses", ["cached", "extracted", "source-changed", "missing", "stale"]],
  ["runStatuses", ["queued", "cancelling", "succeeded", "failed", "cancelled"]],
  ["fallbacks", ["unknownRun", "working", "operationFailed", "unknownMode", "unknownStatus", "etaUnknown"]],
].flatMap(([section, keys]) => keys.filter((key) => typeof dynamicZhCN[section]?.[key] !== "string" || !dynamicZhCN[section][key].trim())
  .map((key) => `${section}.${key}`));

function stableKey(source) {
  return `ui_${createHash("sha256").update(source).digest("hex").slice(0, 12)}`;
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

function applyFixedTranslations() {
  let updated = 0;
  for (const [source, zhCN] of Object.entries(FIXED_ZH_CN_TRANSLATIONS)) {
    if (!candidates.has(source)) continue;
    const entry = catalog[source];
    if (!entry) {
      catalog[source] = { key: stableKey(source), en: source, "zh-CN": zhCN };
      updated += 1;
      continue;
    }
    if (entry["zh-CN"] === zhCN) continue;
    entry["zh-CN"] = zhCN;
    updated += 1;
  }
  const sorted = Object.fromEntries(Object.entries(catalog).sort(([left], [right]) => left.localeCompare(right)));
  fs.writeFileSync(catalogPath, `${JSON.stringify(sorted, null, 2)}\n`);
  console.log(`Applied ${updated} fixed Simplified Chinese translations.`);
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
    if (FIXED_ZH_CN_TRANSLATIONS[source] && entry["zh-CN"] !== FIXED_ZH_CN_TRANSLATIONS[source]) {
      invalid.push(source);
    }
    if (entry["zh-CN"] === source && !isFormattingOnly(source) && !UNCHANGED_ZH_CN_SOURCES.has(source)) {
      invalid.push(source);
    }
    const sourceVariables = new Set(source.match(/\{\{v\d+\}\}/g) ?? []);
    const translatedVariables = entry["zh-CN"].match(/\{\{v\d+\}\}/g) ?? [];
    if (translatedVariables.some((variable) => !sourceVariables.has(variable))) invalid.push(source);
  }
  return [...new Set(invalid)];
}

function runtimeCatalog(language) {
  return Object.fromEntries(
    Object.values(catalog)
      .map((entry) => [entry.key, entry[language]])
      .sort(([left], [right]) => left.localeCompare(right)),
  );
}

function writeRuntimeCatalogs() {
  for (const [language, filename] of Object.entries(runtimeCatalogPaths)) {
    fs.writeFileSync(
      filename,
      `${JSON.stringify(runtimeCatalog(language), null, 2)}\n`,
    );
  }
  console.log("Generated compact runtime catalogs for en and zh-CN.");
}

function invalidRuntimeCatalogs() {
  return Object.entries(runtimeCatalogPaths).flatMap(([language, filename]) => {
    if (!fs.existsSync(filename)) return [language];
    const actual = JSON.parse(fs.readFileSync(filename, "utf8"));
    return JSON.stringify(actual) === JSON.stringify(runtimeCatalog(language))
      ? []
      : [language];
  });
}

const keyFlagIndex = process.argv.indexOf("--key");

if (process.argv.includes("--apply-fixed")) {
  applyFixedTranslations();
} else if (process.argv.includes("--prune")) {
  pruneCatalog();
} else if (process.argv.includes("--write-runtime")) {
  writeRuntimeCatalogs();
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
  const invalidRuntime = invalidRuntimeCatalogs();
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
  if (stale.length) {
    console.error(`Catalog contains ${stale.length} unused entries:`);
    for (const source of stale) console.error(`- ${JSON.stringify(source)}`);
  }
  if (invalid.length) {
    console.error(`Catalog contains ${invalid.length} invalid entries:`);
    for (const source of invalid) console.error(`- ${JSON.stringify(source)}`);
  }
  if (invalidRuntime.length) {
    console.error(
      `Runtime catalogs are missing or stale for: ${invalidRuntime.join(", ")}.`,
    );
    console.error("Run `npm run i18n:generate` and commit the generated files.");
  }
  if (missingBackendProgressTranslations.length) {
    console.error(`Missing ${missingBackendProgressTranslations.length} Chinese backend progress labels:`);
    for (const [label, locations] of missingBackendProgressTranslations) {
      console.error(`- ${JSON.stringify(label)} (${locations.slice(0, 3).join(", ")})`);
    }
  }
  if (invalidDynamicValues.length) {
    console.error(`Dynamic Chinese labels are missing or invalid: ${invalidDynamicValues.join(", ")}`);
  }
  if (!missing.length && !stale.length && !invalid.length && !invalidRuntime.length
      && !missingBackendProgressTranslations.length && !invalidDynamicValues.length) {
    console.log(`i18n catalog covers ${candidates.size} user-facing literals and ${backendProgressLabels.size} backend progress labels.`);
  }
  process.exitCode = missing.length || stale.length || invalid.length || invalidRuntime.length
    || missingBackendProgressTranslations.length || invalidDynamicValues.length ? 1 : 0;
}
