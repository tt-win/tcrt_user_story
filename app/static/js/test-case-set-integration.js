/**
 * Test Case Set 整合模組
 *
 * 功能：
 * - 在 Test Case Management 頁面頂部顯示當前 Test Case Set
 * - 提供 Set 選擇/切換功能
 * - 管理 Set 上下文
 */

class TestCaseSetIntegration {
  constructor() {
    this._initialized = false;
    this.currentSetId = null;
    this.currentTeamId = null;
    this.testCaseSets = [];
    this.init();
  }

  init() {
    if (this._initialized) {
      return;
    }
    this._initialized = true;

    // helper 模式不應自動帶入既有 set context（避免背景誤切入某個 Set）
    const helperMode = this.isHelperMode();
    const setIdFromUrl = this.getUrlParam('set_id');

    if (helperMode) {
      try {
        sessionStorage.removeItem('selectedTestCaseSetId');
        sessionStorage.removeItem('selectedTestCaseSetName');
      } catch (_) {}
    }

    // 一般模式：URL 優先，其次 sessionStorage
    // helper 模式：僅採用 URL 的 set_id（通常為空），忽略 sessionStorage
    this.currentSetId = helperMode
      ? setIdFromUrl
      : (setIdFromUrl || sessionStorage.getItem('selectedTestCaseSetId'));
    this.currentTeamId = this.getTeamIdFromPage();

    if (this.currentSetId && this.currentTeamId) {
      this.loadCurrentSet();
    }
  }

  isHelperMode() {
    if (typeof window !== 'undefined' && window.__TCM_HELPER_MODE__ === true) {
      return true;
    }
    const helper = (this.getUrlParam('helper') || '').toLowerCase();
    return helper === '1' || helper === 'true';
  }

  /**
   * 從頁面讀取當前 Team ID
   * 優先順序：URL 參數（共享連結） > 全域變數 > localStorage
   */
  getTeamIdFromPage() {
    // 共享連結：URL 的 team_id 優先，確保不同 team 時能正確導向
    const teamParam = this.getUrlParam('team_id') || this.getUrlParam('teamId') || this.getUrlParam('team');
    if (teamParam) {
      return teamParam;
    }
    // 嘗試從全域變數讀取
    if (typeof teamId !== 'undefined') {
      return teamId;
    }
    // 從 localStorage 讀取
    return localStorage.getItem('currentTeamId');
  }

  /**
   * 讀取 URL 參數
   */
  getUrlParam(paramName) {
    const params = new URLSearchParams(window.location.search);
    return params.get(paramName);
  }

  /**
   * 載入當前 Set 資訊
   */
  async loadCurrentSet() {
    try {
      const response = await fetch(
        `/api/test-case-sets/${this.currentSetId}/sections`,
        {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('token')}`
          }
        }
      );

      if (!response.ok) {
        throw new Error('Failed to load test case set');
      }

      const sections = await response.json();
      this.sections = sections;
      this.renderSetHeader();
      this.loadTestCaseSets();

      // 觸發自訂事件，通知其他模組 Set 已載入
      window.dispatchEvent(new CustomEvent('testCaseSetLoaded', {
        detail: { setId: this.currentSetId, sections: sections }
      }));

    } catch (error) {
      console.error('Error loading test case set:', error);
    }
  }

  /**
   * 渲染 Set 標題欄
   */
  renderSetHeader() {
    // 在現有的頁面標題之前插入 Set 選擇欄
    const header = document.querySelector('.card-header') ||
                   document.querySelector('h1') ||
                   document.querySelector('.page-header');

    if (!header) return;

    const setHeaderHtml = `
      <div id="testCaseSetHeader" class="card mb-3">
        <div class="card-body d-flex align-items-center justify-content-between">
          <div>
            <h6 class="mb-1">
              <i class="fas fa-folder"></i>
              當前集合
            </h6>
            <p id="currentSetName" class="mb-0 text-primary">
              <strong>載入中...</strong>
            </p>
          </div>
          <button class="btn btn-outline-primary btn-sm" id="switchSetBtn" onclick="testCaseSetIntegration.showSetSelector()">
            <i class="fas fa-exchange-alt"></i> 切換集合
          </button>
        </div>
      </div>
    `;

    // 如果已存在則移除
    const existing = document.getElementById('testCaseSetHeader');
    if (existing) {
      existing.remove();
    }

    // 在頁面開始插入
    const container = document.querySelector('.container-fluid') ||
                      document.body;
    container.insertAdjacentHTML('afterbegin', setHeaderHtml);
  }

  /**
   * 載入所有 Test Case Sets
   */
  async loadTestCaseSets() {
    if (!this.currentTeamId) return;

    try {
      const response = await fetch(
        `/api/teams/${this.currentTeamId}/test-case-sets`,
        {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('token')}`
          }
        }
      );

      if (!response.ok) {
        throw new Error('Failed to load test case sets');
      }

      this.testCaseSets = await response.json();
      this.updateSetHeader();

    } catch (error) {
      console.error('Error loading test case sets:', error);
    }
  }

  /**
   * 更新 Set 標題
   */
  updateSetHeader() {
    const currentSet = this.testCaseSets.find(s => s.id == this.currentSetId);
    const headerName = document.getElementById('currentSetName');

    if (headerName) {
      if (currentSet) {
        headerName.innerHTML = `
          <strong>${this.escapeHtml(currentSet.name)}</strong>
          ${currentSet.is_default ? '<i class="fas fa-star text-warning ms-2"></i>' : ''}
          <br>
          <small class="text-muted">${currentSet.test_case_count || 0} 個測試案例</small>
        `;
        // 保存 Set 名稱到 sessionStorage，以備區段列表使用
        sessionStorage.setItem('selectedTestCaseSetName', currentSet.name);
      } else {
        headerName.innerHTML = '<strong>集合不存在</strong>';
      }
    }

    // 觸發事件，通知其他模組 Set 頭部已更新
    window.dispatchEvent(new CustomEvent('setHeaderUpdated', {
      detail: {
        currentSetId: this.currentSetId,
        teamId: this.currentTeamId,
        currentSet: currentSet
      }
    }));
  }

  /**
   * 顯示 Set 選擇器
   */
  showSetSelector() {
    const modalHtml = `
      <div class="modal fade" id="setSelectModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">選擇測試案例集合</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body" id="setSelectList">
              <div class="text-center">
                <div class="spinner-border" role="status">
                  <span class="visually-hidden">載入中...</span>
                </div>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
              <a href="/test-case-sets" class="btn btn-primary">管理集合</a>
            </div>
          </div>
        </div>
      </div>
    `;

    // 移除舊 modal
    const existing = document.getElementById('setSelectModal');
    if (existing) {
      existing.remove();
    }

    // 添加新 modal
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // 填充列表
    const listContainer = document.getElementById('setSelectList');
    listContainer.innerHTML = this.testCaseSets.map(set => `
      <div class="list-group-item p-3 border-bottom d-flex justify-content-between align-items-center"
           style="cursor: pointer;"
           onmouseover="this.style.backgroundColor='#f8f9fa'"
           onmouseout="this.style.backgroundColor='white'"
           onclick="testCaseSetIntegration.switchSet(${set.id})">
        <div>
          <h6 class="mb-1">
            ${set.is_default ? '<i class="fas fa-star text-warning"></i> ' : ''}
            ${this.escapeHtml(set.name)}
          </h6>
          <small class="text-muted">${set.test_case_count || 0} 個測試案例</small>
        </div>
        ${set.id == this.currentSetId ? '<i class="fas fa-check text-success"></i>' : ''}
      </div>
    `).join('');

    const modal = new bootstrap.Modal(document.getElementById('setSelectModal'));
    modal.show();
  }

  /**
   * 切換 Set
   */
  switchSet(setId) {
    if (setId !== this.currentSetId) {
      sessionStorage.setItem('selectedTestCaseSetId', setId);
      window.location.href = `/test-case-management?set_id=${setId}`;
    } else {
      bootstrap.Modal.getInstance(document.getElementById('setSelectModal')).hide();
    }
  }

  /**
   * 取得當前 Set ID
   */
  getCurrentSetId() {
    return this.currentSetId;
  }

  /**
   * 取得所有 Sections
   */
  getSections() {
    return this.sections || [];
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
const testCaseSetIntegration = new TestCaseSetIntegration();

// 確保 DOM 準備就緒後初始化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    testCaseSetIntegration.init();
  });
}
