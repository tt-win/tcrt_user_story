/**
 * Test Case Section List 側邊欄模組
 *
 * 功能：
 * - 顯示 Section 樹狀結構
 * - Section 收合/展開
 * - 雙擊編輯 Section 名稱
 * - 右鍵菜單 (編輯/刪除)
 * - 拖拽排序和層級調整
 */

class TestCaseSectionList {
  constructor() {
    this.setId = null;
    this.sections = [];
    this.editingNodeId = null;
    this.init();
  }

  init() {
    console.log('[SectionList] Initializing TestCaseSectionList');

    // 監聽 Set 載入事件
    window.addEventListener('testCaseSetLoaded', (e) => {
      console.log('[SectionList] Received testCaseSetLoaded event:', {
        setId: e.detail.setId,
        sectionCount: e.detail.sections ? e.detail.sections.length : 0,
        sections: e.detail.sections
      });

      this.setId = e.detail.setId;
      this.sections = e.detail.sections || [];
      this.render();
    });
  }

  /**
   * 渲染 Section List 側邊欄
   */
  render() {
    if (!this.setId) {
      console.warn('[SectionList] No setId, skipping render');
      return;
    }

    console.log(`[SectionList] Rendering with setId=${this.setId}, sections=${this.sections.length}`);

    // 找到 testCasesPage 容器
    const testCasesPage = document.getElementById('testCasesPage');
    if (!testCasesPage) {
      console.error('[SectionList] Cannot find testCasesPage container');
      return;
    }

    // 第一次初始化時，設置為兩列布局
    if (!testCasesPage.dataset.twoColumnLayout) {
      testCasesPage.dataset.twoColumnLayout = 'true';

      // 改變 testCasesPage 為 row
      testCasesPage.classList.add('row', 'g-3');

      // 建立左列包裝器
      const mainCol = document.createElement('div');
      mainCol.id = 'testCasesMainCol';
      mainCol.className = 'col-lg-10';

      // 移動所有現有子節點到左列
      const children = Array.from(testCasesPage.children);
      for (const child of children) {
        if (child.id !== 'sectionListSidebarCol') {
          mainCol.appendChild(child);
        }
      }

      testCasesPage.appendChild(mainCol);
      console.log('[SectionList] Two column layout initialized');
    }

    // 檢查或建立側邊欄列
    let sidebarCol = document.getElementById('sectionListSidebarCol');
    if (!sidebarCol) {
      sidebarCol = document.createElement('div');
      sidebarCol.id = 'sectionListSidebarCol';
      sidebarCol.className = 'col-lg-2';
      testCasesPage.appendChild(sidebarCol);
      console.log('[SectionList] Sidebar column created');
    }

    // 構建側邊欄面板 HTML
    const panelHtml = `
      <div id="sectionListPanel" class="card sticky-top" style="top: 20px;">
        <div class="card-header bg-light d-flex justify-content-between align-items-center">
          <h6 class="mb-0">
            <i class="fas fa-folder-tree"></i> 區段列表
          </h6>
        </div>
        <div id="sectionListContent" class="card-body p-0" style="max-height: 600px; overflow-y: auto;">
          <!-- Section 樹會插入這裡 -->
        </div>
        <div class="card-footer">
          <button class="btn btn-sm btn-primary w-100" onclick="testCaseSectionList.showCreateSectionModal()">
            <i class="fas fa-plus"></i> 新增區段
          </button>
        </div>
      </div>
    `;

    // 插入側邊欄面板
    sidebarCol.innerHTML = panelHtml;
    console.log('[SectionList] Sidebar panel HTML inserted');

    // 渲染 Section 樹
    const content = document.getElementById('sectionListContent');
    if (content) {
      content.innerHTML = this.renderTree(this.sections);
      console.log(`[SectionList] Section tree rendered with ${this.sections.length} sections`);
    } else {
      console.error('[SectionList] Cannot find sectionListContent');
    }

    // 綁定事件
    this.bindEvents();
  }

  /**
   * 遞迴渲染樹狀結構
   */
  renderTree(sections) {
    if (!sections || sections.length === 0) {
      return '<div class="text-muted text-center py-3"><small>沒有區段</small></div>';
    }

    const html = sections.map(section => this.renderNode(section)).join('');
    return `<ul class="list-unstyled">${html}</ul>`;
  }

  /**
   * 渲染單個節點
   */
  renderNode(section) {
    const hasChildren = section.child_sections && section.child_sections.length > 0;
    const indent = (section.level - 1) * 15;

    return `
      <li class="section-node" data-section-id="${section.id}" style="margin-left: ${indent}px;">
        <div class="section-item p-2 mb-1 rounded"
             oncontextmenu="testCaseSectionList.showContextMenu(event, ${section.id})"
             ondblclick="testCaseSectionList.enterEditMode(${section.id})">

          ${hasChildren ? `
            <i class="fas fa-chevron-down section-toggle" style="width: 20px; text-align: center; cursor: pointer;"
               onclick="testCaseSectionList.toggleNode(this)"></i>
          ` : `
            <span style="width: 20px; display: inline-block;"></span>
          `}

          <i class="fas fa-folder text-muted"></i>
          <span class="section-name">${this.escapeHtml(section.name)}</span>
          <span class="badge bg-secondary ms-2">${section.test_case_count || 0}</span>
        </div>

        ${hasChildren ? `
          <ul class="list-unstyled section-children" style="display: block;">
            ${section.child_sections.map(child => this.renderNode(child)).join('')}
          </ul>
        ` : ''}
      </li>
    `;
  }

  /**
   * 綁定事件監聽器
   */
  bindEvents() {
    // 點擊 Section 過濾 Test Cases
    document.querySelectorAll('.section-item').forEach(item => {
      item.addEventListener('click', (e) => {
        if (e.target.classList.contains('section-toggle')) return;
        if (this.editingNodeId) return;

        const sectionId = item.closest('.section-node').dataset.sectionId;
        this.selectSection(sectionId);
      });
    });

    // 右鍵菜單事件已在 showContextMenu 中處理
  }

  /**
   * 切換節點展開/折疊
   */
  toggleNode(toggleIcon) {
    const li = toggleIcon.closest('.section-node');
    const children = li.querySelector('.section-children');

    if (children) {
      const isVisible = children.style.display !== 'none';
      children.style.display = isVisible ? 'none' : 'block';
      toggleIcon.classList.toggle('fa-chevron-right');
      toggleIcon.classList.toggle('fa-chevron-down');
    }
  }

  /**
   * 選擇 Section 並過濾 Test Cases
   */
  selectSection(sectionId) {
    // 移除之前的選擇
    document.querySelectorAll('.section-item').forEach(item => {
      item.classList.remove('bg-primary', 'text-white');
    });

    // 高亮當前選擇
    const selected = document.querySelector(`[data-section-id="${sectionId}"] .section-item`);
    if (selected) {
      selected.classList.add('bg-primary', 'text-white');
    }

    // 觸發自訂事件，通知其他模組進行過濾
    window.dispatchEvent(new CustomEvent('sectionSelected', {
      detail: { sectionId: parseInt(sectionId) }
    }));

    // 保存選擇
    sessionStorage.setItem('selectedSectionId', sectionId);
  }

  /**
   * 進入編輯模式
   */
  enterEditMode(sectionId) {
    const node = document.querySelector(`[data-section-id="${sectionId}"]`);
    const nameSpan = node.querySelector('.section-name');

    if (!nameSpan) return;

    this.editingNodeId = sectionId;
    const originalName = nameSpan.textContent;

    // 建立編輯框
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'form-control form-control-sm';
    input.value = originalName;
    input.style.display = 'inline-block';
    input.style.width = 'auto';
    input.style.minWidth = '150px';
    input.style.maxWidth = '250px';

    nameSpan.replaceWith(input);
    input.focus();
    input.select();

    // 儲存或取消編輯
    const saveEdit = async () => {
      const newName = input.value.trim();

      if (newName && newName !== originalName) {
        await this.updateSection(sectionId, newName);
      } else {
        const span = document.createElement('span');
        span.className = 'section-name';
        span.textContent = originalName;
        input.replaceWith(span);
      }

      this.editingNodeId = null;
    };

    input.addEventListener('blur', saveEdit);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        saveEdit();
      } else if (e.key === 'Escape') {
        const span = document.createElement('span');
        span.className = 'section-name';
        span.textContent = originalName;
        input.replaceWith(span);
        this.editingNodeId = null;
      }
    });
  }

  /**
   * 顯示右鍵菜單
   */
  showContextMenu(event, sectionId) {
    event.preventDefault();

    const menuHtml = `
      <div class="context-menu position-fixed" style="top: ${event.pageY}px; left: ${event.pageX}px; z-index: 10000;">
        <div class="card shadow-sm">
          <div class="list-group list-group-flush" style="min-width: 200px;">
            <button class="list-group-item list-group-item-action py-2" onclick="testCaseSectionList.enterEditMode(${sectionId}); document.querySelector('.context-menu')?.remove()">
              <i class="fas fa-edit"></i> 編輯名稱
            </button>
            <button class="list-group-item list-group-item-action py-2 text-danger" onclick="testCaseSectionList.deleteSection(${sectionId}); document.querySelector('.context-menu')?.remove()">
              <i class="fas fa-trash"></i> 刪除
            </button>
          </div>
        </div>
      </div>
    `;

    // 移除舊菜單
    document.querySelector('.context-menu')?.remove();

    // 添加新菜單
    document.body.insertAdjacentHTML('beforeend', menuHtml);

    // 點擊其他地方關閉菜單
    document.addEventListener('click', () => {
      document.querySelector('.context-menu')?.remove();
    }, { once: true });
  }

  /**
   * 顯示建立 Section Modal
   */
  showCreateSectionModal() {
    const modalHtml = `
      <div class="modal fade" id="createSectionModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">新增區段</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
              <form id="createSectionForm">
                <div class="form-group mb-3">
                  <label for="sectionName">區段名稱 <span class="text-danger">*</span></label>
                  <input type="text" id="sectionName" class="form-control" placeholder="例如: Smoke Tests" required>
                </div>
                <div class="form-group mb-3">
                  <label for="sectionDescription">描述</label>
                  <textarea id="sectionDescription" class="form-control" rows="2" placeholder="區段描述..."></textarea>
                </div>
                <div class="form-group mb-3">
                  <label for="parentSection">父區段</label>
                  <select id="parentSection" class="form-control">
                    <option value="">無 (頂層)</option>
                    ${this.getSectionOptions()}
                  </select>
                </div>
              </form>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
              <button type="button" class="btn btn-primary" onclick="testCaseSectionList.createSection()">建立</button>
            </div>
          </div>
        </div>
      </div>
    `;

    // 移除舊 modal
    document.getElementById('createSectionModal')?.remove();

    // 添加新 modal
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    const modal = new bootstrap.Modal(document.getElementById('createSectionModal'));
    modal.show();
  }

  /**
   * 取得 Section 選項列表
   */
  getSectionOptions() {
    const options = [];

    const flattenSections = (sections, prefix = '') => {
      sections.forEach(section => {
        if (section.level < 5) {  // 最多 5 層
          options.push(
            `<option value="${section.id}">${prefix}${this.escapeHtml(section.name)}</option>`
          );
        }
        if (section.child_sections && section.child_sections.length > 0) {
          flattenSections(section.child_sections, prefix + '  ');
        }
      });
    };

    flattenSections(this.sections);
    return options.join('');
  }

  /**
   * 建立 Section
   */
  async createSection() {
    const name = document.getElementById('sectionName').value.trim();
    const description = document.getElementById('sectionDescription').value.trim();
    const parentId = document.getElementById('parentSection').value || null;

    if (!name) {
      alert('區段名稱不可空白');
      return;
    }

    try {
      // 獲取 team_id 和當前 set_id
      const urlParams = new URLSearchParams(window.location.search);
      const teamId = urlParams.get('team_id');

      if (!teamId) {
        alert('無法取得團隊 ID');
        return;
      }

      const response = await window.AuthClient.fetch(
        `/api/test-case-sets/${this.setId}/sections`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            name,
            description: description || null,
            parent_section_id: parentId ? parseInt(parentId) : null,
            sort_order: 0
          })
        }
      );

      if (!response.ok) {
        let errorDetail = 'Failed to create section';
        try {
          const errorData = await response.json();
          console.log('API Error response:', errorData);
          if (errorData.detail) {
            if (typeof errorData.detail === 'string') {
              errorDetail = errorData.detail;
            } else if (Array.isArray(errorData.detail)) {
              errorDetail = errorData.detail.map(e =>
                typeof e === 'string' ? e : JSON.stringify(e)
              ).join('; ');
            } else {
              errorDetail = JSON.stringify(errorData.detail);
            }
          }
        } catch (e) {
          console.error('Failed to parse error response:', e);
        }
        throw new Error(errorDetail);
      }

      const modal = bootstrap.Modal.getInstance(document.getElementById('createSectionModal'));
      if (modal) {
        modal.hide();
      }

      // 重新載入 Sections
      console.log('[SectionList] Section created, reloading sections...');
      await this.loadSections();

    } catch (error) {
      console.error('Error creating section:', error);
      alert('建立區段失敗: ' + error.message);
    }
  }

  /**
   * 更新 Section
   */
  async updateSection(sectionId, newName) {
    try {
      const response = await fetch(
        `/api/test-case-sets/${this.setId}/sections/${sectionId}`,
        {
          method: 'PUT',
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('token')}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ name: newName })
        }
      );

      if (!response.ok) {
        throw new Error('Failed to update section');
      }

      // 更新本地資料
      const section = this.findSection(sectionId);
      if (section) {
        section.name = newName;
      }

      // 重新渲染
      this.render();

    } catch (error) {
      console.error('Error updating section:', error);
      alert('更新區段失敗: ' + error.message);
    }
  }

  /**
   * 刪除 Section
   */
  async deleteSection(sectionId) {
    if (!confirm('確定要刪除此區段嗎？該區段下的測試案例將被移到 Unassigned。')) {
      return;
    }

    try {
      const response = await fetch(
        `/api/test-case-sets/${this.setId}/sections/${sectionId}`,
        {
          method: 'DELETE',
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('token')}`
          }
        }
      );

      if (!response.ok) {
        throw new Error('Failed to delete section');
      }

      // 重新載入 Sections
      await this.loadSections();

    } catch (error) {
      console.error('Error deleting section:', error);
      alert('刪除區段失敗: ' + error.message);
    }
  }

  /**
   * 載入 Sections
   */
  async loadSections() {
    if (!this.setId) return;

    try {
      const response = await window.AuthClient.fetch(
        `/api/test-case-sets/${this.setId}/sections`
      );

      if (!response.ok) {
        throw new Error('Failed to load sections');
      }

      this.sections = await response.json();
      this.render();

    } catch (error) {
      console.error('Error loading sections:', error);
    }
  }

  /**
   * 尋找 Section
   */
  findSection(sectionId, sections = this.sections) {
    for (const section of sections) {
      if (section.id == sectionId) {
        return section;
      }
      if (section.child_sections && section.child_sections.length > 0) {
        const found = this.findSection(sectionId, section.child_sections);
        if (found) return found;
      }
    }
    return null;
  }

  /**
   * 切換側邊欄
   */
  togglePanel() {
    const content = document.getElementById('sectionListContent');
    if (content) {
      const isVisible = content.style.display !== 'none';
      content.style.display = isVisible ? 'none' : 'block';
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
const testCaseSectionList = new TestCaseSectionList();

// 在 DOM 準備好後初始化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    testCaseSectionList.init();
  });
}
