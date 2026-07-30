/**
 * Header toolbar overflow contracts at 1440 / 768 / 375 without a browser.
 * Run: node --test app/testsuite/js/header-toolbar-overflow.test.mjs
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(path.join(here, '../../static/js/header-toolbar.js'), 'utf8');

function makeEl(tag, attrs = {}) {
  const children = [];
  const classSet = new Set(String(attrs.className || attrs.class || '').split(/\s+/).filter(Boolean));
  const el = {
    tagName: tag.toUpperCase(),
    children,
    style: {},
    classList: {
      add: (...xs) => xs.forEach((x) => classSet.add(x)),
      remove: (...xs) => xs.forEach((x) => classSet.delete(x)),
      contains: (x) => classSet.has(x),
      toggle: (x, force) => {
        if (force === true) classSet.add(x);
        else if (force === false) classSet.delete(x);
        else if (classSet.has(x)) classSet.delete(x);
        else classSet.add(x);
        return classSet.has(x);
      },
    },
    get className() {
      return [...classSet].join(' ');
    },
    set className(v) {
      classSet.clear();
      String(v || '')
        .split(/\s+/)
        .filter(Boolean)
        .forEach((x) => classSet.add(x));
    },
    get firstChild() {
      return children[0] || null;
    },
    get firstElementChild() {
      return children[0] || null;
    },
    get lastElementChild() {
      return children[children.length - 1] || null;
    },
    appendChild(child) {
      if (child.parentNode) child.parentNode.removeChild(child);
      children.push(child);
      child.parentNode = el;
      return child;
    },
    insertBefore(child, ref) {
      if (child.parentNode) child.parentNode.removeChild(child);
      const idx = ref ? children.indexOf(ref) : -1;
      if (idx === -1) children.push(child);
      else children.splice(idx, 0, child);
      child.parentNode = el;
      return child;
    },
    removeChild(child) {
      const idx = children.indexOf(child);
      if (idx !== -1) children.splice(idx, 1);
      child.parentNode = null;
      return child;
    },
    contains(node) {
      if (node === el) return true;
      return children.some((c) => c === node || (c.contains && c.contains(node)));
    },
    querySelector(sel) {
      return queryAll(el, sel)[0] || null;
    },
    querySelectorAll(sel) {
      return queryAll(el, sel);
    },
    matches(sel) {
      return matches(el, sel);
    },
    getAttribute(name) {
      return el._attrs[name] ?? null;
    },
    setAttribute(name, value) {
      el._attrs[name] = String(value);
    },
    _attrs: { ...attrs },
    parentNode: null,
    textContent: attrs.textContent || '',
  };
  if (attrs.id) el.id = attrs.id;
  if (attrs.href) el._attrs.href = attrs.href;
  return el;
}

function matches(el, sel) {
  if (sel.startsWith('#')) return el.id === sel.slice(1);
  if (sel.startsWith('.')) return el.classList.contains(sel.slice(1));
  if (sel.includes('[')) {
    const m = sel.match(/^(\w+)?\[([^=\]]+)(?:=\"([^\"]*)\")?\]/);
    if (!m) return false;
    if (m[1] && el.tagName !== m[1].toUpperCase()) return false;
    const val = el.getAttribute(m[2]);
    if (m[3] !== undefined) return val === m[3];
    return val != null;
  }
  return el.tagName === sel.toUpperCase();
}

function queryAll(root, sel) {
  const parts = String(sel)
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  if (parts.length > 1) {
    const seen = new Set();
    const out = [];
    for (const part of parts) {
      for (const node of queryAll(root, part)) {
        if (!seen.has(node)) {
          seen.add(node);
          out.push(node);
        }
      }
    }
    return out;
  }
  const out = [];
  const walk = (node) => {
    if (!node || !node.children) return;
    for (const child of node.children) {
      if (matches(child, sel) && !out.includes(child)) out.push(child);
      walk(child);
    }
  };
  walk(root);
  return out;
}

function buildToolbar(viewportWidth) {
  const ids = {};
  const byId = (id) => ids[id] || null;

  const items = makeEl('div', { id: 'headerToolbarItems', className: 'header-toolbar-items' });
  ids.headerToolbarItems = items;
  const menu = makeEl('ul', { id: 'headerToolbarOverflowMenu' });
  ids.headerToolbarOverflowMenu = menu;
  const overflow = makeEl('div', { id: 'headerToolbarOverflow', className: 'dropdown header-toolbar-overflow d-none' });
  ids.headerToolbarOverflow = overflow;
  overflow.appendChild(makeEl('button', { id: 'headerToolbarOverflowBtn' }));
  overflow.appendChild(menu);

  const scroll = makeEl('div', { id: 'headerToolbarScroll', className: 'header-toolbar-scroll' });
  ids.headerToolbarScroll = scroll;
  scroll.appendChild(items);
  scroll.appendChild(overflow);
  Object.defineProperty(scroll, 'clientWidth', {
    configurable: true,
    get: () => Math.max(60, viewportWidth - 220),
  });
  Object.defineProperty(scroll, 'scrollWidth', {
    configurable: true,
    get: () => items.children.length * 96 + 48,
  });

  const pin = makeEl('div', { id: 'headerToolbarPin', className: 'header-toolbar-pin' });
  ids.headerToolbarPin = pin;
  const user = makeEl('div', { className: 'header-toolbar-user' });
  user.appendChild(makeEl('button', { id: 'userDropdown', textContent: 'User' }));
  const logout = makeEl('button', { id: 'logoutBtn', textContent: 'Logout' });
  ids.logoutBtn = logout;
  user.appendChild(logout);
  pin.appendChild(user);

  const admin = makeEl('div', { id: 'adminDropdownGroup', className: 'btn-group' });
  ids.adminDropdownGroup = admin;
  admin.appendChild(makeEl('button', { textContent: 'Admin' }));
  items.appendChild(admin);
  for (const label of ['A', 'B', 'C', 'D', 'E', 'F']) {
    items.appendChild(makeEl('button', { className: 'btn', textContent: label }));
  }
  const homeIcon = makeEl('i', { className: 'fas fa-home' });
  const homeSpan = makeEl('span');
  homeSpan.setAttribute('data-i18n', 'navigation.backToHome');
  homeSpan.textContent = '回到首頁';
  const home = makeEl('a', { href: '/', className: 'btn' });
  home.appendChild(homeIcon);
  home.appendChild(homeSpan);
  // HTMLAnchorElement check
  Object.setPrototypeOf(home, { constructor: { name: 'HTMLAnchorElement' } });
  // Make instanceof HTMLAnchorElement work via Symbol or custom
  items.appendChild(home);

  const toolbar = makeEl('div', { className: 'header-toolbar' });
  toolbar.appendChild(scroll);
  toolbar.appendChild(pin);

  return { items, menu, overflow, scroll, pin, home, logout, byId, ids };
}

function runAtWidth(viewportWidth) {
  const dom = buildToolbar(viewportWidth);

  class HTMLAnchorElement {}

  const document = {
    readyState: 'complete',
    getElementById: (id) => dom.ids[id] || null,
    createElement: (tag) => makeEl(tag),
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener() {},
  };
  const windowObj = {
    document,
    HTMLAnchorElement,
    ResizeObserver: class {
      observe() {}
    },
    MutationObserver: class {
      observe() {}
      disconnect() {}
    },
    requestAnimationFrame: (fn) => {
      fn();
      return 1;
    },
    cancelAnimationFrame() {},
    addEventListener() {},
    TcrtHeaderToolbar: undefined,
  };
  windowObj.window = windowObj;

  for (const child of [...dom.items.children]) {
    if (child.tagName === 'A') Object.setPrototypeOf(child, HTMLAnchorElement.prototype);
  }

  const context = vm.createContext({
    window: windowObj,
    document,
    HTMLAnchorElement,
    ResizeObserver: windowObj.ResizeObserver,
    MutationObserver: windowObj.MutationObserver,
    requestAnimationFrame: windowObj.requestAnimationFrame,
    cancelAnimationFrame: windowObj.cancelAnimationFrame,
    console,
  });
  vm.runInContext(
    `var window = this.window; var document = this.document; var HTMLAnchorElement = this.HTMLAnchorElement;` +
      `var ResizeObserver = this.ResizeObserver; var MutationObserver = this.MutationObserver;` +
      `var requestAnimationFrame = this.requestAnimationFrame; var cancelAnimationFrame = this.cancelAnimationFrame;\n` +
      source,
    context,
  );

  assert.ok(windowObj.TcrtHeaderToolbar, 'exposes TcrtHeaderToolbar');
  windowObj.TcrtHeaderToolbar.reflow();
  return dom;
}

test('toolbar pins home+logout and never overflows them at 1440/768/375', () => {
  for (const width of [1440, 768, 375]) {
    const dom = runAtWidth(width);
    assert.ok(dom.pin.contains(dom.logout), `${width}: logout in pin`);
    assert.ok(
      [...dom.pin.children].some((c) => c.classList.contains('header-toolbar-home') || c.tagName === 'A'),
      `${width}: home in pin`,
    );
    assert.equal(dom.menu.querySelector('#logoutBtn'), null, `${width}: logout not in overflow`);
    assert.equal(
      [...dom.menu.children].some((li) => li.querySelector && li.querySelector('a[href="/"]')),
      false,
      `${width}: home not in overflow`,
    );
  }
});

test('narrow viewports fold surplus controls into overflow', () => {
  const narrow = runAtWidth(375);
  assert.equal(narrow.overflow.classList.contains('d-none'), false, '375: overflow visible');
  assert.ok(narrow.menu.children.length > 0, '375: overflow has items');

  const wide = runAtWidth(1440);
  // Wide: scrollWidth (7*96+48=720) < clientWidth (1440-220=1220) → no overflow
  assert.equal(wide.overflow.classList.contains('d-none'), true, '1440: overflow hidden');
  assert.equal(wide.menu.children.length, 0, '1440: overflow empty');
});
