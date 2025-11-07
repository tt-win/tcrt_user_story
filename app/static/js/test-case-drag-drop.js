/**
 * Test Case 和 Section 拖拽功能模組
 *
 * 功能：
 * - 拖拽 Test Case 到不同 Section
 * - 拖拽 Section 排序
 * - 拖拽 Section 調整層級
 */

class TestCaseDragDrop {
  constructor() {
    this.draggedElement = null;
    this.draggedData = null;
    this.dropZones = [];
    this.init();
  }

  init() {
    // 監聽 Set 載入和 Section 變更
    window.addEventListener('testCaseSetLoaded', () => {
      this.setupSectionDragDrop();
    });

    window.addEventListener('sectionListUpdated', () => {
      this.setupSectionDragDrop();
    });

    // 初始化 Test Case 拖拽
    this.setupTestCaseDragDrop();
  }

  /**
   * 設置 Section 拖拽功能
   */
  setupSectionDragDrop() {
    // 監控 Section 項目的變更，動態添加拖拽支援
    const observer = new MutationObserver(() => {
      this.enableSectionDragDrop();
    });

    const sectionList = document.getElementById('sectionListContent');
    if (sectionList) {
      observer.observe(sectionList, { childList: true, subtree: true });
      this.enableSectionDragDrop();
    }
  }

  /**
   * 啟用 Section 拖拽
   */
  enableSectionDragDrop() {
    const sectionItems = document.querySelectorAll('.section-item');

    sectionItems.forEach(item => {
      // 如果已經綁定，就不再綁定
      if (item.dataset.dragDropEnabled) return;

      item.draggable = true;
      item.dataset.dragDropEnabled = 'true';

      item.addEventListener('dragstart', (e) => this.handleSectionDragStart(e));
      item.addEventListener('dragover', (e) => this.handleSectionDragOver(e));
      item.addEventListener('drop', (e) => this.handleSectionDrop(e));
      item.addEventListener('dragend', (e) => this.handleDragEnd(e));
    });
  }

  /**
   * 設置 Test Case 拖拽功能
   */
  setupTestCaseDragDrop() {
    const observer = new MutationObserver(() => {
      this.enableTestCaseDragDrop();
    });

    const table = document.getElementById('testCaseTable');
    if (table) {
      observer.observe(table, { childList: true, subtree: true });
      this.enableTestCaseDragDrop();
    }
  }

  /**
   * 啟用 Test Case 拖拽
   */
  enableTestCaseDragDrop() {
    const rows = document.querySelectorAll('#testCaseTable tbody tr');

    rows.forEach(row => {
      // 如果已經綁定，就不再綁定
      if (row.dataset.dragDropEnabled) return;

      row.draggable = true;
      row.dataset.dragDropEnabled = 'true';
      row.style.cursor = 'move';

      row.addEventListener('dragstart', (e) => this.handleTestCaseDragStart(e));
      row.addEventListener('dragend', (e) => this.handleDragEnd(e));
    });

    // 設置 Section 為 Drop Target
    const sectionNodes = document.querySelectorAll('.section-node');
    sectionNodes.forEach(node => {
      node.addEventListener('dragover', (e) => this.handleTestCaseDragOver(e));
      node.addEventListener('drop', (e) => this.handleTestCaseDrop(e));
      node.addEventListener('dragleave', (e) => this.handleTestCaseDragLeave(e));
    });
  }

  /**
   * Section 拖拽開始
   */
  handleSectionDragStart(e) {
    const sectionNode = e.target.closest('.section-node');
    const sectionId = sectionNode.dataset.sectionId;

    this.draggedElement = sectionNode;
    this.draggedData = {
      type: 'section',
      sectionId: parseInt(sectionId)
    };

    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', `section-${sectionId}`);

    // 視覺反饋
    sectionNode.style.opacity = '0.5';
    sectionNode.style.backgroundColor = '#e9ecef';
  }

  /**
   * Section 拖拽懸停
   */
  handleSectionDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';

    const target = e.target.closest('.section-node');
    if (target && target !== this.draggedElement) {
      target.style.borderTop = '3px solid #007bff';
    }
  }

  /**
   * Section 放下
   */
  async handleSectionDrop(e) {
    e.preventDefault();

    if (!this.draggedData || this.draggedData.type !== 'section') return;

    const targetNode = e.target.closest('.section-node');
    if (!targetNode || targetNode === this.draggedElement) return;

    // 移除視覺反饋
    document.querySelectorAll('.section-node').forEach(node => {
      node.style.borderTop = '';
    });

    try {
      // 調用 API 重新排序
      const parentSection = targetNode.closest('.section-children')?.closest('.section-node');
      const parentId = parentSection ? parentSection.dataset.sectionId : null;

      // 這裡應該呼叫 API 來更新順序
      // 暫時註釋，因為還需要完整的排序邏輯
      console.log(`Moving section ${this.draggedData.sectionId} under section ${parentId}`);

      // 提示用戶功能即將推出
      alert('拖拽排序功能將在下一版本推出');

    } catch (error) {
      console.error('Error moving section:', error);
    }
  }

  /**
   * Test Case 拖拽開始
   */
  handleTestCaseDragStart(e) {
    const row = e.target.closest('tr');
    const testCaseId = row.getAttribute('data-record-id') || row.getAttribute('data-test-case-id');

    this.draggedElement = row;
    this.draggedData = {
      type: 'testcase',
      testCaseId: testCaseId
    };

    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', `testcase-${testCaseId}`);

    // 視覺反饋
    row.style.opacity = '0.6';
    row.style.backgroundColor = '#f0f0f0';
  }

  /**
   * Test Case 拖拽懸停
   */
  handleTestCaseDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';

    const target = e.target.closest('.section-node');
    if (target) {
      target.style.backgroundColor = '#e3f2fd';
      target.style.borderLeft = '3px solid #007bff';
    }
  }

  /**
   * Test Case 拖拽離開
   */
  handleTestCaseDragLeave(e) {
    const target = e.target.closest('.section-node');
    if (target) {
      target.style.backgroundColor = '';
      target.style.borderLeft = '';
    }
  }

  /**
   * Test Case 放下
   */
  async handleTestCaseDrop(e) {
    e.preventDefault();

    if (!this.draggedData || this.draggedData.type !== 'testcase') return;

    const targetNode = e.target.closest('.section-node');
    if (!targetNode) return;

    // 移除視覺反饋
    document.querySelectorAll('.section-node').forEach(node => {
      node.style.backgroundColor = '';
      node.style.borderLeft = '';
    });

    try {
      const targetSectionId = parseInt(targetNode.dataset.sectionId);
      const testCaseId = this.draggedData.testCaseId;

      // 調用 API 移動 Test Case
      const response = await fetch(`/api/testcases/move-to-section`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          test_case_ids: [testCaseId],
          target_section_id: targetSectionId
        })
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to move test case');
      }

      // 刷新表格
      if (typeof loadTestCases === 'function') {
        await loadTestCases();
      }

      console.log(`Test case ${testCaseId} moved to section ${targetSectionId}`);

    } catch (error) {
      console.error('Error moving test case:', error);
      alert('移動測試案例失敗: ' + error.message);
    }
  }

  /**
   * 拖拽結束
   */
  handleDragEnd(e) {
    // 移除所有視覺反饋
    if (this.draggedElement) {
      this.draggedElement.style.opacity = '';
      this.draggedElement.style.backgroundColor = '';
    }

    document.querySelectorAll('.section-node').forEach(node => {
      node.style.backgroundColor = '';
      node.style.borderLeft = '';
      node.style.borderTop = '';
    });

    this.draggedElement = null;
    this.draggedData = null;
  }
}

// 建立全域實例
const testCaseDragDrop = new TestCaseDragDrop();

// 在 DOM 準備好後初始化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    testCaseDragDrop.init();
  });
}
