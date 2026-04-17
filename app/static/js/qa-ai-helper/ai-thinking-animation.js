/**
 * AI Thinking Animation Module
 *
 * Shows a subtle overlay with a pulsing indicator while the backend is
 * processing a long-running AI generation call (seed generation, testcase
 * generation, etc.).
 *
 * Public API (attached to window.AiThinkingAnimation):
 *   show(message)   — mount the overlay with the given message
 *   hide()          — unmount the overlay
 *   wrap(asyncFn, message) — helper that shows before and hides after asyncFn
 */
(function () {
  'use strict';

  let _overlay = null;

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function buildOverlay(message) {
    const overlay = document.createElement('div');
    overlay.className = 'ai-thinking-overlay';
    overlay.innerHTML = `
      <div class="ai-thinking-container">
        <div class="ai-thinking-indicator">
          <span class="ai-thinking-dot"></span>
          <span class="ai-thinking-dot"></span>
          <span class="ai-thinking-dot"></span>
        </div>
        <div class="ai-thinking-message">${escapeHtml(message || 'AI 思考中...')}</div>
      </div>`;
    return overlay;
  }

  function show(message) {
    hide();
    _overlay = buildOverlay(message);
    document.body.appendChild(_overlay);
    requestAnimationFrame(() => _overlay.classList.add('is-visible'));
  }

  function hide() {
    if (!_overlay) return;
    _overlay.classList.remove('is-visible');
    const el = _overlay;
    _overlay = null;
    setTimeout(() => { if (el.parentNode) el.remove(); }, 300);
  }

  async function wrap(asyncFn, message) {
    show(message);
    try {
      return await asyncFn();
    } finally {
      hide();
    }
  }

  window.AiThinkingAnimation = { show, hide, wrap };
})();
