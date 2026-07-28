// i18n interpolation and static parameter contract tests:
//   node --test app/testsuite/js/i18n.test.mjs
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, '../..', '..');
const source = readFileSync(path.join(root, 'app/static/js/i18n.js'), 'utf8');

function createI18nSystem() {
  const warnings = [];
  const context = vm.createContext({
    console: {
      error() {},
      info() {},
      log() {},
      table() {},
      warn(...args) {
        warnings.push(args.join(' '));
      },
    },
    CustomEvent: class CustomEvent {
      constructor(type, init = {}) {
        this.type = type;
        this.detail = init.detail;
      }
    },
    Element: class Element {},
    document: {
      addEventListener() {},
      dispatchEvent() {},
      documentElement: {},
      querySelectorAll() {
        return [];
      },
    },
    fetch: async () => ({
      ok: true,
      status: 200,
      async json() {
        return {};
      },
    }),
    localStorage: {
      getItem() {
        return null;
      },
      removeItem() {},
      setItem() {},
    },
    navigator: {
      language: 'en-US',
      languages: ['en-US'],
    },
    window: {
      addEventListener() {},
      i18nDebugEnabled: false,
      location: { hostname: 'test' },
    },
  });

  vm.runInContext(`${source}\nthis.__i18nSystem = I18nSystem;`, context);
  return { system: context.window.i18n, warnings };
}

function flattenTranslations(value, prefix = '', result = {}) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    for (const [key, child] of Object.entries(value)) {
      flattenTranslations(child, prefix ? `${prefix}.${key}` : key, result);
    }
  } else if (typeof value === 'string') {
    result[prefix] = value;
  }
  return result;
}

function interpolationKeys(text) {
  const keys = [];
  text.replace(/\{(\w+)\}/g, (match, key, offset) => {
    if (text[offset - 1] !== '{' && text[offset + match.length] !== '}') {
      keys.push(key);
    }
    return match;
  });
  return [...new Set(keys)];
}

test('literal double-braced prompt tokens do not trigger interpolation warnings', () => {
  const { system, warnings } = createI18nSystem();
  const text = 'System Prompt template (exactly one {{SKILL_CATALOG}} required)';

  assert.equal(system.interpolate(text, {}, 'assistantAdmin.promptLabel'), text);
  assert.deepEqual(warnings, []);
});

test('single-braced translations still interpolate and report missing keys', () => {
  const { system, warnings } = createI18nSystem();

  assert.equal(system.interpolate('Selected {count} items', { count: 3 }, 'testCaseSet.selectedCount'), 'Selected 3 items');
  assert.equal(system.interpolate('Selected {count} items', {}, 'testCaseSet.selectedCount'), 'Selected {count} items');
  assert.match(warnings.at(-1), /testCaseSet\.selectedCount.*count/);
});

test('static parameterized i18n attributes always declare matching params', () => {
  const locale = JSON.parse(readFileSync(path.join(root, 'app/static/locales/en-US.json'), 'utf8'));
  const translations = flattenTranslations(locale);
  const files = execFileSync('rg', ['--files', path.join(root, 'app/templates')], { encoding: 'utf8' })
    .trim()
    .split('\n')
    .filter(Boolean);
  const attributePattern = /<[^>]*\b(data-i18n(?:-(?:title|placeholder|aria-label|alt|value))?)\s*=\s*(["'])([^"']+)\2[^>]*>/gs;
  const offenders = [];

  for (const file of files) {
    const html = readFileSync(file, 'utf8');
    for (const match of html.matchAll(attributePattern)) {
      const tag = match[0];
      const attribute = match[1];
      const key = match[3];
      const translation = translations[key];
      if (typeof translation !== 'string' || interpolationKeys(translation).length === 0) continue;

      const paramsAttribute = attribute === 'data-i18n'
        ? 'data-i18n-params'
        : `${attribute}-params`;
      if (!new RegExp(`\\b${paramsAttribute.replaceAll('-', '\\-')}\\s*=`).test(tag)) {
        offenders.push(`${path.relative(root, file)}: ${attribute}=${key}`);
      }
    }
  }

  assert.deepEqual(offenders, []);
});
