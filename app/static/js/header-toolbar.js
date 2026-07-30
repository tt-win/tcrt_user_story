/**
 * Header toolbar overflow (ResizeObserver) + chrome dropdown escape hatch.
 * Pins home/back into the right pin zone with the user menu; folds surplus
 * controls into an overflow dropdown while keeping a horizontal scroll fallback.
 *
 * All chrome dropdown toggles use Popper strategy "fixed" so menus are not
 * clipped by header height, title truncation, or toolbar overflow-x scrollports.
 */
(function () {
  'use strict';

  var FIXED_POPPER = '{"strategy":"fixed"}';

  function ensureFixedPopper(root) {
    if (!root || !root.querySelectorAll) return;
    var toggles = root.querySelectorAll('[data-bs-toggle="dropdown"]');
    for (var i = 0; i < toggles.length; i++) {
      var el = toggles[i];
      var current = el.getAttribute('data-bs-popper-config') || '';
      if (current.indexOf('fixed') !== -1) continue;
      el.setAttribute('data-bs-popper-config', FIXED_POPPER);
    }
  }

  function ensureChromeDropdownsEscape() {
    ensureFixedPopper(document.querySelector('.app-header'));
    ensureFixedPopper(document.querySelector('.app-footer'));
  }

  function isHomeLink(el) {
    if (!(el instanceof HTMLAnchorElement)) return false;
    var href = el.getAttribute('href') || '';
    if (href !== '/') return false;
    if (el.querySelector('.fa-home, [data-i18n="navigation.backToHome"]')) return true;
    if (el.getAttribute('data-i18n') === 'navigation.backToHome') return true;
    var text = (el.textContent || '').replace(/\s+/g, ' ').trim();
    return text.indexOf('回到首頁') !== -1 || text.indexOf('Back to Home') !== -1;
  }

  function findHomeControls(items) {
    var found = [];
    Array.prototype.forEach.call(items.children, function (child) {
      if (isHomeLink(child)) {
        found.push(child);
        return;
      }
      var link = child.querySelector && child.querySelector('a[href="/"]');
      if (link && isHomeLink(link) && child.children.length === 1) {
        found.push(child);
      }
    });
    return found;
  }

  function pinHomeEntries(items, pin) {
    if (!items || !pin) return;
    var user = pin.querySelector('.header-toolbar-user');
    findHomeControls(items).forEach(function (el) {
      el.classList.add('header-toolbar-home');
      if (user) {
        pin.insertBefore(el, user);
      } else {
        pin.appendChild(el);
      }
    });
  }

  function restoreOverflow(items, menu, overflow) {
    if (!menu || !items) return;
    while (menu.firstChild) {
      var li = menu.firstChild;
      var original = li.__toolbarItem || li.firstElementChild;
      if (original) {
        items.appendChild(original);
      }
      menu.removeChild(li);
    }
    if (overflow) overflow.classList.add('d-none');
  }

  function moveLastToOverflow(items, menu, overflow) {
    if (!items || !items.lastElementChild || !menu) return false;
    var last = items.lastElementChild;
    var li = document.createElement('li');
    li.className = 'header-toolbar-overflow-item mb-1';
    li.__toolbarItem = last;
    li.appendChild(last);
    menu.insertBefore(li, menu.firstChild);
    if (overflow) overflow.classList.remove('d-none');
    ensureFixedPopper(li);
    return true;
  }

  function fits(scroll) {
    if (!scroll) return true;
    return scroll.scrollWidth <= scroll.clientWidth + 1;
  }

  function reflow(ctx) {
    if (ctx.busy) return;
    ctx.busy = true;
    try {
      restoreOverflow(ctx.items, ctx.menu, ctx.overflow);
      pinHomeEntries(ctx.items, ctx.pin);
      ensureChromeDropdownsEscape();

      var guard = 0;
      while (!fits(ctx.scroll) && ctx.items.children.length > 0 && guard < 40) {
        if (!moveLastToOverflow(ctx.items, ctx.menu, ctx.overflow)) break;
        guard += 1;
      }
    } finally {
      ctx.busy = false;
    }
  }

  function initToolbar() {
    var scroll = document.getElementById('headerToolbarScroll');
    var items = document.getElementById('headerToolbarItems');
    var overflow = document.getElementById('headerToolbarOverflow');
    var menu = document.getElementById('headerToolbarOverflowMenu');
    var pin = document.getElementById('headerToolbarPin');
    if (!scroll || !items || !pin) return;

    var ctx = {
      scroll: scroll,
      items: items,
      overflow: overflow,
      menu: menu,
      pin: pin,
      busy: false,
    };

    pinHomeEntries(items, pin);
    reflow(ctx);

    var scheduled = null;
    function schedule() {
      if (scheduled) cancelAnimationFrame(scheduled);
      scheduled = requestAnimationFrame(function () {
        scheduled = null;
        reflow(ctx);
      });
    }

    if (typeof ResizeObserver !== 'undefined') {
      var ro = new ResizeObserver(schedule);
      ro.observe(scroll);
      if (scroll.parentElement) ro.observe(scroll.parentElement);
    } else {
      window.addEventListener('resize', schedule);
    }

    if (typeof MutationObserver !== 'undefined') {
      var mo = new MutationObserver(schedule);
      mo.observe(items, { childList: true });
      var admin = document.getElementById('adminDropdownGroup');
      if (admin) {
        mo.observe(admin, { attributes: true, attributeFilter: ['class'] });
      }
    }

    window.TcrtHeaderToolbar = {
      reflow: function () {
        reflow(ctx);
      },
      ensureFixedPopper: ensureChromeDropdownsEscape,
    };
  }

  function init() {
    ensureChromeDropdownsEscape();
    initToolbar();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
