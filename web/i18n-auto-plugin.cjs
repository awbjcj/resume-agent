const fs = require("node:fs");
const path = require("node:path");

const catalog = JSON.parse(
  fs.readFileSync(path.join(__dirname, "src", "i18n", "auto-catalog.json"), "utf8"),
);

const UI_PROPS = new Set([
  "actionLabel", "alt", "aria-label", "assistantName", "body", "cancelLabel",
  "confirmLabel", "description", "detail", "emptyMessage", "errorMessage", "footer",
  "heading", "helpText", "hint", "kicker", "label", "placeholder", "sub", "subtitle",
  "successMessage", "task", "title",
]);
const UI_VARIABLE = /(action|caption|description|detail|empty|error|heading|help|hint|label|message|placeholder|status|subtitle|success|text|title)$/i;
const UI_COLLECTION = /(actions|cards|fields|filters|items|kinds|labels|modalities|nav|options|outcomes|results|rows|scopes|sections|stages|statuses|steps|tabs)$/i;

const clean = (value) => value.replace(/\s+/g, " ").trim();
const isHumanText = (value) => {
  const text = clean(value);
  return Boolean(
    text
      && /[A-Za-z]/.test(text)
      && !/^(https?:|\/api\/|[.#@]|[a-z]+:\/\/)/i.test(text)
      && !/(^|\s)(sm|md|lg|xl|2xl|dark|hover|focus|data|group|peer):/.test(text)
      && !/(^|\s)(flex|grid|block|hidden|relative|absolute|w-|h-|p[trblxy]?-[\d[]|m[trblxy]?-[\d[]|text-|bg-|border-|rounded-|gap-|items-|justify-|space-|min-|max-|overflow-|shadow-|ring-)/.test(text)
      && !(/\b(?:text|bg|border|rounded|tracking|leading|font|w|h|min|max|p[trblxy]?|m[trblxy]?|gap|items|justify|shadow|ring|opacity)-[^\s]+/.test(text) && !/[.!?]/.test(text)),
  );
};
const jsxAttributeName = (node) => node.name.type === "JSXIdentifier" ? node.name.name : null;
const propertyName = (node) => {
  if (node.computed) return null;
  return node.key.type === "Identifier" || node.key.type === "StringLiteral"
    ? node.key.name ?? node.key.value
    : null;
};
const directVariable = (pathRef) => {
  const declaration = pathRef.findParent((candidate) => candidate.isVariableDeclarator());
  if (!declaration || declaration.node.id.type !== "Identifier") return null;
  const init = declaration.get("init");
  if (init === pathRef) return { name: declaration.node.id.name, array: false };
  if (pathRef.parentPath?.isArrayExpression() && init === pathRef.parentPath) return { name: declaration.node.id.name, array: true };
  let current = pathRef.parentPath;
  while (current?.isConditionalExpression() || current?.isLogicalExpression()) current = current.parentPath;
  if (current === init) return { name: declaration.node.id.name, array: false };
  return null;
};
const jsxAttribute = (pathRef) => {
  if (pathRef.parentPath?.isJSXAttribute()) return pathRef.parentPath;
  if (pathRef.parentPath?.isJSXExpressionContainer() && pathRef.parentPath.parentPath?.isJSXAttribute()) return pathRef.parentPath.parentPath;
  return null;
};
const namedUiFunction = (pathRef) => {
  const fn = pathRef.findParent((candidate) => candidate.isFunctionDeclaration() || candidate.isFunctionExpression() || candidate.isArrowFunctionExpression());
  if (!fn) return false;
  let name = fn.node.id?.name;
  if (!name && fn.parentPath?.isVariableDeclarator() && fn.parentPath.node.id.type === "Identifier") name = fn.parentPath.node.id.name;
  if (!name || !UI_VARIABLE.test(name)) return false;
  let current = pathRef;
  while (current.parentPath?.isConditionalExpression() || current.parentPath?.isLogicalExpression()) current = current.parentPath;
  if (current.parentPath?.isReturnStatement()) return current.parentPath.findParent((candidate) => candidate.isFunction()) === fn;
  return fn.isArrowFunctionExpression() && fn.get("body") === current;
};
const uiCollectorCall = (pathRef) => {
  const call = pathRef.findParent((candidate) => candidate.isCallExpression());
  if (!call) return false;
  let argument = pathRef;
  while (argument.parentPath && argument.parentPath !== call) argument = argument.parentPath;
  if (argument.parentPath !== call || argument.listKey !== "arguments") return false;
  if (call.node.callee.type === "Identifier") return call.node.callee.name === "scalar" && argument.key === 1;
  const callee = call.node.callee;
  if (!(callee.type === "MemberExpression" && callee.object.type === "Identifier"
    && callee.property.type === "Identifier" && callee.property.name === "push"
    && UI_COLLECTION.test(callee.object.name))) return false;
  if (argument === pathRef) return true;
  return argument.isArrayExpression() && argument.get("elements.0") === pathRef;
};
const isToastCall = (pathRef) => {
  const call = pathRef.findParent((candidate) => candidate.isCallExpression());
  if (!call) return false;
  const callee = call.node.callee;
  return callee.type === "MemberExpression"
    && callee.object.type === "Identifier"
    && callee.object.name === "toast";
};
const outputPosition = (pathRef) => {
  let current = pathRef;
  if (current.parentPath?.isConditionalExpression()) {
    if (current.key !== "consequent" && current.key !== "alternate") return false;
    current = current.parentPath;
  }
  const container = current.parentPath;
  return Boolean(container?.isJSXExpressionContainer()
    && (container.parentPath?.isJSXElement() || container.parentPath?.isJSXFragment()));
};
const isLocalizable = (pathRef) => {
  if (pathRef.isJSXText()) return isHumanText(pathRef.node.value);
  if (!pathRef.isStringLiteral() && !pathRef.isTemplateLiteral()) return false;
  const value = pathRef.isTemplateLiteral() ? templateSource(pathRef.node) : pathRef.node.value;
  if (!isHumanText(value)) return false;
  const parent = pathRef.parentPath;
  const attribute = jsxAttribute(pathRef);
  if (attribute) return UI_PROPS.has(jsxAttributeName(attribute.node));
  if (outputPosition(pathRef) || isToastCall(pathRef) || uiCollectorCall(pathRef)) return true;
  if (parent?.isObjectProperty() && UI_PROPS.has(propertyName(parent.node))) return true;
  const variable = directVariable(pathRef);
  if (variable && !variable.array && UI_VARIABLE.test(variable.name)) return true;
  if (variable?.array && UI_COLLECTION.test(variable.name)) return true;
  return namedUiFunction(pathRef);
};
const templateSource = (node) => node.quasis
  .map((quasi, index) => `${quasi.value.cooked ?? quasi.value.raw}${index < node.expressions.length ? `{{v${index}}}` : ""}`)
  .join("");

module.exports = function autoI18nPlugin({ types: t }) {
  return {
    name: "resume-agent-auto-i18n",
    visitor: {
      Program: {
        enter(programPath, state) {
          state.autoI18n = {
            imported: false,
            programPath,
            identifier: programPath.scope.generateUidIdentifier("autoI18n"),
          };
        },
        exit(programPath, state) {
          if (!state.autoI18n.imported) return;
          programPath.unshiftContainer(
            "body",
            t.importDeclaration(
              [t.importDefaultSpecifier(state.autoI18n.identifier)],
              t.stringLiteral("@/i18n"),
            ),
          );
        },
      },
      JSXText(pathRef, state) {
        if (!isLocalizable(pathRef)) return;
        replace(pathRef, state, pathRef.node.value, true);
      },
      StringLiteral(pathRef, state) {
        if (!isLocalizable(pathRef)) return;
        replace(pathRef, state, pathRef.node.value, false);
      },
      TemplateLiteral(pathRef, state) {
        if (!isLocalizable(pathRef)) return;
        const source = templateSource(pathRef.node);
        const entry = catalog[source];
        if (!entry) return;
        state.autoI18n.imported = true;
        const values = pathRef.node.expressions.map((expression, index) =>
          t.objectProperty(t.identifier(`v${index}`), expression),
        );
        pathRef.replaceWith(
          t.callExpression(
            t.memberExpression(state.autoI18n.identifier, t.identifier("t")),
            [t.stringLiteral(`auto.${entry.key}`), t.objectExpression(values)],
          ),
        );
      },
    },
  };

  function replace(pathRef, state, rawValue, jsxText) {
    const source = clean(rawValue);
    const entry = catalog[source];
    if (!entry) return;
    state.autoI18n.imported = true;
    const call = t.callExpression(
      t.memberExpression(state.autoI18n.identifier, t.identifier("t")),
      [t.stringLiteral(`auto.${entry.key}`)],
    );
    if (!jsxText) {
      if (pathRef.parentPath?.isJSXAttribute()) {
        pathRef.replaceWith(t.jsxExpressionContainer(call));
      } else {
        pathRef.replaceWith(call);
      }
      return;
    }
    const leading = /^[ \t]+/.test(rawValue) ? " " : "";
    const trailing = /[ \t]+$/.test(rawValue) ? " " : "";
    let expression = call;
    if (leading) expression = t.binaryExpression("+", t.stringLiteral(leading), expression);
    if (trailing) expression = t.binaryExpression("+", expression, t.stringLiteral(trailing));
    pathRef.replaceWith(t.jsxExpressionContainer(expression));
  }
};
