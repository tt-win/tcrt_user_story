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
    this.nextSectionEventMeta = null;
    this.init();
  }

  init() {
    console.log("[SectionList] Initializing TestCaseSectionList");

    // 監聽 Set 載入事件
    window.addEventListener("testCaseSetLoaded", (e) => {
      console.log("[SectionList] Received testCaseSetLoaded event:", {
        setId: e.detail.setId,
        sectionCount: e.detail.sections ? e.detail.sections.length : 0,
        sections: e.detail.sections,
      });

      this.setId = e.detail.setId;
      this.sections = e.detail.sections || [];
      this.render();
    });

    // 監聽窗口大小改變，動態調整面板高度
    window.addEventListener("resize", () => {
      this.adjustPanelHeight();
    });
  }

  /**
   * 渲染 Section List 側邊欄
   */
  render() {
    if (!this.setId) {
      console.warn("[SectionList] No setId, skipping render");
      return;
    }

    console.log(
      `[SectionList] Rendering with setId=${this.setId}, sections=${this.sections.length}`,
    );

    // 找到 testCasesPage 容器
    const testCasesPage = document.getElementById("testCasesPage");
    if (!testCasesPage) {
      console.error("[SectionList] Cannot find testCasesPage container");
      return;
    }

    // 第一次初始化時，設置為兩列布局
    if (!testCasesPage.dataset.twoColumnLayout) {
      testCasesPage.dataset.twoColumnLayout = "true";

      // testCasesPage 已由 CSS 設置為 flex row 布局

      // 建立左列包裝器
      const mainCol = document.createElement("div");
      mainCol.id = "testCasesMainCol";
      // 不使用 bootstrap col classes，改用 pure flex
      // 寬度由 CSS 的 flex: 1 控制

      // 移動所有現有子節點到左列
      const children = Array.from(testCasesPage.children);
      for (const child of children) {
        if (child.id !== "sectionListSidebarCol") {
          mainCol.appendChild(child);
        }
      }

      testCasesPage.appendChild(mainCol);
      console.log(
        "[SectionList] Two column layout initialized with flex styles",
      );
    }

    // 檢查或建立側邊欄列
    let sidebarCol = document.getElementById("sectionListSidebarCol");
    if (!sidebarCol) {
      sidebarCol = document.createElement("div");
      sidebarCol.id = "sectionListSidebarCol";
      testCasesPage.appendChild(sidebarCol);
      console.log("[SectionList] Sidebar column created");
    }

    // 不使用 bootstrap col classes，改用 pure flex
    // 寬度和高度由 CSS 的 flex: 0 0 auto 和 overflow-y: auto 控制

    // 構建側邊欄面板 HTML
    const panelHtml = `
      <div id="sectionListPanel" class="card section-list-panel" style="display: flex; flex-direction: column; flex: 1; min-height: 0; margin: 0; border-radius: 4px;">
        <div class="card-header bg-light d-flex justify-content-between align-items-center" style="flex-shrink: 0;">
          <h6 class="mb-0">
            <i class="fas fa-folder-tree"></i> 區段列表
          </h6>
        </div>
        <div id="sectionListContent" class="card-body p-0 section-list-content" style="flex: 1; overflow-y: auto; min-height: 0;">
          <!-- Section 樹會插入這裡 -->
        </div>
        <div class="card-footer section-list-footer" style="flex-shrink: 0;">
          <button class="btn btn-sm btn-primary w-100 mb-2" onclick="testCaseSectionList.showCreateSectionModal()">
            <i class="fas fa-plus"></i> 新增區段
          </button>
          <button class="btn btn-sm btn-outline-secondary w-100" onclick="testCaseSectionList.showReorderModal()">
            <i class="fas fa-arrows-up-down"></i> 編輯順序
          </button>
        </div>
      </div>
    `;

    // 插入側邊欄面板
    sidebarCol.innerHTML = panelHtml;
    console.log("[SectionList] Sidebar panel HTML inserted");

    // 渲染 Section 樹
    const content = document.getElementById("sectionListContent");
    if (content) {
      content.innerHTML = this.renderTree(this.sections);
      console.log(
        `[SectionList] Section tree rendered with ${this.sections.length} sections`,
      );
    } else {
      console.error("[SectionList] Cannot find sectionListContent");
    }

    // 綁定事件
    this.bindEvents();

    // 動態調整高度以適應視口
    this.adjustPanelHeight();

    try {
      const snapshot = Array.isArray(this.sections)
        ? JSON.parse(JSON.stringify(this.sections))
        : [];
      const detail = {
        setId: this.setId,
        sections: snapshot,
        ...(this.nextSectionEventMeta || {}),
      };
      window.dispatchEvent(
        new CustomEvent("sectionListUpdated", {
          detail,
        }),
      );
      this.nextSectionEventMeta = null;
    } catch (err) {
      console.warn("[SectionList] Failed to dispatch sectionListUpdated:", err);
    }
  }

  /**
   * 遞迴渲染樹狀結構
   */
  renderTree(sections) {
    if (!sections || sections.length === 0) {
      return '<div class="text-muted text-center py-3"><small>沒有區段</small></div>';
    }

    const orderedSections = this.sortSectionsForDisplay(sections);
    const html = orderedSections.map((section) => this.renderNode(section)).join("");
    return `<ul class="list-unstyled">${html}</ul>`;
  }

  /**
   * 渲染單個節點
   */
  renderNode(section) {
    const children = this.sortSectionsForDisplay(this.getChildSections(section));
    const hasChildren = children.length > 0;
    const indent = (section.level - 1) * 15;
    const isUnassigned = section.name === "Unassigned";

    return `
      <li class="section-node" data-section-id="${section.id}" data-parent-id="${section.parent_section_id || ''}" style="margin-left: ${indent}px;" draggable="${!isUnassigned}">
        <div class="section-item p-2 mb-1 rounded"
             ${!isUnassigned ? `oncontextmenu="testCaseSectionList.showContextMenu(event, ${section.id})"` : ""}
             ${!isUnassigned ? `ondblclick="testCaseSectionList.enterEditMode(${section.id})"` : ""}>

          ${
            hasChildren
              ? `
            <i class="fas fa-chevron-down section-toggle" style="width: 14px; text-align: center; cursor: pointer;"
               onclick="testCaseSectionList.toggleNode(this)"></i>
          `
              : `
            <span style="width: 14px; display: inline-block;"></span>
          `
          }

          <i class="fas fa-folder text-muted"></i>
          <span class="section-name ${isUnassigned ? "fw-bold text-muted" : ""}">${this.escapeHtml(section.name)}${isUnassigned ? " (系統)" : ""}</span>
          <span class="badge bg-secondary ms-2">${section.test_case_count || 0}</span>
        </div>

        ${
          hasChildren
            ? `
          <ul class="list-unstyled section-children" style="display: block;">
            ${children.map((child) => this.renderNode(child)).join("")}
          </ul>
        `
            : ""
        }
      </li>
    `;
  }

  /**
   * 綁定事件監聽器
   */
  bindEvents() {
    // 點擊 Section 過濾 Test Cases
    document.querySelectorAll(".section-item").forEach((item) => {
      item.addEventListener("click", (e) => {
        if (e.target.classList.contains("section-toggle")) return;
        if (this.editingNodeId) return;

        const sectionId = item.closest(".section-node").dataset.sectionId;
        this.selectSection(sectionId);
      });
    });

    // 綁定拖移事件
    document.querySelectorAll(".section-node[draggable='true']").forEach((node) => {
      node.addEventListener("dragstart", (e) => this.handleDragStart(e));
      node.addEventListener("dragover", (e) => this.handleDragOver(e));
      node.addEventListener("drop", (e) => this.handleDrop(e));
      node.addEventListener("dragend", (e) => this.handleDragEnd(e));
      node.addEventListener("dragleave", (e) => this.handleDragLeave(e));
    });

    // 右鍵菜單事件已在 showContextMenu 中處理
  }

  /**
   * 拖移開始
   */
  handleDragStart(e) {
    const node = e.target.closest(".section-node");
    if (!node) return;

    e.dataTransfer.effectAllowed = "move";
    this.draggedNode = node;
    this.draggedSectionId = parseInt(node.dataset.sectionId);
    if (Number.isNaN(this.draggedSectionId)) {
      this.draggedSectionId = null;
      this.draggedNode = null;
      return;
    }
    node.style.opacity = "0.5";
    try {
      e.dataTransfer.setData("text/plain", String(this.draggedSectionId));
    } catch (_) {}
  }

  /**
   * 拖移經過
   */
  handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";

    const target = e.target.closest(".section-node");
    if (!target || target === this.draggedNode) return;

    const rect = target.getBoundingClientRect();
    const dropY = e.clientY - rect.top;
    const threshold = rect.height / 3;
    this.clearDropIndicators();

    if (dropY < threshold) {
      target.style.borderTop = "3px solid #007bff";
    } else if (dropY > threshold * 2) {
      target.style.borderBottom = "3px solid #007bff";
    } else {
      target.style.backgroundColor = "#e3f2fd";
    }
  }

  /**
   * 拖移離開
   */
  handleDragLeave(e) {
    const node = e.target.closest(".section-node");
    if (node) {
      node.style.borderTop = "";
      node.style.borderBottom = "";
      node.style.backgroundColor = "";
    }
  }

  /**
   * 拖移放下
   */
  async handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();

    if (!this.draggedNode || !this.draggedSectionId) {
      this.clearDropIndicators();
      return;
    }

    const targetNode = e.target.closest(".section-node");
    if (!targetNode || targetNode === this.draggedNode) {
      this.clearDropIndicators();
      return;
    }

    const targetSectionId = parseInt(targetNode.dataset.sectionId);
    const rect = targetNode.getBoundingClientRect();
    const dropY = e.clientY;
    const threshold = rect.height / 3;

    // 判斷放下位置
    const dropPosition = dropY - rect.top;

    let dropType = "inside";
    if (dropPosition < threshold) {
      dropType = "before";
    } else if (dropPosition > threshold * 2) {
      dropType = "after";
    }

    const success = await this.applySectionDrag(this.draggedSectionId, targetSectionId, dropType);
    this.clearDropIndicators();
    this.resetDragState();

    if (success) {
      await this.loadSections();
    }
  }

  /**
   * 拖移結束
   */
  handleDragEnd() {
    this.clearDropIndicators();
    if (this.draggedNode) {
      this.draggedNode.style.opacity = "1";
      this.draggedNode.style.borderTop = "";
      this.draggedNode.style.borderBottom = "";
      this.draggedNode.style.backgroundColor = "";
    }

    this.resetDragState();
  }

  resetDragState() {
    this.draggedNode = null;
    this.draggedSectionId = null;
  }

  async applySectionDrag(draggedId, targetId, dropType) {
    try {
      const draggedInfo = this.findSectionWithParent(draggedId);
      if (!draggedInfo) return false;
      const sourceParentId = draggedInfo.parentId ?? null;

      const targetInfo = this.findSectionWithParent(targetId);
      const targetParentId =
        dropType === "inside"
          ? targetId
          : targetInfo
            ? targetInfo.parentId ?? null
            : null;

      if (targetParentId === draggedId) {
        console.warn("Cannot move section into itself");
        return false;
      }

      if (this.sectionContainsDescendant(draggedId, targetParentId)) {
        console.warn("Cannot move section into its descendant");
        return false;
      }

      const sourceIds = this.getSiblingIds(sourceParentId).filter(id => id !== draggedId);
      let targetIds;
      if (sourceParentId === targetParentId) {
        targetIds = [...sourceIds];
      } else {
        targetIds = this.getSiblingIds(targetParentId).filter(id => id !== draggedId);
      }

      let insertIndex = targetIds.length;
      if (dropType === "before" || dropType === "after") {
        const targetIndex = targetIds.indexOf(targetId);
        if (targetIndex >= 0) {
          insertIndex = dropType === "before" ? targetIndex : targetIndex + 1;
        }
      }
      if (insertIndex < 0) insertIndex = 0;
      targetIds.splice(insertIndex, 0, draggedId);

      const payload = [];
      if (sourceParentId !== targetParentId) {
        payload.push(
          ...sourceIds.map((id, idx) => ({
            id,
            parent_section_id: sourceParentId,
            sort_order: idx,
          })),
        );
      }
      payload.push(
        ...targetIds.map((id, idx) => ({
          id,
          parent_section_id: targetParentId,
          sort_order: idx,
        })),
      );

      return await this.saveSectionOrderPayload(payload);
    } catch (error) {
      console.error("applySectionDrag failed:", error);
      return false;
    }
  }

  /**
   * 切換節點展開/折疊
   */
  toggleNode(toggleIcon) {
    const li = toggleIcon.closest(".section-node");
    const children = li.querySelector(".section-children");

    if (children) {
      const isVisible = children.style.display !== "none";
      children.style.display = isVisible ? "none" : "block";
      toggleIcon.classList.toggle("fa-chevron-right");
      toggleIcon.classList.toggle("fa-chevron-down");
    }
  }

  /**
   * 選擇 Section 並過濾 Test Cases
   */
  selectSection(sectionId) {
    // 移除之前的選擇
    document.querySelectorAll(".section-item").forEach((item) => {
      item.classList.remove("bg-primary", "text-white");
    });

    // 高亮當前選擇
    const selected = document.querySelector(
      `[data-section-id="${sectionId}"] .section-item`,
    );
    if (selected) {
      selected.classList.add("bg-primary", "text-white");
    }

    // 觸發自訂事件，通知其他模組進行過濾
    window.dispatchEvent(
      new CustomEvent("sectionSelected", {
        detail: { sectionId: parseInt(sectionId) },
      }),
    );

    // 保存選擇
    sessionStorage.setItem("selectedSectionId", sectionId);
  }

  /**
   * 進入編輯模式
   */
  enterEditMode(sectionId) {
    const node = document.querySelector(`[data-section-id="${sectionId}"]`);
    const nameSpan = node.querySelector(".section-name");

    if (!nameSpan) return;

    const originalName = nameSpan.textContent;

    // 防止編輯 Unassigned Section
    if (originalName === "Unassigned") {
      alert('無法編輯系統區段 "Unassigned"');
      return;
    }

    this.editingNodeId = sectionId;

    // 建立編輯框
    const input = document.createElement("input");
    input.type = "text";
    input.className = "form-control form-control-sm";
    input.value = originalName;
    input.style.display = "inline-block";
    input.style.width = "auto";
    input.style.minWidth = "150px";
    input.style.maxWidth = "250px";

    nameSpan.replaceWith(input);
    input.focus();
    input.select();

    // 儲存或取消編輯
    const saveEdit = async () => {
      const newName = input.value.trim();

      if (newName && newName !== originalName) {
        await this.updateSection(sectionId, newName);
      } else {
        const span = document.createElement("span");
        span.className = "section-name";
        span.textContent = originalName;
        input.replaceWith(span);
      }

      this.editingNodeId = null;
    };

    input.addEventListener("blur", saveEdit);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        saveEdit();
      } else if (e.key === "Escape") {
        const span = document.createElement("span");
        span.className = "section-name";
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
    document.querySelector(".context-menu")?.remove();

    // 添加新菜單
    document.body.insertAdjacentHTML("beforeend", menuHtml);

    // 點擊其他地方關閉菜單
    document.addEventListener(
      "click",
      () => {
        document.querySelector(".context-menu")?.remove();
      },
      { once: true },
    );
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
    document.getElementById("createSectionModal")?.remove();

    // 添加新 modal
    document.body.insertAdjacentHTML("beforeend", modalHtml);

    const modal = new bootstrap.Modal(
      document.getElementById("createSectionModal"),
    );
    modal.show();
  }

  /**
   * 取得 Section 選項列表
   */
  getSectionOptions() {
    const options = [];

    const flattenSections = (sections, level = 0) => {
      sections.forEach((section) => {
        const isUnassigned = this.isUnassignedSection(section);
        if (section.level < 5) {
          // 最多 5 層
          // 根據層級生成視覺符號
          let prefix = "";
          if (level > 0) {
            // 使用階層符號：| 表示連接，－ 表示層級
            prefix = "┣ ".repeat(level);
          }

          if (!isUnassigned) {
            options.push(
              `<option value="${section.id}">${prefix}${this.escapeHtml(section.name)}</option>`,
            );
          }
        }
        const children = this.getChildSections(section);
        if (children.length > 0) {
          flattenSections(this.sortSectionsForDisplay(children), level + 1);
        }
      });
    };

    flattenSections(this.sortSectionsForDisplay(this.sections));
    return options.join("");
  }

  /**
   * 建立 Section
   */
  async createSection() {
    const name = document.getElementById("sectionName").value.trim();
    const description = document
      .getElementById("sectionDescription")
      .value.trim();
    const parentId = document.getElementById("parentSection").value || null;

    if (!name) {
      alert("區段名稱不可空白");
      return;
    }

    // Unassigned 已不會出現在父區段選單，這裡不需再次檢查

    try {
      // 獲取 team_id 和當前 set_id
      const urlParams = new URLSearchParams(window.location.search);
      const teamId = urlParams.get("team_id");

      if (!teamId) {
        alert("無法取得團隊 ID");
        return;
      }

      const response = await window.AuthClient.fetch(
        `/api/test-case-sets/${this.setId}/sections`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            name,
            description: description || null,
            parent_section_id: parentId ? parseInt(parentId) : null,
            sort_order: 0,
          }),
        },
      );

      if (!response.ok) {
        let errorDetail = "Failed to create section";
        try {
          const errorData = await response.json();
          console.log("API Error response:", errorData);
          if (errorData.detail) {
            if (typeof errorData.detail === "string") {
              errorDetail = errorData.detail;
            } else if (Array.isArray(errorData.detail)) {
              errorDetail = errorData.detail
                .map((e) => (typeof e === "string" ? e : JSON.stringify(e)))
                .join("; ");
            } else {
              errorDetail = JSON.stringify(errorData.detail);
            }
          }
        } catch (e) {
          console.error("Failed to parse error response:", e);
        }
        throw new Error(errorDetail);
      }

      const modal = bootstrap.Modal.getInstance(
        document.getElementById("createSectionModal"),
      );
      if (modal) {
        modal.hide();
      }

      // 重新載入 Sections
      console.log("[SectionList] Section created, reloading sections...");
      await this.loadSections();
    } catch (error) {
      console.error("Error creating section:", error);
      alert("建立區段失敗: " + error.message);
    }
  }

  /**
   * 更新 Section
   */
  async updateSection(sectionId, newName) {
    try {
      const response = await window.AuthClient.fetch(
        `/api/test-case-sets/${this.setId}/sections/${sectionId}`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ name: newName }),
        },
      );

      if (!response.ok) {
        throw new Error("Failed to update section");
      }

      await this.loadSections({ reloadTestCases: true });
    } catch (error) {
      console.error("Error updating section:", error);
      alert("更新區段失敗: " + error.message);
    }
  }

  /**
   * 刪除 Section
   */
  async deleteSection(sectionId) {
    // 防止刪除 Unassigned Section
    const section = this.findSection(sectionId);
    if (section && section.name === "Unassigned") {
      alert('無法刪除系統區段 "Unassigned"');
      return;
    }

    if (
      !confirm("確定要刪除此區段嗎？該區段下的測試案例將被移到 Unassigned。")
    ) {
      return;
    }

    try {
      const response = await window.AuthClient.fetch(
        `/api/test-case-sets/${this.setId}/sections/${sectionId}`,
        {
          method: "DELETE",
        },
      );

      if (!response.ok) {
        throw new Error("Failed to delete section");
      }

      // 重新載入 Sections 並強制更新測試案例
      await this.loadSections({ reloadTestCases: true });
    } catch (error) {
      console.error("Error deleting section:", error);
      alert("刪除區段失敗: " + error.message);
    }
  }

  /**
   * 載入 Sections
   */
  async loadSections(options = {}) {
    if (!this.setId) return;
    const { reloadTestCases = false } = options || {};

    try {
      const response = await window.AuthClient.fetch(
        `/api/test-case-sets/${this.setId}/sections`,
        {
          method: "GET",
        },
      );

      if (!response.ok) {
        throw new Error("Failed to load sections");
      }

      this.sections = await response.json();
      if (reloadTestCases) {
        this.nextSectionEventMeta = { reloadTestCases: true };
      }
      this.render();
    } catch (error) {
      console.error("Error loading sections:", error);
      alert("載入區段失敗: " + error.message);
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
      const children = this.getChildSections(section);
      if (children.length > 0) {
        const found = this.findSection(sectionId, children);
        if (found) return found;
      }
    }
    return null;
  }

  isUnassignedSection(section) {
    if (!section || !section.name) return false;
    return section.name.trim().toLowerCase() === "unassigned";
  }

  getChildSections(section) {
    if (!section) return [];
    if (Array.isArray(section.child_sections)) return section.child_sections;
    if (Array.isArray(section.children)) return section.children;
    return [];
  }

  sortSectionsForDisplay(sections) {
    if (!Array.isArray(sections)) return [];

    const comparator = (a, b) => {
      const aOrder = Number.isFinite(a?.sort_order) ? a.sort_order : 0;
      const bOrder = Number.isFinite(b?.sort_order) ? b.sort_order : 0;
      if (aOrder !== bOrder) {
        return aOrder - bOrder;
      }
      const aName = (a?.name || "").toLowerCase();
      const bName = (b?.name || "").toLowerCase();
      return aName.localeCompare(bName);
    };

    const normal = [];
    const unassigned = [];
    sections.forEach((section) => {
      if (!section) return;
      if (this.isUnassignedSection(section)) {
        unassigned.push(section);
      } else {
        normal.push(section);
      }
    });

    normal.sort(comparator);
    unassigned.sort(comparator);
    return normal.concat(unassigned);
  }

  getSiblingIds(parentId) {
    const normalized = this.normalizeParentId(parentId);
    if (normalized === null) {
      return Array.isArray(this.sections) ? this.sections.map((s) => s.id) : [];
    }
    const parent = this.findSection(normalized);
    if (parent && Array.isArray(parent.child_sections)) {
      return parent.child_sections.map((s) => s.id);
    }
    return [];
  }

  normalizeParentId(value) {
    if (value === undefined || value === null || value === "" || value === "null") {
      return null;
    }
    const parsed = Number(value);
    return Number.isNaN(parsed) ? null : parsed;
  }

  findSectionWithParent(sectionId, sections = this.sections, parentId = null) {
    for (const section of sections || []) {
      if (section.id == sectionId) {
        return { section, parentId };
      }
      if (section.child_sections && section.child_sections.length > 0) {
        const result = this.findSectionWithParent(sectionId, section.child_sections, section.id);
        if (result) return result;
      }
    }
    return null;
  }

  sectionContainsDescendant(sectionId, possibleDescId) {
    if (possibleDescId === null || possibleDescId === undefined) return false;
    if (sectionId === possibleDescId) return true;
    const section = this.findSection(sectionId);
    if (!section || !Array.isArray(section.child_sections)) return false;
    for (const child of section.child_sections) {
      if (child.id === possibleDescId) return true;
      if (this.sectionContainsDescendant(child.id, possibleDescId)) return true;
    }
    return false;
  }

  async saveSectionOrderPayload(entries) {
    if (!entries || !entries.length) return false;
    try {
      const payload = entries.map((entry) => ({
        id: entry.id,
        sort_order: entry.sort_order,
        parent_section_id:
          entry.parent_section_id === undefined || entry.parent_section_id === null
            ? null
            : entry.parent_section_id,
      }));

      const response = await window.AuthClient.fetch(
        `/api/test-case-sets/${this.setId}/sections/reorder`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sections: payload }),
        },
      );

      if (!response.ok) {
        console.error("Failed to save section order:", response.statusText);
        return false;
      }
      return true;
    } catch (error) {
      console.error("Error saving section order:", error);
      return false;
    }
  }

  clearDropIndicators() {
    document.querySelectorAll(".section-node").forEach((node) => {
      node.style.borderTop = "";
      node.style.borderBottom = "";
      node.style.backgroundColor = "";
    });
  }

  /**
   * 動態調整內容區域高度以適應視口（現在由 CSS flexbox 自動處理）
   */
  adjustPanelHeight() {
    // 高度分配現在完全由 CSS flexbox 處理
    // 這個方法保留用於日誌和未來可能的調整
    console.log("[SectionList] Panel layout adjusted by CSS flexbox");
  }

  /**
   * 切換側邊欄
   */
  togglePanel() {
    const content = document.getElementById("sectionListContent");
    if (content) {
      const isVisible = content.style.display !== "none";
      content.style.display = isVisible ? "none" : "block";
    }
  }

  /**
   * HTML 轉義
   */
  escapeHtml(text) {
    const map = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    };
    return text.replace(/[&<>"']/g, (m) => map[m]);
  }

  /**
   * 顯示編輯順序 Modal
   */
  showReorderModal() {
    if (!this.setId) {
      alert('請先選擇一個 Test Case Set');
      return;
    }

    // 創建扁平化的 section 列表（包含層級資訊）
    this.flatSections = this.flattenSections(this.sections);
    
    // 創建 modal HTML
    const modalHtml = `
      <div class="modal fade" id="reorderSectionModal" tabindex="-1" aria-labelledby="reorderSectionModalLabel" aria-hidden="true">
        <div class="modal-dialog modal-lg">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title" id="reorderSectionModalLabel">
                <i class="fas fa-arrows-up-down"></i> 編輯區段順序與層級
              </h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body">
              <div class="alert alert-info">
                <i class="fas fa-info-circle"></i> 
                <strong>操作說明：</strong>
                <ul class="mb-0 mt-2" style="font-size: 0.9em;">
                  <li><strong>上/下按鈕</strong>：同層移動，與前/後兄弟節點交換位置</li>
                  <li><strong>← 左按鈕</strong>：減少層級（反縮排），從父節點取出並與父節點同層</li>
                  <li><strong>→ 右按鈕</strong>：增加層級（縮排），成為視覺上相鄰的上一個同層或淺層節點的子節點</li>
                  <li><strong>注意</strong>：所有操作都會連同子樹一起移動，最多支援 5 層</li>
                </ul>
              </div>
              <div id="reorderSectionList" class="list-group">
                ${this.renderReorderList()}
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
              <button type="button" class="btn btn-primary" onclick="testCaseSectionList.saveReorder()">
                <i class="fas fa-save"></i> 儲存變更
              </button>
            </div>
          </div>
        </div>
      </div>
    `;

    // 移除舊的 modal（如果存在）
    const oldModal = document.getElementById('reorderSectionModal');
    if (oldModal) {
      oldModal.remove();
    }

    // 添加新的 modal
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // 顯示 modal
    const modal = new bootstrap.Modal(document.getElementById('reorderSectionModal'));
    modal.show();
  }

  /**
   * 扁平化 sections 為列表（保留層級資訊）
   */
  flattenSections(sections, level = 1, parentId = null, result = []) {
    const sorted = this.sortSectionsForDisplay(sections);
    
    for (const section of sorted) {
      // 跳過 Unassigned（系統區段）
      if (this.isUnassignedSection(section)) {
        continue;
      }

      result.push({
        id: section.id,
        name: section.name,
        level: level,
        parent_section_id: parentId,
        sort_order: section.sort_order || 0,
        test_case_count: section.test_case_count || 0
      });

      // 遞迴處理子節點
      const children = this.getChildSections(section);
      if (children && children.length > 0) {
        this.flattenSections(children, level + 1, section.id, result);
      }
    }

    return result;
  }

  /**
   * 渲染可重新排序的列表
   */
  renderReorderList() {
    if (!this.flatSections || this.flatSections.length === 0) {
      return '<div class="text-muted text-center py-3">沒有可編輯的區段</div>';
    }

    return this.flatSections.map((section, index) => {
      const indent = (section.level - 1) * 20;
      
      // 檢查是否可以向上移動（同層）
      const canMoveUp = this.canMoveUp(index);
      
      // 檢查是否可以向下移動（同層）
      const canMoveDown = this.canMoveDown(index);
      
      // 檢查是否可以減少層級（左移）
      const canDecreaseLevel = section.level > 1;
      
      // 檢查是否可以增加層級（右移）- 使用新的檢查方法
      const canIncreaseLevel = this.canIncreaseLevel(index);
      
      return `
        <div class="list-group-item d-flex align-items-center py-2" data-section-index="${index}">
          <div style="margin-left: ${indent}px; flex: 1;">
            <i class="fas fa-folder text-muted me-2"></i>
            <strong>${this.escapeHtml(section.name)}</strong>
            <span class="badge bg-secondary ms-2">${section.test_case_count}</span>
            <small class="text-muted ms-2">(層級 ${section.level})</small>
          </div>
          <div class="btn-group btn-group-sm ms-2" role="group">
            <button type="button" class="btn btn-outline-primary" 
                    onclick="testCaseSectionList.moveUp(${index})" 
                    ${!canMoveUp ? 'disabled' : ''} 
                    title="向上移動（同層）">
              <i class="fas fa-chevron-up"></i>
            </button>
            <button type="button" class="btn btn-outline-primary" 
                    onclick="testCaseSectionList.moveDown(${index})" 
                    ${!canMoveDown ? 'disabled' : ''} 
                    title="向下移動（同層）">
              <i class="fas fa-chevron-down"></i>
            </button>
            <button type="button" class="btn btn-outline-secondary" 
                    onclick="testCaseSectionList.decreaseLevel(${index})" 
                    ${!canDecreaseLevel ? 'disabled' : ''} 
                    title="減少層級（反縮排）">
              <i class="fas fa-arrow-left"></i>
            </button>
            <button type="button" class="btn btn-outline-secondary" 
                    onclick="testCaseSectionList.increaseLevel(${index})" 
                    ${!canIncreaseLevel ? 'disabled' : ''} 
                    title="增加層級（縮排）">
              <i class="fas fa-arrow-right"></i>
            </button>
          </div>
        </div>
      `;
    }).join('');
  }

  /**
   * 檢查是否可以向上移動
   */
  canMoveUp(index) {
    const section = this.flatSections[index];
    const currentLevel = section.level;
    
    // 向上找第一個同層級的兄弟節點
    for (let i = index - 1; i >= 0; i--) {
      if (this.flatSections[i].level === currentLevel) {
        return true;
      }
      if (this.flatSections[i].level < currentLevel) {
        // 遇到父節點或更上層，停止
        break;
      }
    }
    
    return false;
  }

  /**
   * 檢查是否可以向下移動
   */
  canMoveDown(index) {
    const section = this.flatSections[index];
    const currentLevel = section.level;
    const subtree = this.getSubtree(index);
    const subtreeEnd = index + subtree.length;
    
    // 向下找第一個同層級的兄弟節點
    for (let i = subtreeEnd; i < this.flatSections.length; i++) {
      if (this.flatSections[i].level === currentLevel) {
        return true;
      }
      if (this.flatSections[i].level < currentLevel) {
        // 遇到更上層，停止
        break;
      }
    }
    
    return false;
  }

  /**
   * 檢查是否可以增加層級
   * 規則：向上找到第一個層級 <= 當前層級的節點作為父節點
   */
  canIncreaseLevel(index) {
    const section = this.flatSections[index];
    
    // 已達最大層級
    if (section.level >= 5) {
      return false;
    }
    
    // 沒有前一個節點
    if (index === 0) {
      return false;
    }
    
    // 向上尋找可掛接的父節點（層級 <= 當前層級的第一個節點）
    for (let i = index - 1; i >= 0; i--) {
      const node = this.flatSections[i];
      
      if (node.level <= section.level) {
        // 找到了可掛接的父節點
        const newLevel = node.level + 1;
        
        // 檢查新層級是否超過限制
        if (newLevel > 5) {
          return false;
        }
        
        return true;
      }
    }
    
    // 沒有找到可掛接的父節點
    return false;
  }

  /**
   * 向上移動（同層）
   * 規則：與前一個兄弟節點交換位置，若沒有前一個兄弟節點則無效
   */
  moveUp(index) {
    const section = this.flatSections[index];
    const currentLevel = section.level;
    
    // 向上找第一個同層級的兄弟節點
    let prevSiblingIndex = -1;
    for (let i = index - 1; i >= 0; i--) {
      if (this.flatSections[i].level === currentLevel) {
        prevSiblingIndex = i;
        break;
      }
      if (this.flatSections[i].level < currentLevel) {
        // 已經超出同層範圍（遇到父節點或更上層）
        break;
      }
    }

    if (prevSiblingIndex === -1) {
      console.log('[SectionList] 無法向上移動：沒有前一個兄弟節點');
      return;
    }

    // 獲取當前節點和前一個兄弟節點的子樹
    const currentSubtree = this.getSubtree(index);
    const prevSubtree = this.getSubtree(prevSiblingIndex);

    // 交換兩個子樹的位置
    this.swapSubtrees(prevSiblingIndex, index);

    // 重新渲染
    this.updateReorderList();
  }

  /**
   * 向下移動（同層）
   * 規則：與下一個兄弟節點交換位置，若沒有下一個兄弟節點則無效
   */
  moveDown(index) {
    const section = this.flatSections[index];
    const currentLevel = section.level;
    const subtree = this.getSubtree(index);
    const subtreeEnd = index + subtree.length;
    
    // 向下找第一個同層級的兄弟節點
    let nextSiblingIndex = -1;
    for (let i = subtreeEnd; i < this.flatSections.length; i++) {
      if (this.flatSections[i].level === currentLevel) {
        nextSiblingIndex = i;
        break;
      }
      if (this.flatSections[i].level < currentLevel) {
        // 已經超出同層範圍
        break;
      }
    }

    if (nextSiblingIndex === -1) {
      console.log('[SectionList] 無法向下移動：沒有下一個兄弟節點');
      return;
    }

    // 獲取下一個兄弟節點的子樹
    const nextSubtree = this.getSubtree(nextSiblingIndex);

    // 交換兩個子樹的位置
    this.swapSubtrees(index, nextSiblingIndex);

    // 重新渲染
    this.updateReorderList();
  }

  /**
   * 減少層級（向左移動，反縮排）
   * 規則：若有父節點，則從父節點取出，插入到父節點的下一個位置（與父同層）
   */
  decreaseLevel(index) {
    const section = this.flatSections[index];
    
    // 已是層級 1（根層），無法再減少
    if (section.level <= 1) {
      console.log('[SectionList] 無法減少層級：已經是根層');
      return;
    }

    // 找到父節點
    let parentIndex = -1;
    for (let i = index - 1; i >= 0; i--) {
      if (this.flatSections[i].level === section.level - 1) {
        parentIndex = i;
        break;
      }
    }

    if (parentIndex === -1) {
      console.log('[SectionList] 無法減少層級：找不到父節點');
      return;
    }

    // 獲取當前節點的子樹
    const subtree = this.getSubtree(index);
    
    // 減少整個子樹的層級
    subtree.forEach(node => {
      node.level--;
    });

    // 找到父節點的子樹結束位置（即父節點的下一個兄弟節點前）
    const parentSubtree = this.getSubtree(parentIndex);
    const insertPosition = parentIndex + parentSubtree.length;

    // 移除當前子樹
    this.flatSections.splice(index, subtree.length);

    // 插入到新位置
    const adjustedInsertPos = insertPosition > index ? insertPosition - subtree.length : insertPosition;
    this.flatSections.splice(adjustedInsertPos, 0, ...subtree);

    // 重新渲染
    this.updateReorderList();
  }

  /**
   * 增加層級（向右移動，縮排）
   * 規則：成為相鄰上一個節點（視覺順序）的最上層 section 的子節點
   * 例如：
   * 111
   *   |- 222
   *       |- 333
   * 444  <- 按右移會成為 111 的子節點
   */
  increaseLevel(index) {
    const section = this.flatSections[index];
    
    // 已是層級 5，無法再增加
    if (section.level >= 5) {
      console.log('[SectionList] 無法增加層級：已達最大層級 5');
      return;
    }

    // 沒有前一個節點
    if (index === 0) {
      console.log('[SectionList] 無法增加層級：沒有前一個節點');
      return;
    }

    // 向上尋找相鄰的上一個節點的最上層 section
    // 跳過所有比當前節點深的節點，找到第一個層級 <= 當前層級的節點
    let targetParentIndex = -1;
    let targetParent = null;
    
    for (let i = index - 1; i >= 0; i--) {
      const node = this.flatSections[i];
      
      // 找到第一個層級 <= 當前層級的節點（這是視覺上相鄰的上一個section）
      if (node.level <= section.level) {
        // 這個節點就是我們要掛接的父節點
        targetParentIndex = i;
        targetParent = node;
        break;
      }
    }
    
    if (!targetParent) {
      console.log('[SectionList] 無法增加層級：找不到可掛接的父節點');
      alert('無法增加層級：找不到可掛接的父節點');
      return;
    }
    
    // 計算新層級：父節點層級 + 1
    const newLevel = targetParent.level + 1;
    
    // 檢查新層級是否超過限制
    if (newLevel > 5) {
      console.log('[SectionList] 無法增加層級：超過最大層級 5');
      alert('無法增加層級：超過最大層級 5');
      return;
    }

    // 獲取當前節點的子樹
    const subtree = this.getSubtree(index);
    
    // 計算層級差異
    const levelDelta = newLevel - section.level;
    
    // 調整整個子樹的層級
    subtree.forEach(node => {
      node.level += levelDelta;
    });

    // 設置新的父節點
    section.parent_section_id = targetParent.id;

    console.log(`[SectionList] 成功增加層級: ${section.name} (層級 ${section.level - levelDelta} -> ${section.level}) 成為 ${targetParent.name} 的子節點`);

    // 重新渲染
    this.updateReorderList();
  }

  /**
   * 獲取節點的子樹（包括節點本身和所有後代）
   */
  getSubtree(index) {
    const subtree = [];
    const rootLevel = this.flatSections[index].level;
    
    // 加入根節點
    subtree.push(this.flatSections[index]);
    
    // 加入所有子節點（層級大於根節點的連續節點）
    for (let i = index + 1; i < this.flatSections.length; i++) {
      if (this.flatSections[i].level <= rootLevel) {
        // 遇到同層或更淺層，子樹結束
        break;
      }
      subtree.push(this.flatSections[i]);
    }
    
    return subtree;
  }

  /**
   * 交換兩個子樹的位置
   */
  swapSubtrees(index1, index2) {
    const subtree1 = this.getSubtree(index1);
    const subtree2 = this.getSubtree(index2);
    
    // 確保 index1 < index2
    if (index1 > index2) {
      return this.swapSubtrees(index2, index1);
    }
    
    // 移除兩個子樹
    const removed2 = this.flatSections.splice(index2, subtree2.length);
    const removed1 = this.flatSections.splice(index1, subtree1.length);
    
    // 按新順序插入
    this.flatSections.splice(index1, 0, ...removed2);
    this.flatSections.splice(index1 + removed2.length, 0, ...removed1);
  }

  /**
   * 更新重新排序列表顯示
   */
  updateReorderList() {
    const listContainer = document.getElementById('reorderSectionList');
    if (listContainer) {
      listContainer.innerHTML = this.renderReorderList();
    }
  }

  /**
   * 儲存重新排序結果
   */
  async saveReorder() {
    try {
      // 重建 parent_section_id 關係
      const payload = [];
      
      for (let i = 0; i < this.flatSections.length; i++) {
        const section = this.flatSections[i];
        
        // 尋找正確的 parent_section_id
        let parentId = null;
        if (section.level > 1) {
          // 向上找第一個層級比自己少1的作為父節點
          for (let j = i - 1; j >= 0; j--) {
            if (this.flatSections[j].level === section.level - 1) {
              parentId = this.flatSections[j].id;
              break;
            }
          }
        }

        payload.push({
          id: section.id,
          sort_order: i,
          parent_section_id: parentId
        });
      }

      console.log('[SectionList] Saving reorder with payload:', payload);

      const response = await window.AuthClient.fetch(
        `/api/test-case-sets/${this.setId}/sections/reorder`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sections: payload })
        }
      );

      if (!response.ok) {
        throw new Error('Failed to save section order');
      }

      // 關閉 modal
      const modal = bootstrap.Modal.getInstance(document.getElementById('reorderSectionModal'));
      if (modal) {
        modal.hide();
      }

      // 重新載入 sections
      await this.loadSections({ reloadTestCases: true });
    } catch (error) {
      console.error('Error saving section order:', error);
      alert('儲存失敗: ' + error.message);
    }
  }
}

// 建立全域實例
const testCaseSectionList = new TestCaseSectionList();

// 在 DOM 準備好後初始化
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    testCaseSectionList.init();
  });
}
