#!/usr/bin/env node
/*
 * i18n coverage regression gate (dependency-free for CI and local use).
 *
 * Checks locale key symmetry and high-confidence user-visible literals in
 * templates/JavaScript. Existing debt is allowed through a count baseline;
 * only increases fail the gate.
 */
import { readFileSync, writeFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const LOCALES_DIR = join(ROOT, "app", "static", "locales");
const LOCALES = ["zh-TW", "en-US", "zh-CN"];
const BASELINE = join(ROOT, "scripts", "i18n-coverage-baseline.json");
const ALLOWLIST = join(ROOT, "scripts", "i18n-allowlist.json");
const CJK = /[一-鿿㐀-䶿豈-﫿]/;
const VISIBLE_ATTRIBUTES = ["placeholder", "title", "aria-label"];
const VISIBLE_CALLS = new Set([
  "alert", "confirm", "showToast", "showError", "showSuccess", "showWarning", "showInfo", "Notification",
]);
const VISIBLE_PROPERTIES = new Set(["placeholder", "title", "ariaLabel", "aria-label", "textContent", "innerHTML"]);
const VOID_ELEMENTS = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"]);

function leafKeys(obj, prefix = "", out = new Set()) {
  if (obj && typeof obj === "object" && !Array.isArray(obj)) {
    for (const [key, value] of Object.entries(obj)) leafKeys(value, prefix ? `${prefix}.${key}` : key, out);
  } else {
    out.add(prefix);
  }
  return out;
}

function walk(dir, extensions) {
  const files = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) files.push(...walk(path, extensions));
    else if (extensions.some((extension) => name.endsWith(extension))) files.push(path);
  }
  return files.sort();
}

function lineAt(source, offset) {
  let line = 1;
  for (let index = 0; index < offset; index++) if (source.charCodeAt(index) === 10) line++;
  return line;
}

function displayValue(raw) {
  return raw
    .replace(/{#[\s\S]*?#}|<!--[\s\S]*?-->/g, " ")
    .replace(/{%[\s\S]*?%}|{{[\s\S]*?}}/g, " ")
    .replace(/&(?:[a-z]+|#\d+|#x[\da-f]+);/gi, " ")
    .replace(/\\(?:n|r|t)/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function isUserVisibleLiteral(raw, { option = false } = {}) {
  const value = displayValue(raw);
  if (!value || !/[A-Za-z一-鿿㐀-䶿豈-﫿]/.test(value)) return false;
  if (/^(?:<[^>]+>\s*)+$/.test(value) || (value.includes("{") && /[\w-]+\s*:[^;{}]+;?/.test(value))) return false;
  if (/^(?:https?:|mailto:|tel:|data:|\/\/|\/(?:api|static|assets)\/)/i.test(value)) return false;
  if (/^(?:e\.?g\.?|for example|example\s*:|例如|例[：:])/i.test(value)) return false;
  if (/^(?:#[-\w]+|[A-Z]{2,}-\d+(?:\s*,\s*[A-Z]{2,}-\d+)*|[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12})$/i.test(value)) return false;
  if (/^(?:(?:[A-Za-z⌘]+[+]\S+)(?:\s*\/\s*(?:[A-Za-z⌘]+[+]\S+))*|Y{2,4}[-/]M{1,2}[-/]D{1,2}|%[a-z]|\{\w+\})$/i.test(value)) return false;
  if (/^(?:As an? \w+|I want to|So that)\.\.\.$/i.test(value)) return false;
  if (/^[A-Za-z][\w.-]*-[\w.-]+$/.test(value)) return false;
  if (/^[\w.-]+\.(?:js|css|html|json|ya?ml|py|txt|csv)$/i.test(value)) return false;
  if (/^[A-Z][A-Z0-9_.:/-]*$/.test(value) || /^[a-z][a-z0-9_.:-]*$/.test(value)) return false;
  if (option && /^[A-Z0-9_.:/-]+(?:\s+[A-Z0-9_.:/-]+)*$/.test(value)) return false;
  return CJK.test(value) || /[A-Za-z]/.test(value);
}

function finding(file, line, kind, value) {
  return { file: relative(ROOT, file), line, kind, value: displayValue(value).slice(0, 100) };
}

function translatedTitleBlocks(source) {
  const blocks = [];
  const pattern = /{%\s*block\s+title\b[\s\S]*?{%\s*endblock\s*%}/g;
  let match;
  while ((match = pattern.exec(source))) {
    if (/\bdata-i18n(?:-[\w-]+)?\s*=|\bi18n\.t\s*\(|\b_\s*\(/.test(match[0])) {
      blocks.push({ start: match.index, end: pattern.lastIndex });
    }
  }
  return blocks;
}

function scanTemplate(file) {
  const source = readFileSync(file, "utf8");
  const findings = [];
  const stack = [];
  const titleBlocks = translatedTitleBlocks(source);
  const tokenPattern = /{#[\s\S]*?#}|<!--[\s\S]*?-->|{%[\s\S]*?%}|{{[\s\S]*?}}|<[^>]*>/g;
  let cursor = 0;
  let match;

  function scanText(text, offset) {
    if (stack.some((entry) => entry.ignored || entry.translated)) return;
    let localOffset = 0;
    for (const lineText of text.split("\n")) {
      const lineOffset = offset + localOffset;
      const translatedTitleSuffix = titleBlocks.some((block) => lineOffset >= block.start && lineOffset < block.end)
        && /^\s*[-|]\s*(?:Test Case Repository(?: Web Tool)?|TCRT)\s*$/i.test(displayValue(lineText));
      if (!translatedTitleSuffix && isUserVisibleLiteral(lineText, { option: stack.at(-1)?.name === "option" })) {
        findings.push(finding(file, lineAt(source, lineOffset), "text", lineText));
      }
      localOffset += lineText.length + 1;
    }
  }

  while ((match = tokenPattern.exec(source))) {
    scanText(source.slice(cursor, match.index), cursor);
    cursor = tokenPattern.lastIndex;
    const tag = match[0];
    if (tag.startsWith("{#") || tag.startsWith("<!--") || tag.startsWith("{%") || tag.startsWith("{{") || /^<!|^<\?/.test(tag)) continue;
    const closing = tag.match(/^<\s*\/\s*([\w:-]+)/);
    if (closing) {
      const name = closing[1].toLowerCase();
      while (stack.length && stack.pop().name !== name) { /* tolerate template-generated unbalanced HTML */ }
      continue;
    }
    const opening = tag.match(/^<\s*([\w:-]+)/);
    if (!opening) continue;
    const name = opening[1].toLowerCase();
    const explicitlyIgnored = /\bdata-i18n-ignore(?:\s*=\s*(?:["'][^"']*["']|[^\s>]+))?(?=\s|\/?>)/i.test(tag)
      || /\btranslate\s*=\s*(["'])no\1/i.test(tag);
    const attributes = new Map();
    const attributePattern = /([^\s=/>]+)\s*=\s*(["'])([\s\S]*?)\2/g;
    let attribute;
    while ((attribute = attributePattern.exec(tag))) {
      attributes.set(attribute[1].toLowerCase(), attribute[3]);
      const attributeName = attribute[1].toLowerCase();
      if (explicitlyIgnored || !VISIBLE_ATTRIBUTES.includes(attributeName)) continue;
      if (attributes.has(`data-i18n-${attributeName}`) || new RegExp(`\\bdata-i18n-${attributeName}\\s*=`, "i").test(tag)) continue;
      if (isUserVisibleLiteral(attribute[3])) {
        findings.push(finding(file, lineAt(source, match.index + attribute.index), `attribute:${attributeName}`, attribute[3]));
      }
    }
    if (!tag.endsWith("/>") && !VOID_ELEMENTS.has(name)) {
      stack.push({
        name,
        translated: /\bdata-i18n\s*=/.test(tag),
        ignored: explicitlyIgnored || name === "script" || name === "style",
      });
    }
  }
  scanText(source.slice(cursor), cursor);
  return findings;
}

function lexJavaScript(source) {
  const tokens = [];
  let index = 0;
  while (index < source.length) {
    const start = index;
    const char = source[index];
    if (/\s/.test(char)) {
      index++;
      continue;
    }
    if (char === "/" && source[index + 1] === "/") {
      index = source.indexOf("\n", index + 2);
      if (index === -1) break;
      continue;
    }
    if (char === "/" && source[index + 1] === "*") {
      index = source.indexOf("*/", index + 2);
      index = index === -1 ? source.length : index + 2;
      continue;
    }
    if (char === '"' || char === "'" || char === "`") {
      const quote = char;
      let interpolated = false;
      index++;
      while (index < source.length) {
        if (source[index] === "\\") index += 2;
        else if (quote === "`" && source[index] === "$" && source[index + 1] === "{") {
          interpolated = true;
          index += 2;
        } else if (source[index] === quote) {
          index++;
          break;
        } else index++;
      }
      tokens.push({ type: "string", value: source.slice(start + 1, index - 1), start, interpolated, quote });
      continue;
    }
    if (/[A-Za-z_$]/.test(char)) {
      index++;
      while (index < source.length && /[\w$]/.test(source[index])) index++;
      tokens.push({ type: "identifier", value: source.slice(start, index), start });
      continue;
    }
    tokens.push({ type: "punct", value: char, start });
    index++;
  }
  return tokens;
}

function closingParen(tokens, openingIndex) {
  let depth = 0;
  for (let index = openingIndex; index < tokens.length; index++) {
    if (tokens[index].value === "(") depth++;
    else if (tokens[index].value === ")" && --depth === 0) return index;
  }
  return -1;
}

function directStringArguments(tokens, openingIndex, closingIndex) {
  const args = [];
  let start = openingIndex + 1;
  let depth = 0;
  for (let index = start; index <= closingIndex; index++) {
    const value = tokens[index]?.value;
    if (index === closingIndex || (value === "," && depth === 0)) {
      const argument = tokens.slice(start, index);
      if (argument.length === 1 && argument[0].type === "string") args.push(argument[0]);
      start = index + 1;
    } else if (["(", "[", "{"].includes(value)) depth++;
    else if ([")", "]", "}"].includes(value)) depth--;
  }
  return args;
}

function isKnownTranslationExpression(expression) {
  return /(?:\b(?:trmTranslate|treTranslate|getLocalizedText|tt|tUsm)\s*\(|\bwindow\s*\.\s*i18n\s*\.\s*t\s*\()/i.test(expression);
}

function expressionLiteralText(expression) {
  const literals = [];
  const pattern = /(["'])(.*?)(?<!\\)\1/g;
  let match;
  while ((match = pattern.exec(expression))) {
    if (isUserVisibleLiteral(match[2])) literals.push(match[2]);
  }
  return literals.join(" ");
}

function templateLiteralText(value) {
  let text = "";
  let index = 0;
  while (index < value.length) {
    if (value[index] !== "$" || value[index + 1] !== "{") {
      text += value[index++];
      continue;
    }

    let depth = 1;
    let quote = null;
    const expressionStart = index + 2;
    index = expressionStart;
    while (index < value.length && depth > 0) {
      const char = value[index];
      if (quote) {
        if (char === "\\") index += 2;
        else {
          if (char === quote) quote = null;
          index++;
        }
      } else if (char === '"' || char === "'" || char === "`") {
        quote = char;
        index++;
      } else {
        if (char === "{") depth++;
        else if (char === "}") depth--;
        index++;
      }
    }

    const expression = value.slice(expressionStart, depth === 0 ? index - 1 : index);
    text += isKnownTranslationExpression(expression) ? " " : ` ${expressionLiteralText(expression)} `;
  }
  return text;
}

function visibleMarkupText(raw) {
  return raw.replace(/<[^>]*>/g, (tag) => {
    const attributes = [];
    const pattern = /\b(?:placeholder|title|aria-label)(?=\s*=)\s*=\s*(["'])([\s\S]*?)\1/gi;
    let match;
    while ((match = pattern.exec(tag))) attributes.push(match[2]);
    return ` ${attributes.join(" ")} `;
  });
}

function scanJavaScript(file) {
  const source = readFileSync(file, "utf8");
  const tokens = lexJavaScript(source);
  const findings = [];
  const seen = new Set();

  function add(token, kind) {
    if (!token || token.type !== "string") return;
    const literalText = token.quote === "`" && token.interpolated
      ? templateLiteralText(token.value)
      : token.value;
    if (/\bdata-i18n(?:-[\w-]+)?\s*=/.test(literalText)) return;
    const visibleValue = visibleMarkupText(literalText);
    if (!isUserVisibleLiteral(visibleValue)) return;
    const key = `${token.start}:${kind}`;
    if (seen.has(key)) return;
    seen.add(key);
    findings.push(finding(file, lineAt(source, token.start), kind, visibleValue));
  }

  for (let index = 0; index < tokens.length; index++) {
    const token = tokens[index];
    if (token.type === "identifier" && VISIBLE_CALLS.has(token.value) && tokens[index + 1]?.value === "(") {
      const close = closingParen(tokens, index + 1);
      if (close !== -1) for (const argument of directStringArguments(tokens, index + 1, close)) add(argument, `call:${token.value}`);
    }

    if (token.type === "identifier" && token.value === "insertAdjacentHTML" && tokens[index + 1]?.value === "(") {
      const close = closingParen(tokens, index + 1);
      if (close !== -1) for (const argument of directStringArguments(tokens, index + 1, close)) add(argument, "call:insertAdjacentHTML");
    }

    if (token.type === "identifier" && VISIBLE_PROPERTIES.has(token.value) && tokens[index - 1]?.value === "." && tokens[index + 1]?.value === "=") {
      add(tokens[index + 2], `assignment:${token.value}`);
    }
    if (token.type === "string" && VISIBLE_PROPERTIES.has(token.value) && tokens[index - 1]?.value === "[" && tokens[index + 1]?.value === "]" && tokens[index + 2]?.value === "=") {
      add(tokens[index + 3], `assignment:${token.value}`);
    }
    if (token.type === "identifier" && token.value === "setAttribute" && tokens[index + 1]?.value === "(") {
      const close = closingParen(tokens, index + 1);
      const args = close === -1 ? [] : directStringArguments(tokens, index + 1, close);
      if (args.length === 2 && VISIBLE_PROPERTIES.has(args[0].value)) add(args[1], `assignment:${args[0].value}`);
    }
  }
  return findings;
}

const keysByLocale = Object.fromEntries(LOCALES.map((locale) => [
  locale,
  leafKeys(JSON.parse(readFileSync(join(LOCALES_DIR, `${locale}.json`), "utf8"))),
]));
const union = new Set(LOCALES.flatMap((locale) => [...keysByLocale[locale]]));
const missing = Object.fromEntries(LOCALES.map((locale) => [
  locale,
  [...union].filter((key) => !keysByLocale[locale].has(key)).sort(),
]));

let allow = { files: [] };
try {
  allow = JSON.parse(readFileSync(ALLOWLIST, "utf8"));
} catch {
  // A missing allowlist is equivalent to an empty allowlist.
}
const allowSet = new Set(allow.files || []);
const templateFindings = walk(join(ROOT, "app", "templates"), [".html"])
  .filter((file) => !allowSet.has(relative(ROOT, file)))
  .flatMap(scanTemplate);
const jsFindings = walk(join(ROOT, "app", "static", "js"), [".js"])
  .filter((file) => !allowSet.has(relative(ROOT, file)))
  .flatMap(scanJavaScript);

const current = {
  missingKeys: Object.fromEntries(LOCALES.map((locale) => [locale, missing[locale].length])),
  cjkTemplateLines: templateFindings.length,
  cjkJsCalls: jsFindings.length,
};

if (process.argv.includes("--list")) {
  for (const locale of LOCALES) console.log(`\n[${locale}] missing ${missing[locale].length} keys:\n  ${missing[locale].join("\n  ")}`);
  for (const [label, findings] of [["template literals", templateFindings], ["JavaScript literals", jsFindings]]) {
    console.log(`\n[${label}] ${findings.length} findings:`);
    for (const item of findings) console.log(`  ${item.file}:${item.line} [${item.kind}] ${JSON.stringify(item.value)}`);
  }
}

if (process.argv.includes("--update")) {
  writeFileSync(BASELINE, `${JSON.stringify(current, null, 2)}\n`);
  console.log("baseline updated:", JSON.stringify(current));
  process.exit(0);
}

let base;
try {
  base = JSON.parse(readFileSync(BASELINE, "utf8"));
} catch {
  console.error("Baseline not found. Run: node scripts/check-i18n-coverage.mjs --update");
  process.exit(2);
}

let failed = false;
for (const locale of LOCALES) {
  const count = current.missingKeys[locale];
  const baseline = base.missingKeys?.[locale] ?? Infinity;
  console.log(`${count > baseline ? "x" : "ok"} ${locale}: ${count} missing keys (baseline ${baseline})`);
  if (count > baseline) {
    failed = true;
    console.error("  New missing keys (first 10):", missing[locale].slice(0, 10));
  }
}
for (const [key, label] of [
  ["cjkTemplateLines", "template hardcoded user-visible literals"],
  ["cjkJsCalls", "JavaScript hardcoded user-visible literals"],
]) {
  const count = current[key];
  const baseline = base[key] ?? Infinity;
  console.log(`${count > baseline ? "x" : "ok"} ${label}: ${count} (baseline ${baseline})`);
  if (count > baseline) failed = true;
}

if (failed) {
  console.error("\nx i18n coverage regressed. Add data-i18n/i18n.t() instead of new user-visible literals or missing keys.");
  process.exit(1);
}
console.log("\nok no i18n coverage regression");
