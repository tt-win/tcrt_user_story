#!/usr/bin/env node
/*
 * i18n 覆蓋率守門（無外部相依，CI 與本機共用）。
 *
 * 兩項檢查，皆採 baseline 回歸閘（不阻斷既有存量、只擋「新增」缺口）：
 *   1. 三語系葉鍵對稱：載入 app/static/locales/{zh-TW,en-US,zh-CN}.json，
 *      遞迴蒐集葉鍵集合，計算各語系相對「聯集」的缺鍵數；任一語系缺鍵數
 *      超過 baseline 即 fail（複用 i18n.js validateTranslations 的單向缺鍵語意，
 *      擴充為三語系互為基準）。
 *   2. CJK 字面值掃描：app/templates/*.html 文字行（未掛 data-i18n）、
 *      app/static/js/** 的 alert/confirm/showToast/showError 等可見字串（未走 i18n.t）。
 *      允許 scripts/i18n-allowlist.json 暫時豁免分批遷移中的檔案。
 *
 * 用法：
 *   node scripts/check-i18n-coverage.mjs            # 檢查（CI / pre-commit）
 *   node scripts/check-i18n-coverage.mjs --update   # 以目前數量重寫 baseline
 *   node scripts/check-i18n-coverage.mjs --list     # 額外列出各語系缺鍵清單
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
const JS_VISIBLE_CALL = /\b(alert|confirm|showToast|showError|showSuccess|showWarning|showInfo)\s*\(/;

function leafKeys(obj, prefix = "", out = new Set()) {
  if (obj && typeof obj === "object" && !Array.isArray(obj)) {
    for (const [k, v] of Object.entries(obj)) leafKeys(v, prefix ? `${prefix}.${k}` : k, out);
  } else {
    out.add(prefix);
  }
  return out;
}

function walk(dir, exts) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p, exts));
    else if (exts.some((e) => name.endsWith(e))) out.push(p);
  }
  return out;
}

// --- 1. 語系鍵對稱 ---
const keysByLocale = {};
for (const loc of LOCALES) {
  keysByLocale[loc] = leafKeys(JSON.parse(readFileSync(join(LOCALES_DIR, `${loc}.json`), "utf8")));
}
const union = new Set();
for (const loc of LOCALES) for (const k of keysByLocale[loc]) union.add(k);
const missing = {};
for (const loc of LOCALES) missing[loc] = [...union].filter((k) => !keysByLocale[loc].has(k)).sort();

// --- 2. CJK 字面值掃描 ---
let allow = { files: [] };
try {
  allow = JSON.parse(readFileSync(ALLOWLIST, "utf8"));
} catch {
  /* 無 allowlist 視為空 */
}
const allowSet = new Set(allow.files || []);

let cjkTemplateLines = 0;
for (const f of walk(join(ROOT, "app", "templates"), [".html"])) {
  if (allowSet.has(relative(ROOT, f))) continue;
  let inBlockComment = false; // 跨行 {# #} / <!-- --> 區塊註解（非使用者可見字串，略過）
  for (const line of readFileSync(f, "utf8").split("\n")) {
    if (inBlockComment) {
      if (line.includes("#}") || line.includes("-->")) inBlockComment = false;
      continue;
    }
    const t = line.trim();
    if (t.startsWith("{#") || t.startsWith("<!--")) {
      if (!line.includes("#}") && !line.includes("-->")) inBlockComment = true;
      continue;
    }
    if (t.startsWith("//") || t.startsWith("*")) continue;
    if (!CJK.test(line) || line.includes("data-i18n")) continue;
    cjkTemplateLines++;
  }
}

let cjkJsCalls = 0;
for (const f of walk(join(ROOT, "app", "static", "js"), [".js"])) {
  if (allowSet.has(relative(ROOT, f))) continue;
  for (const line of readFileSync(f, "utf8").split("\n")) {
    if (!CJK.test(line) || !JS_VISIBLE_CALL.test(line) || line.includes("i18n.t(")) continue;
    cjkJsCalls++;
  }
}

const current = {
  missingKeys: Object.fromEntries(LOCALES.map((l) => [l, missing[l].length])),
  cjkTemplateLines,
  cjkJsCalls,
};

if (process.argv.includes("--list")) {
  for (const l of LOCALES) console.log(`\n[${l}] 缺 ${missing[l].length} 鍵：\n  ${missing[l].join("\n  ")}`);
}

if (process.argv.includes("--update")) {
  writeFileSync(BASELINE, JSON.stringify(current, null, 2) + "\n");
  console.log("baseline updated:", JSON.stringify(current));
  process.exit(0);
}

let base;
try {
  base = JSON.parse(readFileSync(BASELINE, "utf8"));
} catch {
  console.error("找不到 baseline，請先執行：node scripts/check-i18n-coverage.mjs --update");
  process.exit(2);
}

let failed = false;
for (const l of LOCALES) {
  const cur = current.missingKeys[l];
  const b = base.missingKeys?.[l] ?? Infinity;
  console.log(`${cur > b ? "✗" : "✓"} ${l}: 缺 ${cur} 鍵（baseline ${b}）`);
  if (cur > b) {
    failed = true;
    console.error(`  新增缺鍵（前 10）：`, missing[l].slice(0, 10));
  }
}
for (const [key, label] of [
  ["cjkTemplateLines", "template 未翻譯 CJK 行"],
  ["cjkJsCalls", "JS alert/toast 未翻譯 CJK"],
]) {
  const cur = current[key];
  const b = base[key] ?? Infinity;
  console.log(`${cur > b ? "✗" : "✓"} ${label}：${cur}（baseline ${b}）`);
  if (cur > b) failed = true;
}

if (failed) {
  console.error("\n✗ i18n 覆蓋率回退：請補齊三語系鍵或改走 data-i18n / i18n.t()，勿新增缺鍵或硬編 CJK。");
  process.exit(1);
}
console.log("\n✓ 無 i18n 覆蓋率回退");
