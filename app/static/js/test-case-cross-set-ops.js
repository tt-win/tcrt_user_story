/**
 * 跨 Test Case Set 複製/搬移功能模組
 *
 * 功能：
 * - 跨 Set 複製 Test Cases
 * - 跨 Set 搬移 Test Cases
 * - 選擇目標 Set 和 Section
 */

class TestCaseCrossSetOps {
  constructor() {
    this.currentSetId = null;
    this.allSets = [];
    this.targetSetId = null;
    this.targetSectionId = null;
    this.init();
  }

  authFetch(url, options = {}) {
    if (!window.AuthClient || typeof window.AuthClient.fetch !== 'function') {
      throw new Error(window.i18n.t('testCaseSet.crossSet.authUnavailable'));
    }
    return window.AuthClient.fetch(url, options);
  }

  init() {
    // 監聽 Set 載入
    window.addEventListener('testCaseSetLoaded', (e) => {
      this.currentSetId = e.detail.setId;
      this.loadAllSets();
    });
  }

  /**
   * 載入所有 Test Case Sets
   */
  async loadAllSets() {
    try {
      // 從全域物件或 sessionStorage 中讀取 teamId
      const teamId = testCaseSetIntegration?.currentTeamId ||
                     localStorage.getItem('currentTeamId');

      if (!teamId) return;

      const response = await this.authFetch(`/api/teams/${teamId}/test-case-sets`);

      if (response.ok) {
        this.allSets = await response.json();
      }

    } catch (error) {
      console.error('Error loading sets:', error);
    }
  }

  /**
   * 顯示跨 Set 複製 Modal
   */
  showCrossSetCopyModal(testCaseIds) {
    if (!testCaseIds || testCaseIds.length === 0) {
      alert(window.i18n.t('testCaseSet.selectAtLeastOne'));
      return;
    }

    const sets = this.allSets.filter(s => s.id !== this.currentSetId);

    if (sets.length === 0) {
      alert(window.i18n.t('testCaseSet.crossSet.noOtherSets'));
      return;
    }

    const modalHtml = `
      <div class="modal fade" id="crossSetCopyModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">${this.escapeHtml(window.i18n.t('testCaseSet.crossSet.copyTitle'))}</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
              <form id="crossSetCopyForm">
                <div class="form-group mb-3">
                  <label for="targetSet">${this.escapeHtml(window.i18n.t('testCaseSet.crossSet.targetSet'))} <span class="text-danger">*</span></label>
                  <select id="targetSet" class="form-control" onchange="testCaseCrossSetOps.onTargetSetChanged()">
                    <option value="">${this.escapeHtml(window.i18n.t('testCaseSet.crossSet.selectSet'))}</option>
                    ${sets.map(s => `<option value="${s.id}">${this.escapeHtml(s.name)}</option>`).join('')}
                  </select>
                </div>

                <div class="form-group mb-3">
                  <label for="targetSection">${this.escapeHtml(window.i18n.t('section.crossSection.targetSection'))} <span class="text-danger">*</span></label>
                  <select id="targetSection" class="form-control" disabled>
                    <option value="">${this.escapeHtml(window.i18n.t('testCaseSet.crossSet.selectSetFirst'))}</option>
                  </select>
                </div>

                <div class="alert alert-info" role="alert">
                  <i class="fas fa-info-circle"></i>
                  ${this.escapeHtml(window.i18n.t('testCaseSet.crossSet.copyCount', { count: testCaseIds.length }))}
                </div>
              </form>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">${this.escapeHtml(window.i18n.t('common.cancel'))}</button>
              <button type="button" class="btn btn-primary"
                      onclick="testCaseCrossSetOps.confirmCrossSetCopy(${JSON.stringify(testCaseIds)})">
                ${this.escapeHtml(window.i18n.t('common.copy'))}
              </button>
            </div>
          </div>
        </div>
      </div>
    `;

    // 移除舊 modal
    document.getElementById('crossSetCopyModal')?.remove();

    // 添加新 modal
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    const modal = new bootstrap.Modal(document.getElementById('crossSetCopyModal'));
    modal.show();
  }

  /**
   * 顯示跨 Set 搬移 Modal
   */
  showCrossSetMoveModal(testCaseIds) {
    if (!testCaseIds || testCaseIds.length === 0) {
      alert(window.i18n.t('testCaseSet.selectAtLeastOne'));
      return;
    }

    const sets = this.allSets.filter(s => s.id !== this.currentSetId);

    if (sets.length === 0) {
      alert(window.i18n.t('testCaseSet.crossSet.noOtherSets'));
      return;
    }

    const modalHtml = `
      <div class="modal fade" id="crossSetMoveModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">${this.escapeHtml(window.i18n.t('testCaseSet.crossSet.moveTitle'))}</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
              <form id="crossSetMoveForm">
                <div class="alert alert-warning" role="alert">
                  <i class="fas fa-exclamation-triangle"></i>
                  ${this.escapeHtml(window.i18n.t('testCaseSet.crossSet.moveWarning'))}
                </div>

                <div class="form-group mb-3">
                  <label for="targetSet">${this.escapeHtml(window.i18n.t('testCaseSet.crossSet.targetSet'))} <span class="text-danger">*</span></label>
                  <select id="targetSet" class="form-control" onchange="testCaseCrossSetOps.onTargetSetChanged()">
                    <option value="">${this.escapeHtml(window.i18n.t('testCaseSet.crossSet.selectSet'))}</option>
                    ${sets.map(s => `<option value="${s.id}">${this.escapeHtml(s.name)}</option>`).join('')}
                  </select>
                </div>

                <div class="form-group mb-3">
                  <label for="targetSection">${this.escapeHtml(window.i18n.t('section.crossSection.targetSection'))} <span class="text-danger">*</span></label>
                  <select id="targetSection" class="form-control" disabled>
                    <option value="">${this.escapeHtml(window.i18n.t('testCaseSet.crossSet.selectSetFirst'))}</option>
                  </select>
                </div>

                <div class="alert alert-info" role="alert">
                  <i class="fas fa-info-circle"></i>
                  ${this.escapeHtml(window.i18n.t('testCaseSet.crossSet.moveCount', { count: testCaseIds.length }))}
                </div>
              </form>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">${this.escapeHtml(window.i18n.t('common.cancel'))}</button>
              <button type="button" class="btn btn-danger"
                      onclick="testCaseCrossSetOps.confirmCrossSetMove(${JSON.stringify(testCaseIds)})">
                ${this.escapeHtml(window.i18n.t('testCaseSet.crossSet.move'))}
              </button>
            </div>
          </div>
        </div>
      </div>
    `;

    // 移除舊 modal
    document.getElementById('crossSetMoveModal')?.remove();

    // 添加新 modal
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    const modal = new bootstrap.Modal(document.getElementById('crossSetMoveModal'));
    modal.show();
  }

  /**
   * 目標 Set 變更時的處理
   */
  async onTargetSetChanged() {
    const setId = document.getElementById('targetSet').value;
    const sectionSelect = document.getElementById('targetSection');

    if (!setId) {
      sectionSelect.disabled = true;
      sectionSelect.innerHTML = `<option value="">${this.escapeHtml(window.i18n.t('testCaseSet.crossSet.selectSetFirst'))}</option>`;
      return;
    }

    try {
      // 載入目標 Set 的 Sections
      const response = await this.authFetch(`/api/test-case-sets/${setId}/sections`);

      if (!response.ok) {
        throw new Error(window.i18n.t('section.crossSection.loadFailed'));
      }

      const sections = await response.json();

      // 填充 Section 選擇器
      sectionSelect.disabled = false;
      sectionSelect.innerHTML = `
        <option value="">${this.escapeHtml(window.i18n.t('testCase.selectSection'))}</option>
        ${this.getSectionOptions(sections)}
      `;

      this.targetSetId = setId;

    } catch (error) {
      console.error('Error loading sections:', error);
      alert(window.i18n.t('section.crossSection.loadFailed'));
    }
  }

  /**
   * 取得 Section 選項列表
   */
  getSectionOptions(sections) {
    const options = [];

    const flattenSections = (sections, prefix = '') => {
      sections.forEach(section => {
        options.push(
          `<option value="${section.id}">${prefix}${this.escapeHtml(section.name)}</option>`
        );
        if (section.children && section.children.length > 0) {
          flattenSections(section.children, prefix + '  ');
        }
      });
    };

    flattenSections(sections);
    return options.join('');
  }

  /**
   * 確認跨 Set 複製
   */
  async confirmCrossSetCopy(testCaseIds) {
    const targetSetId = document.getElementById('targetSet').value;
    const targetSectionId = document.getElementById('targetSection').value;

    if (!targetSetId) {
      alert(window.i18n.t('testCaseSet.crossSet.selectTargetSet'));
      return;
    }

    if (!targetSectionId) {
      alert(window.i18n.t('section.crossSection.selectTargetSection'));
      return;
    }

    try {
      const response = await this.authFetch(`/api/testcases/copy-across-sets`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          test_case_ids: testCaseIds.map(id => (typeof id === 'string' ? id : parseInt(id))),
          target_test_case_set_id: parseInt(targetSetId),
          target_section_id: parseInt(targetSectionId),
          copy_mode: 'copy'
        })
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || window.i18n.t('testCaseSet.crossSet.copyRequestFailed'));
      }

      bootstrap.Modal.getInstance(document.getElementById('crossSetCopyModal')).hide();
      alert(window.i18n.t('testCaseSet.crossSet.copySuccess', { count: testCaseIds.length }));

      // 刷新表格
      if (typeof loadTestCases === 'function') {
        await loadTestCases();
      }

    } catch (error) {
      console.error('Error copying test cases:', error);
      alert(window.i18n.t('testCaseSet.crossSet.copyFailed', { reason: error.message }));
    }
  }

  /**
   * 確認跨 Set 搬移
   */
  async confirmCrossSetMove(testCaseIds) {
    const targetSetId = document.getElementById('targetSet').value;
    const targetSectionId = document.getElementById('targetSection').value;

    if (!targetSetId) {
      alert(window.i18n.t('testCaseSet.crossSet.selectTargetSet'));
      return;
    }

    if (!targetSectionId) {
      alert(window.i18n.t('section.crossSection.selectTargetSection'));
      return;
    }

    if (!confirm(window.i18n.t('testCaseSet.crossSet.moveConfirm', { count: testCaseIds.length }))) {
      return;
    }

    try {
      const response = await this.authFetch(`/api/testcases/move-across-sets`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          test_case_ids: testCaseIds.map(id => (typeof id === 'string' ? id : parseInt(id))),
          target_test_case_set_id: parseInt(targetSetId),
          target_section_id: parseInt(targetSectionId),
          copy_mode: 'move'
        })
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || window.i18n.t('testCaseSet.crossSet.moveRequestFailed'));
      }

      bootstrap.Modal.getInstance(document.getElementById('crossSetMoveModal')).hide();
      alert(window.i18n.t('testCaseSet.crossSet.moveSuccess', { count: testCaseIds.length }));

      // 刷新表格
      if (typeof loadTestCases === 'function') {
        await loadTestCases();
      }

    } catch (error) {
      console.error('Error moving test cases:', error);
      alert(window.i18n.t('testCaseSet.crossSet.moveFailed', { reason: error.message }));
    }
  }

  /**
   * HTML 轉義
   */
  escapeHtml(text) {
    const map = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
  }
}

// 建立全域實例
const testCaseCrossSetOps = new TestCaseCrossSetOps();

// 在 DOM 準備好後初始化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    testCaseCrossSetOps.init();
  });
}
