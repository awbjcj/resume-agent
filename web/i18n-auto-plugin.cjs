const fs = require("node:fs");
const path = require("node:path");

const catalog = JSON.parse(
  fs.readFileSync(path.join(__dirname, "src", "i18n", "auto-catalog.json"), "utf8"),
);

const { clean, isLocalizableStringPath, jsxTextWhitespace, templateSource } = require("./i18n-classifier.cjs");

module.exports = function autoI18nPlugin({ types: t }) {
  const useActiveLocale = (state) => {
    state.autoI18n.imported = true;
    return t.memberExpression(state.autoI18n.identifier, t.identifier("resolvedLanguage"));
  };
  const localizeLocaleArgument = (pathRef, state) => {
    const args = pathRef.node.arguments;
    if (args.length === 0) {
      args.push(useActiveLocale(state));
      return;
    }
    const first = args[0];
    if (
      (first.type === "Identifier" && first.name === "undefined")
      || (first.type === "StringLiteral" && first.value === "en-US")
    ) {
      args[0] = useActiveLocale(state);
    }
  };
  const isIntlFormatter = (callee) => callee.type === "MemberExpression"
    && callee.object.type === "Identifier"
    && callee.object.name === "Intl"
    && callee.property.type === "Identifier"
    && (callee.property.name === "NumberFormat" || callee.property.name === "DateTimeFormat");

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
        if (!isLocalizableStringPath(pathRef)) return;
        replace(pathRef, state, pathRef.node.value, true);
      },
      StringLiteral(pathRef, state) {
        if (!isLocalizableStringPath(pathRef)) return;
        replace(pathRef, state, pathRef.node.value, false);
      },
      TemplateLiteral(pathRef, state) {
        if (!isLocalizableStringPath(pathRef)) return;
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
      CallExpression(pathRef, state) {
        const callee = pathRef.node.callee;
        if (isIntlFormatter(callee)) {
          localizeLocaleArgument(pathRef, state);
          return;
        }
        if (
          callee.type === "MemberExpression"
          && callee.property.type === "Identifier"
          && ["toLocaleString", "toLocaleDateString", "toLocaleTimeString"].includes(callee.property.name)
        ) {
          localizeLocaleArgument(pathRef, state);
        }
      },
      NewExpression(pathRef, state) {
        if (isIntlFormatter(pathRef.node.callee)) localizeLocaleArgument(pathRef, state);
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
    const displayText = jsxTextWhitespace(rawValue);
    const leading = displayText.startsWith(" ") ? " " : "";
    const trailing = displayText.endsWith(" ") ? " " : "";
    let expression = call;
    if (leading) expression = t.binaryExpression("+", t.stringLiteral(leading), expression);
    if (trailing) expression = t.binaryExpression("+", expression, t.stringLiteral(trailing));
    pathRef.replaceWith(t.jsxExpressionContainer(expression));
  }
};
