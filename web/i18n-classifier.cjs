const UI_PROPS = new Set([
  "actionLabel", "alt", "aria-label", "assistantName", "body", "cancelLabel",
  "confirmLabel", "description", "detail", "emptyMessage", "errorMessage", "footer",
  "heading", "helpText", "hint", "kicker", "label", "placeholder", "sub", "subtitle",
  "successMessage", "task", "title",
]);
UI_PROPS.add("caption");
UI_PROPS.add("eyebrow");
UI_PROPS.add("header");
UI_PROPS.add("noun");
UI_PROPS.add("help");
UI_PROPS.add("message");
UI_PROPS.add("note");
const UI_VARIABLE = /(action|badge|caption|date|description|detail|empty|error|eyebrow|fallback|heading|help|hint|label|message|notice|note|placeholder|progress|reason|status|subtitle|success|suffix|summary|text|title)$/i;
const UI_COLLECTION = /(actions|cards|columns|copy|descriptions|details|errors|fields|filters|items|kinds|labels|messages|meta|modalities|names|nav|options|outcomes|parts|results|rows|scopes|sections|stages|statuses|steps|tabs|titles)$/i;
const STYLE_VARIABLE = /(?:class(?:name)?|classes|style)$/i;
const TAILWIND_UTILITY_TOKEN = /^(?:[a-z0-9_/-]+:)*(?:!?)(?:flex|inline-flex|grid|inline-grid|block|inline-block|hidden|relative|absolute|fixed|sticky|uppercase|lowercase|capitalize|truncate|sr-only|(?:whitespace|w|h|min-w|max-w|min-h|max-h|size|p[trblxy]?|m[trblxy]?|text|bg|border|rounded|tracking|leading|font|gap|items|justify|space|overflow|shadow|ring|opacity|transition|duration|ease|animate|cursor)-.+)$/;
const I18N_KEY = /^[a-z][a-z0-9]*(?:\.[a-z0-9_-]+)+$/i;
const variableInit = (declaration) => {
  let init = declaration.get("init");
  while (init.isTSAsExpression() || init.isTSSatisfiesExpression() || init.isTypeCastExpression()) init = init.get("expression");
  return init;
};

const clean = (value) => value.replace(/\s+/g, " ").trim();
const jsxTextWhitespace = (value) => {
  const lines = value.split(/\r\n|\n|\r/);
  let lastNonEmptyLine = 0;
  for (let index = 0; index < lines.length; index += 1) {
    if (/[^\t ]/.test(lines[index])) lastNonEmptyLine = index;
  }
  return lines.map((rawLine, index) => {
    let line = rawLine.replace(/\t/g, " ");
    if (index !== 0) line = line.replace(/^ +/, "");
    if (index !== lines.length - 1) line = line.replace(/ +$/, "");
    if (line && index !== lastNonEmptyLine) line += " ";
    return line;
  }).join("");
};
const isHumanText = (value) => {
  const text = clean(value);
  return Boolean(
    text
      && /[A-Za-z]/.test(text)
      && !/^(https?:|\/api\/|[.#@]|[a-z]+:\/\/)/i.test(text)
      && !/(^|\s)(sm|md|lg|xl|2xl|dark|hover|focus|data|group|peer):/.test(text)
      && !text.split(/\s+/).every((token) => TAILWIND_UTILITY_TOKEN.test(token)),
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
  const init = variableInit(declaration);
  if (init.node === pathRef.node) return { name: declaration.node.id.name, array: false };
  if (pathRef.parentPath?.isArrayExpression() && init.node === pathRef.parentPath.node) return { name: declaration.node.id.name, array: true };
  let current = pathRef;
  while (current.parentPath?.isConditionalExpression() || current.parentPath?.isLogicalExpression()) current = current.parentPath;
  if (current?.node === init.node) return { name: declaration.node.id.name, array: false };
  return null;
};
const uiCollectionValue = (pathRef) => {
  const declaration = pathRef.findParent((candidate) => candidate.isVariableDeclarator());
  if (!declaration || declaration.node.id.type !== "Identifier" || !UI_COLLECTION.test(declaration.node.id.name)) return false;
  const init = variableInit(declaration);
  if (!init.isArrayExpression() && !init.isObjectExpression()) return false;
  let current = pathRef;
  while (current.parentPath && current.parentPath.node !== init.node && !current.parentPath.isFunction()) {
    if (current.parentPath.isArrayExpression() && current.parentPath.parentPath?.node === init.node) {
      return current.listKey === "elements"
        && (Number(current.key) > 0 || /\s|^[A-Z][a-z]/.test(pathRef.isStringLiteral() ? pathRef.node.value : templateSource(pathRef.node)));
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
};
const jsxAttribute = (pathRef) => {
  let current = pathRef;
  while (current.parentPath) {
    const parent = current.parentPath;
    if (parent.isJSXAttribute()) return parent;
    if (parent.isJSXExpressionContainer() && parent.parentPath?.isJSXAttribute()) return parent.parentPath;
    if (!isValueWrapper(current, parent)) return null;
    current = parent;
  }
  return null;
};
const uiObjectProperty = (pathRef) => {
  let current = pathRef;
  while (current.parentPath) {
    const parent = current.parentPath;
    if (parent.isObjectProperty()) return parent.get("value").node === current.node && UI_PROPS.has(propertyName(parent.node));
    if (!isValueWrapper(current, parent)) return false;
    current = parent;
  }
  return false;
};
const uiDefaultParameter = (pathRef) => {
  const assignment = pathRef.findParent((candidate) => candidate.isAssignmentPattern() || candidate.isFunction());
  return Boolean(assignment?.isAssignmentPattern() && assignment.node.left.type === "Identifier" && UI_VARIABLE.test(assignment.node.left.name));
};
const uiSetterCall = (pathRef) => {
  const call = pathRef.findParent((candidate) => candidate.isCallExpression() || candidate.isFunction());
  if (!call?.isCallExpression()) return false;
  const callee = call.node.callee;
  if (callee.type === "Identifier") return /^set.*(Error|Message|Notice|Summary)$/.test(callee.name);
  return callee.type === "MemberExpression" && callee.property.type === "Identifier"
    && /^(fail|set.*(?:Error|Message|Notice|Summary))$/.test(callee.property.name);
};
const uiErrorMessage = (pathRef) => {
  const creation = pathRef.findParent((candidate) => candidate.isNewExpression() || candidate.isFunction());
  return Boolean(creation?.isNewExpression()
    && creation.node.callee.type === "Identifier"
    && (creation.node.callee.name === "Error" || creation.node.callee.name === "RangeError"));
};
const uiAttributeFunctionValue = (pathRef) => {
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
};
const uiRenderedCallbackValue = (pathRef) => {
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
};
const uiNamedObjectMap = (pathRef) => {
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
};
const uiNamedCall = (pathRef) => {
  const call = pathRef.findParent((candidate) => candidate.isCallExpression() || candidate.isFunction());
  return Boolean(call?.isCallExpression()
    && call.node.callee.type === "Identifier"
    && (call.node.callee.name === "label"
      || call.node.callee.name === "pluralLabel"
      || /Message$/.test(call.node.callee.name)));
};
const uiChartName = (pathRef) => {
  const attribute = jsxAttribute(pathRef);
  if (!attribute?.isJSXAttribute() || jsxAttributeName(attribute.node) !== "name") return false;
  const opening = attribute.parentPath;
  const elementName = opening?.isJSXOpeningElement() && opening.node.name.type === "JSXIdentifier"
    ? opening.node.name.name
    : "";
  return ["Area", "Bar", "Line", "Pie", "Radar", "RadialBar", "Scatter"].includes(elementName);
};
const uiJsxCollectionValue = (pathRef) => {
  const attribute = pathRef.findParent((candidate) => candidate.isJSXAttribute() || candidate.isFunction());
  if (!attribute?.isJSXAttribute() || jsxAttributeName(attribute.node) !== "items") return false;
  const tuple = pathRef.parentPath;
  return Boolean(tuple?.isArrayExpression() && tuple.parentPath?.isArrayExpression()
    && pathRef.listKey === "elements" && Number(pathRef.key) === 0);
};
const namedUiFunction = (pathRef) => {
  const fn = pathRef.findParent((candidate) => candidate.isFunctionDeclaration() || candidate.isFunctionExpression() || candidate.isArrowFunctionExpression());
  if (!fn) return false;
  let name = fn.node.id?.name;
  if (!name && fn.parentPath?.isVariableDeclarator() && fn.parentPath.node.id.type === "Identifier") name = fn.parentPath.node.id.name;
  if (!name || (!UI_VARIABLE.test(name) && !/(label|title|formatDate|formatCountdown|recency)/i.test(name))) return false;
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
  while (current.parentPath) {
    const parent = current.parentPath;
    if (parent.isJSXExpressionContainer()) return Boolean(parent.parentPath?.isJSXElement() || parent.parentPath?.isJSXFragment());
    if (!isValueWrapper(current, parent)) return false;
    current = parent;
  }
  return false;
};
const isValueWrapper = (current, parent) => isRenderedBranch(current, parent)
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
const isRenderedBranch = (current, parent) => {
  if (parent.isConditionalExpression()) return current.key === "consequent" || current.key === "alternate";
  if (parent.isLogicalExpression()) return current.key === "right";
  if (parent.isBinaryExpression()) return parent.node.operator === "+";
  return parent.isTSAsExpression() || parent.isTSSatisfiesExpression() || parent.isParenthesizedExpression();
};
const isTranslationKey = (pathRef) => {
  const call = pathRef.findParent((candidate) => candidate.isCallExpression() || candidate.isFunction());
  if (!call?.isCallExpression()) return false;
  const callee = call.node.callee;
  return (callee.type === "Identifier" && callee.name === "t")
    || (callee.type === "MemberExpression" && callee.property.type === "Identifier" && callee.property.name === "t");
};
const isTemplateFragment = (pathRef) => {
  const template = pathRef.findParent((candidate) => candidate.isTemplateLiteral() || candidate.isFunction());
  return Boolean(template?.isTemplateLiteral() && isLocalizableStringPath(template));
};
const isLocalizableStringPath = (pathRef) => {
  if (pathRef.isJSXText()) return isHumanText(pathRef.node.value);
  if (!pathRef.isStringLiteral() && !pathRef.isTemplateLiteral()) return false;
  if (pathRef.findParent((candidate) => candidate.isTSLiteralType() || candidate.isTSTypeAnnotation() || candidate.isTSUnionType())) return false;
  const value = pathRef.isTemplateLiteral() ? templateSource(pathRef.node) : pathRef.node.value;
  if (I18N_KEY.test(value)) return false;
  if (!isHumanText(value)) return false;
  if (pathRef.parentPath?.isMemberExpression() && pathRef.key === "property") return false;
  if (isTranslationKey(pathRef)) return false;
  if (!pathRef.isTemplateLiteral() && isTemplateFragment(pathRef)) return false;
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
  if (variable && !variable.array && !STYLE_VARIABLE.test(variable.name) && UI_VARIABLE.test(variable.name)) return true;
  if (uiCollectionValue(pathRef)) return true;
  return namedUiFunction(pathRef);
};
const templateSource = (node) => node.quasis
  .map((quasi, index) => `${quasi.value.cooked ?? quasi.value.raw}${index < node.expressions.length ? `{{v${index}}}` : ""}`)
  .join("");

module.exports = { clean, isHumanText, isLocalizableStringPath, jsxTextWhitespace, templateSource };
