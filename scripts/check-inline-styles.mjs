#!/usr/bin/env node
/*
 * 前端 inline-style 回退守門。
 *
 * 統計 app/templates 內 inline `style="` 的數量並與 baseline 比較：
 *   - 數量 > baseline → 失敗（阻擋新增 inline style；請改用 utility class / token）。
 *   - 數量 <= baseline → 通過（並提示可隨清理進度收斂 baseline）。
 *
 * 用法：
 *   node scripts/check-inline-styles.mjs            # 檢查（CI / pre-commit）
 *   node scripts/check-inline-styles.mjs --update   # 以目前數量重寫 baseline
 *
 * 純 Node、無外部相依；與 stylelint 共同構成前端一致性護欄。
 */
import { readFileSync, writeFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const TEMPLATES = join(ROOT, "app", "templates");
const BASELINE = join(ROOT, "scripts", "frontend-lint-baseline.json");

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (name.endsWith(".html")) out.push(p);
  }
  return out;
}

let total = 0;
const perFile = {};
for (const file of walk(TEMPLATES)) {
  const matches = readFileSync(file, "utf8").match(/style="/g);
  const n = matches ? matches.length : 0;
  if (n) perFile[relative(ROOT, file)] = n;
  total += n;
}

if (process.argv.includes("--update")) {
  writeFileSync(BASELINE, JSON.stringify({ inlineStyles: total, perFile }, null, 2) + "\n");
  console.log(`baseline updated: inlineStyles=${total}`);
  process.exit(0);
}

let baseline = { inlineStyles: Infinity };
try {
  baseline = JSON.parse(readFileSync(BASELINE, "utf8"));
} catch {
  console.error("找不到 baseline，請先執行：npm run baseline");
  process.exit(2);
}

console.log(`inline style= 總數：${total}（baseline ${baseline.inlineStyles}）`);
if (total > baseline.inlineStyles) {
  console.error(
    `✗ inline-style regression：${total} > baseline ${baseline.inlineStyles}。` +
      "請改用 utility class / design token，勿新增 inline style=。"
  );
  process.exit(1);
}
if (total < baseline.inlineStyles) {
  console.log(`↓ 低於 baseline，可執行 npm run baseline 收斂至 ${total}`);
}
console.log("✓ 無 inline-style 回退");
