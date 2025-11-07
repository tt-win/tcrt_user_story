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

      const response = await fetch(
        `/api/teams/${teamId}/test-case-sets`,
        {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('token')}`
          }
        }
      );

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
      alert('請先選擇要複製的測試案例');
      return;
    }

    const sets = this.allSets.filter(s => s.id !== this.currentSetId);

    if (sets.length === 0) {
      alert('沒有其他可用的集合');
      return;
    }

    const modalHtml = `
      <div class="modal fade" id="crossSetCopyModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">複製到其他集合</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
              <form id="crossSetCopyForm">
                <div class="form-group mb-3">
                  <label for="targetSet">目標集合 <span class="text-danger">*</span></label>
                  <select id="targetSet" class="form-control" onchange="testCaseCrossSetOps.onTargetSetChanged()">
                    <option value="">選擇集合...</option>
                    ${sets.map(s => `<option value="${s.id}">${this.escapeHtml(s.name)}</option>`).join('')}
                  </select>
                </div>

                <div class="form-group mb-3">
                  <label for="targetSection">目標區段 <span class="text-danger">*</span></label>
                  <select id="targetSection" class="form-control" disabled>
                    <option value="">先選擇集合...</option>
                  </select>
                </div>

                <div class="alert alert-info" role="alert">
                  <i class="fas fa-info-circle"></i>
                  將複製 <strong>${testCaseIds.length}</strong> 個測試案例
                </div>
              </form>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
              <button type="button" class="btn btn-primary"
                      onclick="testCaseCrossSetOps.confirmCrossSetCopy(${JSON.stringify(testCaseIds)})">
                複製
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
      alert('請先選擇要搬移的測試案例');
      return;
    }

    const sets = this.allSets.filter(s => s.id !== this.currentSetId);

    if (sets.length === 0) {
      alert('沒有其他可用的集合');
      return;
    }

    const modalHtml = `
      <div class="modal fade" id="crossSetMoveModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">搬移到其他集合</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
              <form id="crossSetMoveForm">
                <div class="alert alert-warning" role="alert">
                  <i class="fas fa-exclamation-triangle"></i>
                  搬移是永久操作，測試案例將從當前集合移除
                </div>

                <div class="form-group mb-3">
                  <label for="targetSet">目標集合 <span class="text-danger">*</span></label>
                  <select id="targetSet" class="form-control" onchange="testCaseCrossSetOps.onTargetSetChanged()">
                    <option value="">選擇集合...</option>
                    ${sets.map(s => `<option value="${s.id}">${this.escapeHtml(s.name)}</option>`).join('')}
                  </select>
                </div>

                <div class="form-group mb-3">
                  <label for="targetSection">目標區段 <span class="text-danger">*</span></label>
                  <select id="targetSection" class="form-control" disabled>
                    <option value="">先選擇集合...</option>
                  </select>
                </div>

                <div class="alert alert-info" role="alert">
                  <i class="fas fa-info-circle"></i>
                  將搬移 <strong>${testCaseIds.length}</strong> 個測試案例
                </div>
              </form>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
              <button type="button" class="btn btn-danger"
                      onclick="testCaseCrossSetOps.confirmCrossSetMove(${JSON.stringify(testCaseIds)})">
                搬移
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
      sectionSelect.innerHTML = '<option value="">先選擇集合...</option>';
      return;
    }

    try {
      // 載入目標 Set 的 Sections
      const response = await fetch(
        `/api/test-case-sets/${setId}/sections`,
        {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('token')}`
          }
        }
      );

      if (!response.ok) {
        throw new Error('Failed to load sections');
      }

      const sections = await response.json();

      // 填充 Section 選擇器
      sectionSelect.disabled = false;
      sectionSelect.innerHTML = `
        <option value="">選擇區段...</option>
        ${this.getSectionOptions(sections)}
      `;

      this.targetSetId = setId;

    } catch (error) {
      console.error('Error loading sections:', error);
      alert('載入區段失敗');
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
      alert('請選擇目標集合');
      return;
    }

    if (!targetSectionId) {
      alert('請選擇目標區段');
      return;
    }

    try {
      const response = await fetch(`/api/testcases/copy-across-sets`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
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
        throw new Error(error.detail || 'Failed to copy test cases');
      }

      bootstrap.Modal.getInstance(document.getElementById('crossSetCopyModal')).hide();
      alert(`成功複製 ${testCaseIds.length} 個測試案例`);

      // 刷新表格
      if (typeof loadTestCases === 'function') {
        await loadTestCases();
      }

    } catch (error) {
      console.error('Error copying test cases:', error);
      alert('複製失敗: ' + error.message);
    }
  }

  /**
   * 確認跨 Set 搬移
   */
  async confirmCrossSetMove(testCaseIds) {
    const targetSetId = document.getElementById('targetSet').value;
    const targetSectionId = document.getElementById('targetSection').value;

    if (!targetSetId) {
      alert('請選擇目標集合');
      return;
    }

    if (!targetSectionId) {
      alert('請選擇目標區段');
      return;
    }

    if (!confirm(`確定要搬移 ${testCaseIds.length} 個測試案例嗎？此操作無法撤銷。`)) {
      return;
    }

    try {
      const response = await fetch(`/api/testcases/move-across-sets`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
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
        throw new Error(error.detail || 'Failed to move test cases');
      }

      bootstrap.Modal.getInstance(document.getElementById('crossSetMoveModal')).hide();
      alert(`成功搬移 ${testCaseIds.length} 個測試案例`);

      // 刷新表格
      if (typeof loadTestCases === 'function') {
        await loadTestCases();
      }

    } catch (error) {
      console.error('Error moving test cases:', error);
      alert('搬移失敗: ' + error.message);
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
