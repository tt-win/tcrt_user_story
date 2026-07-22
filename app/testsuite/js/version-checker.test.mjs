import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(path.join(here, '../../static/js/version-checker.js'), 'utf8');
const storage = new Map([['client_server_timestamp', '100']]);
const context = {
  console,
  setInterval: () => 1,
  clearInterval: () => {},
  setTimeout: () => {},
  localStorage: {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key),
    get length() { return storage.size; },
    key: (index) => [...storage.keys()][index] ?? null,
  },
  document: { addEventListener: () => {}, getElementById: () => null, querySelector: () => null },
  window: { addEventListener: () => {}, __TCRT_SERVER_VERSION__: '100' },
};
vm.createContext(context);
vm.runInContext(source, context);

const checker = new context.window.VersionChecker();
let shown = null;
let reloads = 0;
checker.showUpdateButton = (version) => { shown = version; };
checker.forceReload = () => { reloads += 1; };
checker.syncServerVersion(200, 'test');

assert.equal(shown, 200, 'new version should be offered to the user');
assert.equal(reloads, 0, 'background version detection must not reload the page');
assert.equal(storage.get('client_server_timestamp'), '100', 'version is acknowledged only after explicit update');
console.log('version-checker tests passed');
