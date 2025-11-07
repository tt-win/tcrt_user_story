/**
 * Test Case 與 Section 整合模組
 *
 * 功能：
 * - 按 Section 分組顯示 Test Cases
 * - Section 標題列
 * - Test Case Modal 中添加 Section 選擇器
 * - 支援跨 Section 複製/搬移
 */

class TestCaseSectionIntegration {
  constructor() {
    this.setId = null;
    this.sections = [];
    this.selectedSectionId = null;
    this.init();
  }

  init() {
    // 監聽 Set 載入事件
    window.addEventListener('testCaseSetLoaded', (e) => {
      this.setId = e.detail.setId;
      this.sections = e.detail.sections;
      this.setupSectionSelector();
      this.setupTestCaseListIntegration();
    });

    // 監聽 Section 選擇事件
    window.addEventListener('sectionSelected', (e) => {
      this.selectedSectionId = e.detail.sectionId;
      this.filterTestCasesBySection();
    });
  }

  /**
   * 設置 Test Case Modal 中的 Section 選擇器
   */
  setupSectionSelector() {
    // 檢查 Test Case Modal 是否存在
    const modal = document.getElementById('testCaseModal');
    if (!modal) return;

    // 尋找表單容器
    const form = modal.querySelector('form');
    if (!form) return;

    // 檢查是否已添加 Section 選擇器
    if (document.getElementById('sectionSelect')) return;

    // 建立 Section 選擇器
    const sectionSelectorHtml = `
      <div class="form-group mb-3" id="sectionSelectGroup">
        <label for="sectionSelect">區段</label>
        <select id="sectionSelect" class="form-control" required>
          <option value="">選擇區段...</option>
          ${this.getSectionOptions()}
        </select>
      </div>
    `;

    // 在優先級之後插入 Section 選擇器
    const priorityGroup = form.querySelector('[class*="priority"]')?.closest('.form-group');
    if (priorityGroup) {
      priorityGroup.insertAdjacentHTML('afterend', sectionSelectorHtml);
    } else {
      // 如果找不到優先級，就在表單開始處插入
      form.insertAdjacentHTML('afterbegin', sectionSelectorHtml);
    }

    // 綁定 Section 選擇變更事件
    document.getElementById('sectionSelect').addEventListener('change', (e) => {
      sessionStorage.setItem('selectedSectionForCreate', e.target.value);
    });
  }

  /**
   * 設置 Test Case 列表整合
   */
  setupTestCaseListIntegration() {
    // 監聽表格更新事件
    const observer = new MutationObserver(() => {
      this.enhanceTestCaseTable();
    });

    const table = document.getElementById('testCaseTable');
    if (table) {
      observer.observe(table, { childList: true, subtree: true });
      this.enhanceTestCaseTable();
    }
  }

  /**
   * 增強 Test Case 表格
   */
  enhanceTestCaseTable() {
    const table = document.getElementById('testCaseTable');
    if (!table) return;

    // 為每個 row 添加 section 資訊
    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(row => {
      const testCaseNumber = row.getAttribute('data-test-case-number');
      if (testCaseNumber) {
        // 從資料中讀取 section ID
        // 這需要在後端 API 返回 section 資訊
      }
    });
  }

  /**
   * 按 Section 過濾 Test Cases
   */
  filterTestCasesBySection() {
    const table = document.getElementById('testCaseTable');
    if (!table) return;

    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(row => {
      const rowSectionId = row.getAttribute('data-section-id');

      if (this.selectedSectionId === null) {
        // 顯示所有
        row.style.display = '';
      } else {
        // 只顯示選中 Section 的
        row.style.display = (parseInt(rowSectionId) === this.selectedSectionId) ? '' : 'none';
      }
    });
  }

  /**
   * 取得 Section 選項列表
   */
  getSectionOptions() {
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

    flattenSections(this.sections);
    return options.join('');
  }

  /**
   * 在新增 Test Case 時預填 Section
   */
  prefilSectionOnCreate() {
    const sectionSelect = document.getElementById('sectionSelect');
    if (!sectionSelect) return;

    // 優先使用已選擇的 Section
    if (this.selectedSectionId) {
      sectionSelect.value = this.selectedSectionId;
    } else {
      // 其次使用 sessionStorage 中保存的值
      const saved = sessionStorage.getItem('selectedSectionForCreate');
      if (saved) {
        sectionSelect.value = saved;
      } else {
        // 最後默認為 Unassigned
        const unassignedSection = this.findSectionByName('Unassigned');
        if (unassignedSection) {
          sectionSelect.value = unassignedSection.id;
        }
      }
    }
  }

  /**
   * 按名稱尋找 Section
   */
  findSectionByName(name, sections = this.sections) {
    for (const section of sections) {
      if (section.name === name) {
        return section;
      }
      if (section.children && section.children.length > 0) {
        const found = this.findSectionByName(name, section.children);
        if (found) return found;
      }
    }
    return null;
  }

  /**
   * 取得 Section 名稱
   */
  getSectionName(sectionId) {
    const section = this.findSectionById(sectionId);
    return section ? section.name : 'Unassigned';
  }

  /**
   * 按 ID 尋找 Section
   */
  findSectionById(sectionId, sections = this.sections) {
    for (const section of sections) {
      if (section.id == sectionId) {
        return section;
      }
      if (section.children && section.children.length > 0) {
        const found = this.findSectionById(sectionId, section.children);
        if (found) return found;
      }
    }
    return null;
  }

  /**
   * 在複製測試案例時移動到不同 Section
   */
  showCrossSectionCopyModal(testCaseId) {
    const modalHtml = `
      <div class="modal fade" id="crossSectionCopyModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">複製到其他區段</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
              <form id="crossSectionCopyForm">
                <div class="form-group mb-3">
                  <label for="crossSectionSelect">目標區段</label>
                  <select id="crossSectionSelect" class="form-control" required>
                    <option value="">選擇區段...</option>
                    ${this.getSectionOptions()}
                  </select>
                </div>
              </form>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
              <button type="button" class="btn btn-primary"
                      onclick="testCaseSectionIntegration.confirmCopyToSection(${testCaseId})">
                複製
              </button>
            </div>
          </div>
        </div>
      </div>
    `;

    // 移除舊 modal
    document.getElementById('crossSectionCopyModal')?.remove();

    // 添加新 modal
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    const modal = new bootstrap.Modal(document.getElementById('crossSectionCopyModal'));
    modal.show();
  }

  /**
   * 確認複製到其他 Section
   */
  async confirmCopyToSection(testCaseId) {
    const targetSectionId = document.getElementById('crossSectionSelect').value;

    if (!targetSectionId) {
      alert('請選擇目標區段');
      return;
    }

    try {
      // 這裡需要呼叫相應的 API 來複製 Test Case
      // 由於 Test Case API 還沒有完全更新，這個功能將在後續完成

      alert('複製功能將在後續版本支援');
      bootstrap.Modal.getInstance(document.getElementById('crossSectionCopyModal')).hide();

    } catch (error) {
      console.error('Error copying test case:', error);
      alert('複製失敗: ' + error.message);
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
const testCaseSectionIntegration = new TestCaseSectionIntegration();

// 監控 Test Case Modal 的開啟
document.addEventListener('show.bs.modal', (e) => {
  if (e.target.id === 'testCaseModal') {
    // 當 Modal 開啟時，預填 Section
    testCaseSectionIntegration.prefilSectionOnCreate();
  }
});

// 在 DOM 準備好後初始化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    testCaseSectionIntegration.init();
  });
}
