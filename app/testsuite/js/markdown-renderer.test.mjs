import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createServer } from 'node:http';
import { createServer as createTcpServer } from 'node:net';
import { readFileSync, existsSync, readdirSync, mkdtempSync, rmSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { fileURLToPath, pathToFileURL } from 'node:url';
import os from 'node:os';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const staticRoot = path.join(here, '../../static');
const commonmarkModule = await import(pathToFileURL(path.join(staticRoot, 'vendor/commonmark/commonmark.esm.mjs')).href);
const commonmark = commonmarkModule.default || commonmarkModule;
try { delete globalThis.commonmark; } catch (_) { globalThis.commonmark = undefined; }
const corpusPath = path.join(here, '../fixtures/markdown/commonmark-0.31.2.json');
const corpusBytes = readFileSync(corpusPath);
const corpusHash = createHash('sha256').update(corpusBytes).digest('hex');
const corpus = JSON.parse(corpusBytes.toString('utf8'));
const gfmFixture = JSON.parse(readFileSync(path.join(here, '../fixtures/markdown/gfm-matrix.json'), 'utf8'));
const safeFixture = JSON.parse(readFileSync(path.join(here, '../fixtures/markdown/safe-display-vectors.json'), 'utf8'));
const manifest = readFileSync(path.join(staticRoot, 'vendor/MANIFEST.md'), 'utf8');

const browserPayload = Buffer.from(JSON.stringify({ gfmFixture, safeFixture })).toString('base64');
const adapterSourcePath = '/static/js/common/markdown-renderer.js';
const commonmarkSourcePath = '/static/vendor/commonmark/commonmark.esm.mjs';
const purifySourcePath = '/static/vendor/dompurify/purify.es.mjs';

function browserHarness(payload) {
  return `<!doctype html><meta charset="utf-8"><script src="${adapterSourcePath}"></script><script>
const payload = ${JSON.stringify(payload)};
function decodePayload(value) {
  const bytes = Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes));
}
const fixtures = decodePayload(payload);
const allowedTags = new Set(['p','h1','h2','h3','h4','h5','h6','ul','ol','li','blockquote','pre','code','em','strong','del','a','br','hr','table','thead','tbody','tr','th','td','img','input']);
const allowedAttrs = new Set(['href','target','rel','src','alt','type','checked','disabled']);
function safeDisplay(html) {
  const template = document.createElement('template');
  template.innerHTML = String(html);
  for (const element of template.content.querySelectorAll('*')) {
    if (!allowedTags.has(element.localName)) return false;
    for (const attribute of element.attributes) {
      if (!allowedAttrs.has(attribute.name)) return false;
      if (/^on/i.test(attribute.name) || /^data-/i.test(attribute.name) || attribute.name === 'style') return false;
    }
  }
  return !template.content.querySelector('script,style,svg,iframe,object,form,base,template,math');
}
function capture(result) {
  return { html: result.html, status: result.status, reason: result.reason, safe: safeDisplay(result.html) };
}
async function run() {
  const adapter = window.TCRTMarkdown;
  const source = '<scr' + 'ipt>alert(1)</scr' + 'ipt>\\n**unchanged**';
  const pending = capture(adapter.render(source, { surface: 'renderer-test' }));
  const ready = await adapter.ready;
  const output = {
    ready,
    pending,
    metadata: {
      versions: adapter.versions,
      extensions: [...adapter.extensions],
      policy: adapter.policy,
      globals: { marked: typeof window.marked, DOMPurify: typeof window.DOMPurify, commonmark: typeof window.commonmark },
    },
    recovered: capture(adapter.render('**recover me**\\n\\n<a href="/raw">raw</a>', { surface: 'renderer-test' })),
    gfm: { positive: [], negative: [] },
    rawHtml: [],
    links: {},
    images: [],
    lineBreaks: {},
  };
  for (const fixture of fixtures.gfmFixture.positive) {
    output.gfm.positive.push({ name: fixture.name, result: capture(adapter.render(fixture.source, { surface: 'renderer-test' })) });
  }
  for (const fixture of fixtures.gfmFixture.negative) {
    output.gfm.negative.push({ name: fixture.name, result: capture(adapter.render(fixture.source, { surface: 'renderer-test' })) });
  }
  for (const source of fixtures.safeFixture.rawHtml) {
    output.rawHtml.push(capture(adapter.render(source, { surface: 'renderer-test' })));
  }
  for (const [name, source] of Object.entries(fixtures.safeFixture.links)) {
    if (Array.isArray(source)) output.links[name] = source.map((value) => capture(adapter.render(value, { surface: 'renderer-test' })));
    else if (name === 'rejected') output.links[name] = source.map((value) => capture(adapter.render(value, { surface: 'renderer-test' })));
    else output.links[name] = capture(adapter.render(source, { surface: 'renderer-test' }));
  }
  for (const source of fixtures.safeFixture.images) output.images.push(capture(adapter.render(source, { surface: 'renderer-test' })));
  for (const [name, source] of Object.entries(fixtures.safeFixture.lineBreaks)) output.lineBreaks[name] = capture(adapter.render(source, { surface: 'renderer-test' }));
  output.tasks = capture(adapter.render('- [ ] todo\\n- [x] done', { surface: 'renderer-test' }));
  output.heading = capture(adapter.render('# Heading', { surface: 'renderer-test' }));
  const encoded = btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(output))));
  const pre = document.createElement('pre');
  pre.id = 'results';
  pre.textContent = encoded;
  document.body.replaceChildren(pre);
}
run().catch((error) => {
  const pre = document.createElement('pre');
  pre.id = 'results';
  pre.textContent = btoa(JSON.stringify({ error: String(error && error.stack || error) }));
  document.body.replaceChildren(pre);
});
</script>`;
}

function findChromium() {
  const candidates = [];
  for (const name of ['CHROMIUM_BIN', 'PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH']) {
    if (process.env[name]) candidates.push(process.env[name]);
  }
  candidates.push(
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/opt/homebrew/bin/chromium', '/usr/bin/chromium', '/usr/bin/chromium-browser',
  );
  const roots = [
    path.join(os.homedir(), 'Library/Caches/ms-playwright'),
    path.join(os.homedir(), '.cache/ms-playwright'),
  ];
  for (const root of roots) {
    if (!existsSync(root)) continue;
    for (const browser of readdirSync(root)) {
      if (!/^chromium-/.test(browser)) continue;
      const browserRoot = path.join(root, browser);
      if (!existsSync(browserRoot)) continue;
      const walk = (directory, depth) => {
        if (depth > 9) return;
        for (const entry of readdirSync(directory, { withFileTypes: true })) {
          const candidate = path.join(directory, entry.name);
          if (entry.isFile() && /^(?:chrome|Chromium|Google Chrome for Testing)(?:\.exe)?$/.test(entry.name)) candidates.push(candidate);
          else if (entry.isDirectory()) walk(candidate, depth + 1);
        }
      };
      walk(browserRoot, 0);
    }
  }
  return candidates.find((candidate) => existsSync(candidate));
}

function serveFile(response, pathname, failureMode) {
  const mapping = {
    [adapterSourcePath]: path.join(staticRoot, 'js/common/markdown-renderer.js'),
    [commonmarkSourcePath]: path.join(staticRoot, 'vendor/commonmark/commonmark.esm.mjs'),
    [purifySourcePath]: path.join(staticRoot, 'vendor/dompurify/purify.es.mjs'),
  };
  if (failureMode === 'asset' && (pathname === commonmarkSourcePath || pathname === purifySourcePath)) {
    response.writeHead(404); response.end('asset unavailable'); return;
  }
  if (failureMode === 'parser' && pathname === commonmarkSourcePath) {
    response.writeHead(200, { 'Content-Type': 'text/javascript' });
    response.end('export default {};');
    return;
  }
  if (failureMode === 'sanitizer' && pathname === purifySourcePath) {
    response.writeHead(200, { 'Content-Type': 'text/javascript' });
    response.end('export default {};');
    return;
  }
  if (failureMode === 'renderer' && pathname === commonmarkSourcePath) {
    response.writeHead(200, { 'Content-Type': 'text/javascript' });
    response.end('export const Parser = class { parse() { throw new Error("render failure"); } }; export const HtmlRenderer = class {}; export default { Parser, HtmlRenderer };');
    return;
  }
  const file = mapping[pathname];
  if (!file) { response.writeHead(404); response.end('not found'); return; }
  response.writeHead(200, { 'Content-Type': pathname.endsWith('.js') || pathname.endsWith('.mjs') ? 'text/javascript' : 'text/plain' });
  response.end(readFileSync(file));
}

async function freePort() {
  const probe = createTcpServer();
  await new Promise((resolve) => probe.listen(0, '127.0.0.1', resolve));
  const port = probe.address().port;
  await new Promise((resolve) => probe.close(resolve));
  return port;
}

async function evaluateBrowser(port, expression) {
  const response = await fetch(`http://127.0.0.1:${port}/json/list`);
  const targets = await response.json();
  const target = targets.find((entry) => entry.type === 'page' && entry.webSocketDebuggerUrl);
  if (!target) return null;
  return await new Promise((resolve, reject) => {
    const socket = new WebSocket(target.webSocketDebuggerUrl);
    const timer = setTimeout(() => { socket.close(); reject(new Error('CDP evaluation timed out')); }, 5000);
    socket.onopen = () => socket.send(JSON.stringify({
      id: 1, method: 'Runtime.evaluate', params: { expression, returnByValue: true },
    }));
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.id !== 1) return;
      clearTimeout(timer);
      socket.close();
      resolve(message.result && message.result.result ? message.result.result.value : null);
    };
    socket.onerror = () => { clearTimeout(timer); reject(new Error('CDP websocket failed')); };
  });
}

async function runBrowser({ failureMode = null } = {}) {
  const executable = findChromium();
  assert.ok(executable, 'an installed Chromium executable is required for DOMPurify/browser assertions; set CHROMIUM_BIN');
  const server = createServer((request, response) => {
    const requestUrl = new URL(request.url, 'http://127.0.0.1');
    if (requestUrl.pathname === '/harness.html') {
      response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      response.end(browserHarness(browserPayload));
    } else serveFile(response, requestUrl.pathname, failureMode);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  const url = `http://127.0.0.1:${address.port}/harness.html`;
  const debugPort = await freePort();
  const profile = mkdtempSync(path.join(os.tmpdir(), 'tcrt-markdown-browser-'));
  const child = spawn(executable, [
    '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
    '--disable-background-networking', '--disable-sync', '--disable-component-update',
    '--disable-breakpad', '--disable-crash-reporter', '--no-first-run', '--no-default-browser-check',
    `--remote-debugging-port=${debugPort}`, '--remote-allow-origins=*', `--user-data-dir=${profile}`, url,
  ], { stdio: ['ignore', 'ignore', 'pipe'] });
  let stderr = '';
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', (chunk) => { stderr += chunk; });
  let encoded = null;
  const deadline = Date.now() + 30000;
  try {
    while (Date.now() < deadline && !encoded) {
      try {
        encoded = await evaluateBrowser(debugPort, 'document.querySelector("#results")?.textContent || null');
      } catch (_) { /* browser is still starting */ }
      if (!encoded) await new Promise((resolve) => setTimeout(resolve, 100));
    }
    const diagnostics = encoded ? '' : String(await evaluateBrowser(debugPort, 'document.documentElement.outerHTML').catch((error) => error));
    assert.ok(encoded, `browser harness did not produce results: ${stderr}\n${diagnostics.slice(-4000)}`);
  } finally {
    child.kill('SIGKILL');
    server.close();
    try { rmSync(profile, { recursive: true, force: true }); } catch (_) { /* Chrome helpers may still hold cache files. */ }
  }
  const output = JSON.parse(Buffer.from(encoded, 'base64').toString('utf8'));
  assert.equal(output.error, undefined, output.error);
  return output;
}

let browserResultsPromise;
function browserResults() {
  browserResultsPromise ||= runBrowser();
  return browserResultsPromise;
}

const failureResultsPromises = new Map();
function failureResults(failureMode) {
  if (!failureResultsPromises.has(failureMode)) {
    failureResultsPromises.set(failureMode, runBrowser({ failureMode }));
  }
  return failureResultsPromises.get(failureMode);
}

test('CommonMark 0.31.2 corpus harness executes every official example', () => {
  assert.equal(corpus.length, 652, 'fixture must contain the complete official CommonMark 0.31.2 corpus');
  assert.equal(corpusBytes.byteLength, 140848, 'fixture byte count must match the pinned official corpus');
  assert.equal(corpusHash, '7eda833601c864e0f3c36bac8c1a33d16d2071b90ad347a6f2c0e7088792c42c', 'fixture hash must match the pinned official corpus');
  const parser = new commonmark.Parser();
  const renderer = new commonmark.HtmlRenderer({ safe: false, softbreak: '\n' });
  for (const example of corpus) {
    assert.equal(renderer.render(parser.parse(example.markdown)), example.html, `CommonMark example ${example.example} (${example.section}) diverged`);
  }
});
test('pinned parser and sanitizer assets have manifest provenance and hashes', () => {
  const assets = [
    {
      name: 'CommonMark',
      version: '0.31.2',
      path: path.join(staticRoot, 'vendor/commonmark/commonmark.esm.mjs'),
      source: 'https://unpkg.com/commonmark@0.31.2/dist/commonmark.js',
      integrity: 'sha512-2fRLTyb9r/2835k5cwcAwOj0DEc44FARnMp5veGsJ+mEAZdi52sNopLu07ZyElQUz058H43whzlERDIaaSw4rg==',
      license: 'BSD-2-Clause',
    },
    {
      name: 'DOMPurify',
      version: '3.4.12',
      path: path.join(staticRoot, 'vendor/dompurify/purify.es.mjs'),
      source: 'https://cdn.jsdelivr.net/npm/dompurify@3.4.12/dist/purify.es.mjs',
      integrity: 'sha512-zQvGet8Z2sWbQhCmfFz/T5QWH2oBmjnqK3qvOjaqaNLrLEF912WamU+ohnTp0TCep/MFVHpdJuCZEdFOdTnEFg==',
      license: '(MPL-2.0 OR Apache-2.0)',
    },
  ];
  for (const asset of assets) {
    const digest = createHash('sha256').update(readFileSync(asset.path)).digest('hex');
    assert.ok(manifest.includes(`| ${asset.name} | ${asset.version} |`), `${asset.name} row is present`);
    assert.ok(manifest.includes(asset.source), `${asset.name} source is pinned`);
    assert.ok(manifest.includes(`SHA-256 \`${digest}\``), `${asset.name} local hash is recorded`);
    assert.ok(manifest.includes('`' + asset.integrity + '`'), `${asset.name} npm integrity is recorded`);
    assert.ok(manifest.includes(`| ${asset.license} | 2026-08-03 |`), `${asset.name} license and acquisition date are recorded`);
  }
});

test('adapter exposes canonical CommonMark/GFM policy without parser globals', async () => {
  const output = await browserResults();
  assert.equal(output.ready.status, 'ok');
  assert.equal(output.metadata.versions.commonmark, '0.31.2');
  assert.equal(output.metadata.versions.parser, 'commonmark@0.31.2');
  assert.deepEqual(output.metadata.extensions, ['tables', 'task-list-items', 'strikethrough', 'autolink-literals']);
  assert.equal(output.metadata.policy.rawHtmlProvenance, 'ast-node-type');
  assert.equal(output.metadata.globals.marked, 'undefined');
  assert.equal(output.metadata.globals.DOMPurify, 'undefined');
  assert.equal(output.metadata.globals.commonmark, 'undefined');
});

test('pending fallback rerenders unchanged source after readiness', async () => {
  const output = await browserResults();
  assert.equal(output.pending.status, 'fallback');
  assert.equal(output.pending.reason, 'renderer-pending');
  assert.match(output.pending.html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;\n\*\*unchanged\*\*/);
  assert.equal(output.recovered.status, 'ok');
  assert.match(output.recovered.html, /<strong>recover me<\/strong>/);
  assert.match(output.recovered.html, /&lt;a href="\/raw"&gt;raw&lt;\/a&gt;/);
  assert.equal(output.recovered.safe, true);
});

test('GFM matrix supports only the four declared extensions', async () => {
  const output = await browserResults();
  const positives = new Map(output.gfm.positive.map((entry) => [entry.name, entry.result]));
  for (const fixture of gfmFixture.positive) {
    const result = positives.get(fixture.name);
    assert.equal(result.status, 'ok', fixture.name);
    assert.equal(result.safe, true, fixture.name);
    for (const expected of fixture.mustContain || []) assert.match(result.html, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), fixture.name + ': ' + expected);
  }
  const negatives = new Map(output.gfm.negative.map((entry) => [entry.name, entry.result]));
  for (const fixture of gfmFixture.negative) {
    const result = negatives.get(fixture.name);
    assert.equal(result.status, 'ok', fixture.name);
    assert.equal(result.safe, true, fixture.name);
    for (const expected of fixture.mustContain || []) assert.ok(result.html.includes(expected), fixture.name + ': ' + expected);
    for (const forbidden of fixture.mustNotContain || []) assert.equal(result.html.includes(forbidden), false, fixture.name + ': ' + forbidden);
    if (Number.isInteger(fixture.checkboxCount)) {
      assert.equal((result.html.match(/<input\b/g) || []).length, fixture.checkboxCount, fixture.name + ': checkbox count');
    }
  }
});

test('raw HTML is escaped before Safe Display sanitization', async () => {
  const output = await browserResults();
  for (const result of output.rawHtml) {
    assert.equal(result.status, 'ok');
    assert.equal(result.safe, true);
    assert.doesNotMatch(result.html, /<\/?(?:script|style|a|img|input)\b/i);
  }
  assert.match(output.recovered.html, /&lt;a href=/);
});

test('URL normalization and external-link policy are deterministic', async () => {
  const output = await browserResults();
  assert.equal(output.links.allowedRelative.safe, true);
  assert.match(output.links.allowedRelative.html, /href="\/cases\/1"/);
  assert.doesNotMatch(output.links.allowedRelative.html, /target=|rel=/);
  assert.match(output.links.allowedEncodedRelative.html, /href="java%2573cript:alert\(1\)"/);
  assert.doesNotMatch(output.links.allowedEncodedRelative.html, /target=|rel=/);
  assert.match(output.links.allowedExternal.html, /href="https:\/\/example\.com\/path"/);
  assert.match(output.links.allowedExternal.html, /target="_blank"/);
  assert.match(output.links.allowedExternal.html, /rel="noopener noreferrer"/);
  assert.match(output.links.allowedMailto.html, /href="mailto:user@example\.com"/);
  for (const result of output.links.userinfo) {
    assert.equal(result.safe, true);
    assert.doesNotMatch(result.html, /<a\b/i);
  }
  for (const result of output.links.rejected) {
    assert.equal(result.safe, true);
    assert.doesNotMatch(result.html, /<a\b/i);
    assert.doesNotMatch(result.html, /(?:href|src)=["']?(?:javascript|data|blob|file):/i);
  }
  assert.match(output.images[0].html, /<img\b/);
  assert.match(output.images[1].html, /<img\b/);
  for (const result of output.images.slice(2)) assert.doesNotMatch(result.html, /<img\b/);
});

test('soft breaks, hard breaks, task checkboxes, and headings preserve contract', async () => {
  const output = await browserResults();
  assert.doesNotMatch(output.lineBreaks.soft.html, /<br\b/);
  assert.match(output.lineBreaks.soft.html, /one\ntwo/);
  assert.match(output.lineBreaks.hardSpaces.html, /<br\s*\/?>(?:\n|$)/);
  assert.match(output.lineBreaks.hardBackslash.html, /<br\s*\/?>(?:\n|$)/);
  assert.match(output.tasks.html, /<input type="checkbox" disabled(?:="")?>/);
  assert.match(output.tasks.html, /<input type="checkbox" checked(?:="")? disabled(?:="")?>/);
  assert.doesNotMatch(output.tasks.html, /name=|value=|form=|on[a-z-]+=|data-/i);
  assert.equal(output.heading.html, '<h1>Heading</h1>\n');
  assert.equal(output.heading.safe, true);
});

test('asset failure is fail-closed and ready settles', async () => {
  const output = await failureResults('asset');
  assert.equal(output.pending.status, 'fallback');
  assert.equal(output.pending.reason, 'renderer-pending');
  assert.match(output.pending.html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;\n\*\*unchanged\*\*/);
  assert.equal(output.ready.status, 'fallback');
  assert.equal(output.ready.reason, 'asset-unavailable');
  assert.equal(output.recovered.status, 'fallback');
  assert.equal(output.recovered.reason, 'asset-unavailable');
  assert.equal(output.recovered.safe, true);
  assert.equal(output.metadata.globals.commonmark, 'undefined');
});

test('parser and sanitizer initialization failures expose exact fail-closed reasons', async () => {
  for (const [failureMode, reason] of [['parser', 'parser-unavailable'], ['sanitizer', 'sanitizer-unavailable']]) {
    const output = await failureResults(failureMode);
    assert.equal(output.ready.status, 'fallback', failureMode);
    assert.equal(output.ready.reason, reason, failureMode);
    assert.equal(output.recovered.status, 'fallback', failureMode);
    assert.equal(output.recovered.reason, reason, failureMode);
    assert.equal(output.recovered.safe, true, failureMode);
    assert.equal(output.metadata.globals.commonmark, 'undefined', failureMode);
  }
});

test('renderer exceptions return escaped fallback without poisoning readiness', async () => {
  const output = await failureResults('renderer');
  assert.equal(output.ready.status, 'ok');
  assert.equal(output.recovered.status, 'fallback');
  assert.equal(output.recovered.reason, 'renderer-error');
  assert.match(output.recovered.html, /&lt;a href=&quot;\/raw&quot;&gt;raw&lt;\/a&gt;/);
  assert.equal(output.recovered.safe, true);
});
