function tt(key, fb) {
  try {
    if (window.i18n && window.i18n.isReady && window.i18n.isReady()) {
      const v = window.i18n.t(key);
      if (v && v !== key) return v;
    }
  } catch (_) {}
  return fb;
}

document.addEventListener("DOMContentLoaded", async () => {
  const { Handsontable } = window;
  if (!Handsontable) {
    console.error("Handsontable not loaded");
    return;
  }

  const pathParts = window.location.pathname.split("/");
  const runId = pathParts[pathParts.indexOf("adhoc-runs") + 1];

  const dom = {
    runName: document.getElementById("runNameDisplay"),
    sheetTabs: document.getElementById("sheetTabsContainer"),
    addSheet: document.getElementById("addSheetBtn"),
    addRow: document.getElementById("addRowBtn"),
    saveStatus: document.getElementById("saveStatus"),
    backBtn: document.getElementById("backToMgmtBtn"),
    gridHost: document.getElementById("adhocGrid"),
  };

  let hot = null;
  let currentRun = null;
  let currentSheetId = null;
  let autoSaveTimer = null;
  let assigneeOptions = [];
  let deletedItemIds = new Set();
  let isSaving = false;
  let isPendingSave = false;
  let isRunReadOnly = false;
  let currentSheetItems = [];

  const PRIORITY = ["High", "Medium", "Low"];
  const RESULT = [
    "",
    "Passed",
    "Failed",
    "Retest",
    "Not Available",
    "Pending",
    "Not Required",
  ];

      function defaultColoredRenderer(instance, td, row, col, prop, value, cellProperties) {
          Handsontable.renderers.TextRenderer.apply(this, arguments);
          applyCommonStyles(instance, td, row, col, prop, value);
      }
  
      const buildColumns = () => {    const hasAssignees = assigneeOptions.length > 0;
    const assigneeSource = hasAssignees
      ? function (_query, process) {
          process(Array.isArray(assigneeOptions) ? assigneeOptions : []);
        }
      : undefined;
        return [
            { data: 'test_case_number', title: 'Test Case Number', width: 220, wordWrap: true, renderer: defaultColoredRenderer },
            { data: 'title', title: 'Title', width: 260, wordWrap: true, renderer: defaultColoredRenderer },
            { data: 'precondition', title: 'Precondition', width: 220, wordWrap: true, renderer: defaultColoredRenderer },
            { data: 'steps', title: 'Steps', width: 240, wordWrap: true, renderer: defaultColoredRenderer },
            { data: 'expected_result', title: 'Expected Result', width: 240, wordWrap: true, renderer: defaultColoredRenderer },
            { data: 'jira_tickets', title: 'JIRA Tickets', width: 200, wordWrap: true, renderer: defaultColoredRenderer },
            { data: 'priority', title: 'Priority', width: 110, type: 'dropdown', source: PRIORITY, renderer: priorityRenderer, wordWrap: true },
            { data: 'test_result', title: 'Result', width: 140, type: 'dropdown', source: RESULT, renderer: resultRenderer, wordWrap: true },
            hasAssignees
                ? { data: 'assignee_name', title: 'Assignee', width: 180, type: 'dropdown', source: assigneeSource, strict: false, allowInvalid: true, trimDropdown: false, renderer: defaultColoredRenderer, wordWrap: true }
                : { data: 'assignee_name', title: 'Assignee', width: 180, type: 'text', renderer: defaultColoredRenderer, wordWrap: true },
            { data: 'comments', title: 'Comments', width: 220, wordWrap: true, renderer: defaultColoredRenderer },
            { data: 'bug_list', title: 'Bug List', width: 180, wordWrap: true, renderer: defaultColoredRenderer }
        ];
  };

  // Move listeners to bottom or after definitions
  // ... definitions ...

  // Helper function to setup listeners
  function setupListeners() {
    dom.addSheet?.addEventListener("click", onAddSheet);
    dom.addRow?.addEventListener("click", onAddRow);
    
    const rerunBtn = document.getElementById("rerunBtn");
    if (rerunBtn) {
        rerunBtn.addEventListener("click", handleRerun);
    }

    const convertBtn = document.getElementById("convertBtn");
    if (convertBtn) {
        convertBtn.addEventListener("click", handleConvert);
    }

    const reportsBtn = document.getElementById("reportsBtn");
    if (reportsBtn) {
      reportsBtn.addEventListener("click", () => {
        console.info("Opening Ad-hoc Charts & Reports");
        openReports();
      });
    } else {
      console.warn("reportsBtn not found");
    }
    const exportHtmlBtn = document.getElementById("exportHtmlBtn");
    if (exportHtmlBtn) {
      exportHtmlBtn.addEventListener("click", exportHtmlReport);
    }
  }

  function applyReadOnlyMode(readOnly) {
    const addSectionBtn = document.getElementById("addSectionBtn");
    [dom.addRow, addSectionBtn, dom.addSheet].forEach((btn) => {
      if (!btn) return;
      btn.disabled = !!readOnly;
      btn.classList.toggle("disabled", !!readOnly);
    });

    // Sheets: hide rename/delete for read-only
    const sheetTools = document.querySelectorAll(".sheet-tab .btn");
    sheetTools.forEach((btn) => {
      btn.disabled = !!readOnly;
      btn.classList.toggle("disabled", !!readOnly);
    });

    if (dom.saveStatus) {
      if (readOnly) {
        dom.saveStatus.textContent = tt("adhoc.readonly", "Read-only (archived)");
        dom.saveStatus.className = "text-muted small";
      } else {
        dom.saveStatus.textContent = "";
        dom.saveStatus.className = "";
      }
    }
  }

      // ... (rest of the file) ...

      await loadRun();
      await loadAssignees();
      setupListeners(); // Call it here
  
      function showConfirmModal({ title, message, confirmText, confirmClass, type = 'danger', onConfirm }) {
          let modalEl = document.getElementById('adhocExecutionConfirmModal');
          
          let headerClass = 'bg-light';
          let closeBtnClass = '';
          let iconClass = 'text-secondary';
          let iconName = 'fa-question-circle';
          let alertClass = 'alert-secondary';
  
          if (type === 'danger') {
              headerClass = 'bg-danger text-white';
              closeBtnClass = 'btn-close-white';
              iconName = 'fa-exclamation-triangle';
              alertClass = 'alert-danger';
          } else if (type === 'info') {
              headerClass = 'bg-info text-white';
              closeBtnClass = 'btn-close-white';
              iconName = 'fa-info-circle';
              alertClass = 'alert-info';
          }
  
          if (!modalEl) {
              const div = document.createElement('div');
              div.innerHTML = `
              <div class="modal fade" id="adhocExecutionConfirmModal" tabindex="-1" style="z-index: 1060;">
                  <div class="modal-dialog modal-dialog-centered">
                      <div class="modal-content">
                          <div class="modal-header">
                              <h5 class="modal-title d-flex align-items-center">
                                  <i class="fas me-2"></i>
                                  <span id="execConfirmTitle"></span>
                              </h5>
                              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                          </div>
                          <div class="modal-body">
                              <div class="alert mb-0 d-flex align-items-center">
                                  <i class="fas fa-exclamation-circle me-2"></i>
                                  <span id="execConfirmMessage"></span>
                              </div>
                          </div>
                          <div class="modal-footer">
                              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                              <button type="button" class="btn" id="execConfirmBtn"></button>
                          </div>
                      </div>
                  </div>
              </div>`;
              document.body.appendChild(div.firstElementChild);
              modalEl = document.getElementById('adhocExecutionConfirmModal');
          }
  
          const content = modalEl.querySelector('.modal-content');
          content.className = `modal-content border-${type === 'danger' ? 'danger' : (type === 'info' ? 'info' : 'secondary')}`;
          
          const header = modalEl.querySelector('.modal-header');
          header.className = `modal-header ${headerClass}`;
          
          const icon = header.querySelector('i');
          icon.className = `fas ${iconName} me-2 ${iconClass}`;
          
          const closeBtn = header.querySelector('.btn-close');
          closeBtn.className = `btn-close ${closeBtnClass}`;
  
          const alertBox = modalEl.querySelector('.alert');
          alertBox.className = `alert ${alertClass} mb-0 d-flex align-items-center`;
          
          document.getElementById('execConfirmTitle').textContent = title;
          document.getElementById('execConfirmMessage').textContent = message;
          
          const btn = document.getElementById('execConfirmBtn');
          btn.textContent = confirmText;
          btn.className = `btn ${confirmClass}`;
          
          const newBtn = btn.cloneNode(true);
          btn.parentNode.replaceChild(newBtn, btn);
          
          newBtn.onclick = () => {
              onConfirm();
              const modalInstance = bootstrap.Modal.getInstance(modalEl);
              if (modalInstance) modalInstance.hide();
          };
          
          const modal = new bootstrap.Modal(modalEl);
          modal.show();
      }
  
          async function handleRerun() {
  
              showConfirmModal({
  
                  title: tt('common.confirm', 'Confirm'),
  
                  message: tt('adhoc.rerunConfirm', 'Re-run this Ad-hoc run? This will create a new active copy.'),
  
                  confirmText: tt('adhoc.rerun', 'Re-run'),
  
                  confirmClass: 'btn-info',
  
                  type: 'info',
  
                  onConfirm: async () => {
  
                      try {
  
                          const resp = await window.AuthClient.fetch(`/api/adhoc-runs/${runId}/rerun`, { method: 'POST' });
  
                          if (resp.ok) {
  
                              const newRun = await resp.json();
  
                              window.location.href = `/adhoc-runs/${newRun.id}/execution`;
  
                          } else {
  
                              alert(tt('adhoc.rerunFailed','Failed to re-run'));
  
                          }
  
                      } catch (e) {
  
                          console.error(e);
  
                          alert(tt('adhoc.rerunFailed','Failed to re-run'));
  
                      }
  
                  }
  
              });
  
          }
  
      
  
          async function handleConvert() {
              openConvertModal();
          }
  
      
  
          async function loadRun() {    try {
      const resp = await window.AuthClient.fetch(`/api/adhoc-runs/${runId}`);
      if (!resp.ok)
        throw new Error(tt("adhoc.loadFailed", "Failed to load run"));
      currentRun = await resp.json();

      const runName = currentRun.name || `Ad-hoc Run ${runId}`;
      if (dom.runName) {
        dom.runName.textContent = runName;
        dom.runName.removeAttribute("data-i18n");
      }
      
      const rerunBtn = document.getElementById('rerunBtn');
      const statusLower = (currentRun.status || "").toLowerCase();
      if (rerunBtn) {
          if (statusLower === 'completed') {
              rerunBtn.classList.remove('d-none');
          } else {
              rerunBtn.classList.add('d-none');
          }
      }

      document.title = `${runName} - Ad-hoc Test Run`;
      if (currentRun.team_id && dom.backBtn) {
        dom.backBtn.href = `/test-run-management?team_id=${currentRun.team_id}`;
      }

      // Handle case where no sheets exist after deletion
      if (!currentRun.sheets || currentRun.sheets.length === 0) {
        currentRun.sheets = [];
        if (hot) {
          hot.destroy();
          hot = null;
          dom.gridHost.innerHTML =
            '<div class="text-center mt-5 text-muted">No sheets. Click "+" to add one.</div>';
        }
        dom.sheetTabs.innerHTML = "";
        return;
      }

      isRunReadOnly = statusLower === "archived" || statusLower === "completed";
      applyReadOnlyMode(isRunReadOnly);

      renderTabs();
      const firstSheetId = currentRun.sheets[0].id;
      // If currentSheetId is invalid (e.g. deleted), switch to first
      const targetSheet =
        currentSheetId && currentRun.sheets.find((s) => s.id == currentSheetId)
          ? currentSheetId
          : firstSheetId;

      if (targetSheet) {
        switchToSheet(targetSheet);
      }
    } catch (e) {
      console.error(e);
      if (dom.runName) {
        dom.runName.textContent = "Load failed";
        dom.runName.removeAttribute("data-i18n");
      }
    }
  }

  function renderTabs() {
    if (!dom.sheetTabs) return;
    dom.sheetTabs.innerHTML = "";
    if (!currentRun?.sheets) return;
    currentRun.sheets.sort((a, b) => a.sort_order - b.sort_order);

    currentRun.sheets.forEach((sheet) => {
      const tab = document.createElement("div");
      tab.className = `sheet-tab ${sheet.id == currentSheetId ? "active" : ""}`;
      tab.style.position = "relative";

      const name = document.createElement("span");
      name.className = "tab-name";
      name.textContent = sheet.name;

      // Container for buttons
      const btnContainer = document.createElement("span");
      btnContainer.className = "ms-2 d-flex align-items-center";

      const rename = document.createElement("button");
      rename.className = "btn btn-link btn-sm p-0 text-secondary";
      rename.innerHTML = '<i class="fas fa-edit"></i>';
      rename.title = "Rename sheet";
      rename.style.fontSize = "0.85rem";
      rename.style.lineHeight = "1";
      if (isRunReadOnly) {
        rename.disabled = true;
        rename.classList.add("disabled");
      }

      const delBtn = document.createElement("button");
      delBtn.className = "btn btn-link btn-sm p-0 ms-2 text-danger";
      delBtn.innerHTML = '<i class="fas fa-trash-alt"></i>';
      delBtn.title = "Delete sheet";
      delBtn.style.fontSize = "0.85rem";
      delBtn.style.lineHeight = "1";
      if (isRunReadOnly) {
        delBtn.disabled = true;
        delBtn.classList.add("disabled");
      }

      const startRename = () => {
        if (isRunReadOnly) return;
        if (tab.dataset.editing === "true") return;
        tab.dataset.editing = "true";
        const tabWidth = tab.getBoundingClientRect().width;
        const tabHeight = tab.getBoundingClientRect().height;

        tab.style.width = `${tabWidth}px`;
        tab.style.minWidth = `${tabWidth}px`;

        // Hide content with visibility to keep size
        name.style.visibility = "hidden";
        btnContainer.style.visibility = "hidden";

        const input = document.createElement("input");
        input.type = "text";
        input.className = "form-control form-control-sm";
        input.value = sheet.name;

        // Absolute positioning to cover the tab
        input.style.position = "absolute";
        input.style.left = "0";
        input.style.top = "0";
        input.style.width = "100%";
        input.style.height = "100%";
        input.style.padding = "0 6px";
        input.style.fontSize = "13px";
        input.style.lineHeight = "1.2";
        input.style.boxSizing = "border-box";
        input.style.borderRadius = "6px 6px 0 0"; // Match tab border radius
        input.style.zIndex = "10";

        tab.appendChild(input);
        input.focus();
        input.select();

        const commit = async () => {
          tab.dataset.editing = "false";
          if (input.parentNode === tab) tab.removeChild(input);
          tab.style.width = "";
          tab.style.minWidth = "";
          name.style.visibility = "";
          btnContainer.style.visibility = "";

          const newName = input.value.trim();
          if (!newName || newName === sheet.name) {
            name.textContent = sheet.name;
            return;
          }
          name.textContent = newName;
          await renameSheet(sheet.id, newName);
        };

        const cancel = () => {
          tab.dataset.editing = "false";
          if (input.parentNode === tab) tab.removeChild(input);
          tab.style.width = "";
          tab.style.minWidth = "";
          name.style.visibility = "";
          btnContainer.style.visibility = "";
        };

        input.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          }
          if (e.key === "Escape") {
            e.preventDefault();
            cancel();
          }
        });
        input.addEventListener("blur", commit);
      };

      tab.addEventListener("click", (e) => {
        // Prevent switching if clicking input or during edit
        if (tab.dataset.editing === "true" && e.target.tagName === "INPUT")
          return;
        if (tab.dataset.editing === "true") return;
        switchToSheet(sheet.id);
      });

      name.addEventListener("dblclick", (e) => {
        e.stopPropagation();
        if (isRunReadOnly) return;
        startRename();
      });
      rename.addEventListener("click", (e) => {
        e.stopPropagation();
        if (isRunReadOnly) return;
        startRename();
      });

      delBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (isRunReadOnly) return;
        if (
          confirm(
            tt(
              "adhoc.confirmDeleteSheet",
              "Are you sure you want to delete this sheet?",
            ),
          )
        ) {
          await deleteSheet(sheet.id);
        }
      });

      btnContainer.appendChild(rename);
      btnContainer.appendChild(delBtn);
      tab.appendChild(name);
      tab.appendChild(btnContainer);
      dom.sheetTabs.appendChild(tab);
    });
    if (isRunReadOnly) applyReadOnlyMode(true);
  }

  async function deleteSheet(id) {
    if (isRunReadOnly) return;
    try {
      const resp = await window.AuthClient.fetch(
        `/api/adhoc-runs/${runId}/sheets/${id}`,
        {
          method: "DELETE",
        },
      );
      if (resp.ok) {
        // If we deleted the current sheet, set ID to null so loadRun picks a new one
        if (currentSheetId == id) {
          currentSheetId = null;
        }
        await loadRun();
      } else {
        alert("Delete failed");
      }
    } catch (e) {
      console.error(e);
      alert("Delete error");
    }
  }

  async function renameSheet(id, name) {
    if (isRunReadOnly) return;
    try {
      const resp = await window.AuthClient.fetch(
        `/api/adhoc-runs/${runId}/sheets/${id}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }),
        },
      );
      if (resp.ok) {
        await loadRun();
        switchToSheet(id);
      } else {
        alert("Rename failed");
      }
    } catch (e) {
      console.error(e);
      alert("Rename error");
    }
  }

  function switchToSheet(sheetId) {
    currentSheetId = sheetId;
    renderTabs();
    loadSheetItems(sheetId);
  }

  async function loadSheetItems(sheetId) {
    const sheet = currentRun?.sheets?.find((s) => s.id == sheetId);
    if (!sheet) return;
    const items = (sheet.items || [])
      .slice()
      .sort((a, b) => a.row_index - b.row_index);
    currentSheetItems = items.map((i) => ({ ...i }));
    const rows = items.map(convertItemToRow);
    initHot(rows);
  }

  function convertItemToRow(item) {
    const isSection =
      (item?.test_case_number || "").trim().toUpperCase() === "SECTION";
    return {
      id: item?.id || null,
      test_case_number: item?.test_case_number || "",
      title: item?.title || "",
      priority: isSection ? "" : item?.priority || "Medium",
            precondition: item?.precondition || '',
            steps: item?.steps || '',
            expected_result: item?.expected_result || '',
            jira_tickets: item?.jira_tickets || '',
            test_result: item?.test_result || '',
            assignee_name: item?.assignee_name || '',
      comments: item?.comments || "",
      bug_list: item?.bug_list || "",
      meta_json: item?.meta_json || "{}",
    };
  }

  function setRowDataFromColumns(rowIndex, rowData) {
    if (!hot) return;
    const cols = buildColumns();
    cols.forEach((col, idx) => {
      try {
        hot.setDataAtCell(rowIndex, idx, rowData[col.data] ?? "");
      } catch (_) {}
    });
  }

  function applyCommonStyles(instance, td, row, col, prop, value) {
    if (typeof row !== "number" || row < 0) return;
    const physicalRow = instance.toPhysicalRow(row);
    if (physicalRow === null) return;

    const rowData = instance.getSourceDataAtRow(physicalRow);
    if (!rowData) return;

    const meta = rowData.meta || {};

    // Try to parse meta_json if meta object is empty
    let bgColor = null;
    if (meta.backgroundColor) {
      bgColor = meta.backgroundColor;
    } else if (rowData.meta_json) {
      try {
        const m = JSON.parse(rowData.meta_json);
        bgColor = m.backgroundColor;
      } catch (e) {}
    }

    const isSection = rowData.test_case_number === "SECTION";

    // 1. Background Color
    if (bgColor) {
      td.style.backgroundColor = bgColor;
    } else if (isSection) {
      td.style.backgroundColor = "#f3f4f6";
    } else {
      // For standard cells, we don't clear background because:
      // - Default renderers might have set it (e.g. conditional formatting).
      // - If we want "No Color" to mean "Default", we leave it.
      // - If user explicitly set "No Color", bgColor would be null/undefined.
    }

    // 2. Section Row Logic
    if (isSection) {
      td.classList.add("adhoc-section-cell");
      td.style.textAlign = "center";
      td.style.backgroundColor = "#f3f4f6";
      td.style.color = "#374151";
      if (prop === "test_case_number") {
        td.style.color = "#6b7280";
      } else if (prop === "title") {
        td.style.fontWeight = "700";
      } else {
        td.textContent = "";
      }
    }
  }

    function updateSectionMerges(source, initialLoad) {
        const instance = this;
        // Skip render during initial load to avoid recursion/errors; initial render happens automatically
        if (initialLoad === true) return;
        
        if (!instance || !instance.getPlugin) return;
        
        const plugin = instance.getPlugin('mergeCells');
        if (!plugin) return;

        plugin.clearCollections();
        
        const count = instance.countRows();
        
        for (let r = 0; r < count; r++) {
            // Use visual row index 'r' for checking
            const physicalRow = instance.toPhysicalRow(r);
            if (physicalRow === null) continue;
            
            const rowData = instance.getSourceDataAtRow(physicalRow);
            if (rowData && rowData.test_case_number === 'SECTION') {
                // Merge Title (col 1) to end (col 10) - Visual indices
                plugin.merge(r, 1, r, 10); 
            }
        }
        
        // Render only if instance is ready
        if (instance.view) {
            instance.render();
        }
    }

    function initHot(data) {
        if (hot) {
            hot.destroy();
            dom.gridHost.innerHTML = '';
        }

        const columns = buildColumns();
        const isReadOnly = isRunReadOnly;

        hot = new Handsontable(dom.gridHost, {
            data,
            columns,
            colHeaders: columns.map(c => c.title || ''),
            rowHeaders: true,
            width: '100%',
            height: '100%',
            rowHeights: 28,
            manualColumnResize: true,
            manualRowResize: true,
            stretchH: 'none',
            licenseKey: 'non-commercial-and-evaluation',
            readOnly: isReadOnly,
            contextMenu: isReadOnly ? ['copy'] : ['copy','cut','paste','---------','row_above','row_below','remove_row','---------','undo','redo'],
            dropdownMenu: ['filter_by_condition','filter_by_value','filter_action_bar'],
            filters: true,
            fillHandle: !isReadOnly,
            search: true, // Enable Search Plugin
            outsideClickDeselects: false, // Keep selection when clicking toolbar buttons
            mergeCells: true, // Enable Merging
            undoRedo: false, // Disable Undo/Redo
            afterLoadData: updateSectionMerges,
            afterSort: updateSectionMerges,
            afterFilter: updateSectionMerges,
            beforeRemoveRow: (index, amount, physicalRows) => {
        if (isRunReadOnly) return false;
        if (!hot) return;
        physicalRows.forEach((row) => {
          const item = hot.getSourceDataAtRow(row);
          if (item && item.id) {
            deletedItemIds.add(item.id);
          }
        });
      },
      afterRemoveRow: () => {
        handleChange();
      },
      cells: function (row, col) {
        const cellProps = {};
        if (typeof row !== "number" || row < 0) return cellProps;

        const physicalRow = this.instance.toPhysicalRow(row);
        if (physicalRow === null) return cellProps;

        const rowData = this.instance.getSourceDataAtRow(physicalRow);

        if (rowData && rowData.test_case_number === "SECTION") {
          const prop = this.instance.colToProp(col);
          cellProps.renderer = function (instance, td) {
            td.textContent = "";
            td.style.backgroundColor = "#f3f4f6";
            td.style.color = "#374151";
            td.style.textAlign = "center";
            if (prop === "test_case_number") {
              td.style.color = "#6b7280";
              td.textContent = rowData.test_case_number || "SECTION";
            } else if (prop === "title") {
              td.style.fontWeight = "700";
              td.textContent = rowData.title || "";
            }
          };
          if (prop !== "title") {
            cellProps.readOnly = true;
          }
        }
        return cellProps;
      },
                  afterInit: function() {
                      fixAriaHidden();
                      updateSectionMerges.call(this);
                  },
                  afterBeginEditing: fixAriaHidden,      afterChange: (changes, source) => {
        if (source === "loadData" || source === "autosave") {
          return;
        }
        handleChange();
      },
      afterPaste: () => {
        handleChange();
      },
    });
  }

  // --- Search & Replace Feature ---

  // Inject Button: Add Section (align with system button style)
  if (dom.addRow && !document.getElementById("addSectionBtn")) {
    const btn = document.createElement("button");
    btn.id = "addSectionBtn";
    btn.className = "btn btn-sm btn-primary ms-2";
    btn.innerHTML =
      '<i class="fas fa-heading me-1"></i><span data-i18n="adhoc.addSection">Add Section</span>';
    btn.onclick = onAddSection;
    dom.addRow.parentNode.insertBefore(btn, dom.addRow.nextSibling);
  }

  // Color picker disabled (all)

  // Inject Button: Find & Replace (align with system secondary style)
  if (dom.addRow && !document.getElementById("searchReplaceBtn")) {
    const btn = document.createElement("button");
    btn.id = "searchReplaceBtn";
    btn.className = "btn btn-sm btn-secondary ms-2";
    btn.innerHTML =
      '<i class="fas fa-search me-1"></i><span data-i18n="adhoc.findReplace">Find & Replace</span>';
    btn.onclick = openSearchModal;
    btn.title = "Ctrl+F / ⌘+F";
    dom.addRow.parentNode.insertBefore(btn, dom.addRow.nextSibling);
  }

  // Keyboard shortcut: Ctrl+F or Cmd+F
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
      e.preventDefault();
      openSearchModal();
    }
  });

  // --- Convert to Test Case Modal ---
  let convertModalInstance = null;
  let convertSetCache = [];
  const convertSectionCache = new Map();

  function ensureConvertModal() {
    if (document.getElementById("adhocConvertModal")) return;
    const modalHtml = `
      <div class="modal fade" id="adhocConvertModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered modal-lg">
          <div class="modal-content shadow">
            <div class="modal-header">
              <h5 class="modal-title"><i class="fas fa-exchange-alt me-2"></i>${tt('adhoc.convertToTestCase','Convert to Test Case')}</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body">
              <div class="mb-3">
                <label class="form-label">${tt('adhoc.convertTargetSet','Target Test Case Set')}</label>
                <select id="convertTargetSet" class="form-select"></select>
              </div>
              <div class="mb-3">
                <label class="form-label">${tt('adhoc.convertTargetSection','Target Section')}</label>
                <select id="convertTargetSection" class="form-select"></select>
              </div>
              <div class="mb-3">
                <div class="d-flex align-items-center justify-content-between">
                  <label class="form-label mb-0">${tt('adhoc.convertSelectItems','Select Ad-hoc Test Cases (current sheet)')}</label>
                  <small class="text-muted">${tt('adhoc.convertHintCurrentSheet','Only current sheet items are listed')}</small>
                </div>
                <div id="convertItemsList" class="border rounded p-2" style="max-height: 320px; overflow-y: auto;"></div>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">${tt('common.cancel','Cancel')}</button>
              <button type="button" class="btn btn-success" id="confirmConvertBtn">
                <i class="fas fa-check me-1"></i>${tt('common.confirm','Confirm')}
              </button>
            </div>
          </div>
        </div>
      </div>`;
    document.body.insertAdjacentHTML("beforeend", modalHtml);
    const btn = document.getElementById("confirmConvertBtn");
    btn.addEventListener("click", submitConvertSelection);
    const setSelect = document.getElementById("convertTargetSet");
    setSelect.addEventListener("change", async () => {
      await loadConvertSections(setSelect.value);
    });
  }

  async function loadConvertSets() {
    if (convertSetCache.length > 0) return convertSetCache;
    if (!currentRun?.team_id) return [];
    const resp = await window.AuthClient.fetch(`/api/teams/${currentRun.team_id}/test-case-sets`);
    if (!resp.ok) return [];
    convertSetCache = await resp.json();
    return convertSetCache;
  }

  function flattenSections(tree, res = [], depth = 0) {
    tree.forEach((node) => {
      res.push({ id: node.id, name: node.name, depth });
      if (Array.isArray(node.children) && node.children.length > 0) {
        flattenSections(node.children, res, depth + 1);
      }
    });
    return res;
  }

  async function loadConvertSections(setId) {
    const sectionSelect = document.getElementById("convertTargetSection");
    if (!setId || !sectionSelect) return;
    if (convertSectionCache.has(setId)) {
      renderSectionOptions(convertSectionCache.get(setId));
      return;
    }
    const resp = await window.AuthClient.fetch(`/api/test-case-sets/${setId}/sections`);
    if (!resp.ok) {
      sectionSelect.innerHTML = `<option value="">${tt('adhoc.convertNoSection','No sections')}</option>`;
      return;
    }
    const tree = await resp.json();
    const flat = flattenSections(tree);
    convertSectionCache.set(setId, flat);
    renderSectionOptions(flat);
  }

  function renderSectionOptions(list) {
    const sectionSelect = document.getElementById("convertTargetSection");
    if (!sectionSelect) return;
    if (!list || list.length === 0) {
      sectionSelect.innerHTML = `<option value="">${tt('adhoc.convertNoSection','No sections')}</option>`;
      return;
    }
    sectionSelect.innerHTML = list
      .map((s) => {
        const depth = s.depth || 0;
        const nbsp = "&nbsp;".repeat(depth * 3);
        const indicator = depth > 0 ? "&nbsp;&nbsp;↳ " : "";
        return `<option value="${s.id}">${nbsp}${indicator}${escapeHtml(s.name)}</option>`;
      })
      .join("");
  }

  function renderConvertItems() {
    const listEl = document.getElementById("convertItemsList");
    if (!listEl) return;
    const data = hot ? hot.getSourceData() : [];
    if (!data || data.length === 0) {
      listEl.innerHTML = `<div class="text-muted small">${tt('adhoc.noItems','No data')}</div>`;
      return;
    }
    const items = data
      .filter((row) => (row?.test_case_number || "").toUpperCase() !== "SECTION")
      .map((row, idx) => {
        const id = row.id;
        const disabled = !id;
        const title = escapeHtml(row.title || "");
        const num = escapeHtml(row.test_case_number || "");
        const label = num ? `${num} — ${title}` : title || tt('adhoc.convertUntitled','Untitled');
        return { id, disabled, label, idx };
      });

    if (items.length === 0) {
      listEl.innerHTML = `<div class="text-muted small">${tt('adhoc.noItems','No data')}</div>`;
      return;
    }

    const rowsHtml = items
      .map(({ id, disabled, label, idx }) => {
        return `<div class="form-check mb-1">
            <input class="form-check-input convert-item-checkbox" data-index="${idx}" type="checkbox" value="${id || ''}" id="convertItem${idx}" ${disabled ? 'disabled' : 'checked'}>
            <label class="form-check-label" for="convertItem${idx}">
              ${label} ${disabled ? '<span class="text-muted small">(' + tt('adhoc.convertSaveHint','Save first to convert') + ')</span>' : ''}
            </label>
          </div>`;
      })
      .join("");

    listEl.innerHTML = `
      <div class="d-flex align-items-center mb-2">
        <input type="checkbox" class="form-check-input me-2" id="convertSelectAll">
        <label for="convertSelectAll" class="form-check-label mb-0">${tt('adhoc.selectAll','Select All')}</label>
      </div>
      ${rowsHtml}
    `;

    wireConvertSelectionHandlers();
  }

  function wireConvertSelectionHandlers() {
    const listEl = document.getElementById("convertItemsList");
    if (!listEl) return;
    let lastCheckedIndex = null;

    const updateSelectAllState = () => {
      const checkboxes = Array.from(listEl.querySelectorAll(".convert-item-checkbox")).filter(c => !c.disabled);
      const allChecked = checkboxes.length > 0 && checkboxes.every(c => c.checked);
      const selectAll = document.getElementById("convertSelectAll");
      if (selectAll) selectAll.checked = allChecked;
    };

    listEl.addEventListener("click", (e) => {
      const target = e.target;
      if (target && target.classList.contains("convert-item-checkbox")) {
        const idx = Number(target.dataset.index);
        if (!Number.isNaN(idx)) {
          if (e.shiftKey && lastCheckedIndex !== null) {
            const start = Math.min(lastCheckedIndex, idx);
            const end = Math.max(lastCheckedIndex, idx);
            const state = target.checked;
            const boxes = Array.from(listEl.querySelectorAll(".convert-item-checkbox")).filter(c => !c.disabled);
            boxes.forEach((box) => {
              const bIdx = Number(box.dataset.index);
              if (bIdx >= start && bIdx <= end) box.checked = state;
            });
          }
          lastCheckedIndex = idx;
          updateSelectAllState();
        }
      }
      if (target && target.id === "convertSelectAll") {
        const checked = target.checked;
        const boxes = Array.from(listEl.querySelectorAll(".convert-item-checkbox")).filter(c => !c.disabled);
        boxes.forEach((box) => {
          box.checked = checked;
        });
      }
    });

    updateSelectAllState();
  }

  async function openConvertModal() {
    ensureConvertModal();
    convertSetCache = []; // Always refresh to avoid stale team switch
    convertSectionCache.clear();
    const setSelect = document.getElementById("convertTargetSet");
    const sectionSelect = document.getElementById("convertTargetSection");
    if (setSelect) setSelect.innerHTML = `<option value="">${tt('loading.loading','Loading...')}</option>`;
    if (sectionSelect) sectionSelect.innerHTML = `<option value="">${tt('loading.loading','Loading...')}</option>`;
    renderConvertItems();

    const sets = await loadConvertSets();
    if (setSelect) {
      if (!sets || sets.length === 0) {
        setSelect.innerHTML = `<option value="">${tt('adhoc.convertNoSet','No Test Case Set')}</option>`;
      } else {
        setSelect.innerHTML = sets
          .map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`)
          .join("");
      }
    }
    if (sets && sets.length > 0) {
      await loadConvertSections(sets[0].id);
    }

    const modalEl = document.getElementById("adhocConvertModal");
    convertModalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
    convertModalInstance.show();
  }

  async function submitConvertSelection() {
    const setSelect = document.getElementById("convertTargetSet");
    const sectionSelect = document.getElementById("convertTargetSection");
    const setId = setSelect?.value;
    const sectionId = sectionSelect?.value || null;
    const checks = Array.from(document.querySelectorAll(".convert-item-checkbox")).filter((c) => c.checked && c.value);
    if (!setId) {
      alert(tt('adhoc.convertSelectSet','Please select a Test Case Set'));
      return;
    }
    if (checks.length === 0) {
      alert(tt('adhoc.convertSelectItems','Select at least one test case'));
      return;
    }
    const itemIds = checks.map((c) => Number(c.value)).filter((v) => !Number.isNaN(v));
    try {
      const resp = await window.AuthClient.fetch(`/api/adhoc-runs/${runId}/convert-to-testcases`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sheet_id: currentSheetId,
          item_ids: itemIds,
          target_set_id: Number(setId),
          target_section_id: sectionId ? Number(sectionId) : null
        })
      });
      if (resp.ok) {
        const res = await resp.json();
        const msg = res.message || tt('adhoc.convertSuccess','Conversion successful');
        if (window.AppUtils && AppUtils.showSuccess) {
          AppUtils.showSuccess(msg);
        } else {
          // Fallback to bootstrap modal alert
          const fallback = document.createElement('div');
          fallback.className = 'alert alert-success position-fixed top-0 start-50 translate-middle-x mt-3 shadow';
          fallback.style.zIndex = '2000';
          fallback.textContent = msg;
          document.body.appendChild(fallback);
          setTimeout(() => { fallback.remove(); }, 2500);
        }
        if (convertModalInstance) convertModalInstance.hide();
      } else {
        const msg = tt('common.error','Operation failed');
        if (window.AppUtils && AppUtils.showError) {
          AppUtils.showError(msg);
        } else {
          alert(msg);
        }
      }
    } catch (e) {
      console.error(e);
      const msg = tt('common.error','Operation failed');
      if (window.AppUtils && AppUtils.showError) {
        AppUtils.showError(msg);
      } else {
        alert(msg);
      }
    }
  }


          let searchModal = null;

          let searchResults = [];

      

          function ensureSearchModal() {    if (document.getElementById("adhocSearchModal")) return;

    const modalHtml = `
        <div class="modal fade" id="adhocSearchModal" tabindex="-1" data-bs-backdrop="false">
            <div class="modal-dialog modal-dialog-scrollable modal-sm" style="margin-right: 20px; margin-top: 60px; margin-left: auto;">
                <div class="modal-content shadow">
                    <div class="modal-header p-2">
                        <h6 class="modal-title small">Find & Replace</h6>
                        <button type="button" class="btn-close btn-sm" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body p-3">
                        <div class="mb-2">
                            <input type="text" id="findInput" class="form-control form-control-sm" placeholder="Find what...">
                        </div>
                        <div class="mb-3">
                            <input type="text" id="replaceInput" class="form-control form-control-sm" placeholder="Replace with...">
                        </div>
                        <div class="d-flex justify-content-between mb-2">
                            <button id="findNextBtn" class="btn btn-sm btn-primary flex-grow-1 me-1">Find Next</button>
                            <button id="findPrevBtn" class="btn btn-sm btn-primary flex-grow-1">Find Prev</button>
                        </div>
                        <div class="d-flex justify-content-between">
                            <button id="replaceBtn" class="btn btn-sm btn-secondary flex-grow-1 me-1">Replace</button>
                            <button id="replaceAllBtn" class="btn btn-sm btn-secondary flex-grow-1">Replace All</button>
                        </div>
                        <div id="searchMsg" class="text-muted small mt-2 text-center" style="min-height: 1.2em;"></div>
                    </div>
                </div>
            </div>
        </div>`;

    const div = document.createElement("div");
    div.innerHTML = modalHtml;
    document.body.appendChild(div.firstElementChild);

    const m = document.getElementById('adhocSearchModal');
    m.addEventListener('shown.bs.modal', () => {
        if (hot) hot.unlisten(); // Disable HOT keyboard shortcuts
        m.removeAttribute('aria-hidden');
        const inp = document.getElementById('findInput');
        if (inp) inp.focus();
    });
    m.addEventListener('hide.bs.modal', () => {
        const active = document.activeElement;
        if (active && m.contains(active)) {
            active.blur();
        }
    });
    m.addEventListener('hidden.bs.modal', () => {
        if (hot) {
            const plugin = hot.getPlugin('search');
            plugin.query(null); // Clear search query
            hot.deselectCell();
            hot.render();
            hot.listen(); // Re-enable HOT keyboard shortcuts
        }
        searchResults = [];
        document.getElementById('searchMsg').textContent = '';
    });
    
    document.getElementById('findNextBtn').addEventListener('click', () => doFind(1));
    document
      .getElementById("findPrevBtn")
      .addEventListener("click", () => doFind(-1));
        document.getElementById('replaceBtn').addEventListener('click', doReplace);
        document.getElementById('replaceAllBtn').addEventListener('click', doReplaceAll);
        
        // Prevent Handsontable from intercepting keys in inputs
        const inputs = m.querySelectorAll('input');
        
        // Ensure unlisten on interaction
        inputs.forEach(input => {
            input.addEventListener('focus', () => { if(hot) hot.unlisten(); });
            input.addEventListener('click', () => { if(hot) hot.unlisten(); });
        });

        // IME-friendly: only handle Enter on findInput, ignore when composing
        const findInput = document.getElementById('findInput');
        if (findInput) {
            findInput.addEventListener('keydown', (e) => {
                if (e.isComposing || e.keyCode === 229) return; // IME composition
                if (e.key === 'Enter') {
                    e.preventDefault();
                    doFind(1);
                }
            });
        }
    }

  function openSearchModal() {
    ensureSearchModal();
    if (!searchModal) {
      searchModal = new bootstrap.Modal(
        document.getElementById("adhocSearchModal"),
      );
    }
    searchModal.show();
  }

    function doFind(direction = 1) {
        if (!hot) return;
        const query = document.getElementById('findInput').value;
        if (!query) return;

        const plugin = hot.getPlugin('search');
        const result = plugin.query(query);
        searchResults = result || [];

        const msg = document.getElementById('searchMsg');
        if (searchResults.length === 0) {
            msg.textContent = 'No matches found.';
            hot.render();
            return;
        }

        // Get current cursor position (or default to start -1, -1)
        const selected = hot.getSelectedLast() || [-1, -1];
        const currRow = selected[0];
        const currCol = selected[1];

        // Find next match relative to current position
        let nextMatchIndex = -1;

        if (direction === 1) {
            // Find Next
            for (let i = 0; i < searchResults.length; i++) {
                const match = searchResults[i];
                if (match.row > currRow || (match.row === currRow && match.col > currCol)) {
                    nextMatchIndex = i;
                    break;
                }
            }
            // Wrap around if not found
            if (nextMatchIndex === -1) nextMatchIndex = 0;
        } else {
            // Find Prev
            for (let i = searchResults.length - 1; i >= 0; i--) {
                const match = searchResults[i];
                if (match.row < currRow || (match.row === currRow && match.col < currCol)) {
                    nextMatchIndex = i;
                    break;
                }
            }
            // Wrap around if not found
            if (nextMatchIndex === -1) nextMatchIndex = searchResults.length - 1;
        }

        msg.textContent = `${nextMatchIndex + 1} / ${searchResults.length}`;

        const match = searchResults[nextMatchIndex];
        // Use visual selection to ensure scrolling works for user
        hot.selectCell(match.row, match.col);
        hot.scrollViewportTo(match.row, match.col);
        hot.render();
    }

    function doReplace() {
        if (!hot) return;
        
        // Get current selection
        const selected = hot.getSelectedLast();
        if (!selected) {
            doFind(1); // Try to find first if nothing selected
            return;
        }
        
        const row = selected[0];
        const col = selected[1];
        const cellData = hot.getDataAtCell(row, col);
        const replaceVal = document.getElementById('replaceInput').value || '';
        const query = document.getElementById('findInput').value;
        
        // Check if current cell matches query (case insensitive)
        if (String(cellData).toLowerCase().includes(query.toLowerCase())) {
             const newVal = String(cellData).replace(new RegExp(escapeRegExp(query), 'gi'), replaceVal);
             hot.setDataAtCell(row, col, newVal);
        }
        
        // Move to next
        doFind(1);
    }

  function doReplaceAll() {
    if (!hot) return;
    const query = document.getElementById("findInput").value;
    const replaceVal = document.getElementById("replaceInput").value || "";
    if (!query) return;

    const plugin = hot.getPlugin("search");
    const result = plugin.query(query);

    if (!result || result.length === 0) {
      document.getElementById("searchMsg").textContent = "0 matches replaced.";
      return;
    }

    const changes = [];
    const regex = new RegExp(escapeRegExp(query), "gi");

    // Group by cell to avoid multiple replacements in same cell confusing indices (though query returns unique cells usually?)
    // plugin.query returns array of {row, col, data}.

    result.forEach(({ row, col, data }) => {
      const newVal = String(data).replace(regex, replaceVal);
      changes.push([row, col, newVal]);
    });

        hot.setDataAtCell(changes);
        document.getElementById('searchMsg').textContent = `Replaced ${changes.length} instances.`;
        searchResults = [];
        hot.render();
    }

  function escapeRegExp(string) {
    return string.replace(/[.*+?^`{`}();|[\]\\]/g, "\\$&");
  }

  async function onAddSheet() {
    if (isRunReadOnly) {
      alert(tt("adhoc.readonly", "Read-only (archived)"));
      return;
    }
    const name = prompt(
      "Sheet name",
      `Sheet${(currentRun?.sheets?.length || 0) + 1}`,
    );
    if (!name) return;
    try {
      const resp = await window.AuthClient.fetch(
        `/api/adhoc-runs/${runId}/sheets`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name,
            sort_order: currentRun?.sheets?.length || 0,
          }),
        },
      );
      if (!resp.ok) throw new Error(tt("adhoc.saveFailed", "Failed to save"));
      const newSheet = await resp.json();
      await loadRun();
      switchToSheet(newSheet.id);
    } catch (e) {
      console.error(e);
      alert("Create sheet failed");
    }
  }

  function onAddRow() {
    if (isRunReadOnly) {
      alert(tt("adhoc.readonly", "Read-only (archived)"));
      return;
    }
    if (!hot) return;
    const newRow = convertItemToRow(null);
    const lastRow = hot.countRows() - 1;
    const insertAt = lastRow >= 0 ? lastRow : 0;
    hot.alter('insert_row_below', insertAt, 1);
    const r = insertAt + 1;
    setRowDataFromColumns(r, newRow);
    setTimeout(() => { try { hot.selectCell(r, 0); } catch (_) {} }, 0);
    handleChange();
  }

  function onAddSection() {
    if (isRunReadOnly) {
      alert(tt("adhoc.readonly", "Read-only (archived)"));
      return;
    }
    if (!hot) return;
    const lastRow = hot.countRows() - 1;
    const sectionRow = {
      id: null,
      test_case_number: "SECTION",
      title: "--- Section Header ---",
      priority: "",
      precondition: "",
      steps: "",
      expected_result: "",
      test_result: "",
      assignee_name: "",
      comments: "",
      bug_list: "",
      meta_json: JSON.stringify({ backgroundColor: "#f3f4f6" }),
    };
    const insertAt = lastRow >= 0 ? lastRow : 0;
    hot.alter('insert_row_below', insertAt, 1);
    const r = insertAt + 1;
    setRowDataFromColumns(r, sectionRow);
    setTimeout(() => { try { hot.selectCell(r, 1); } catch (_) {} }, 0);
    handleChange();
  }

  // updateSectionRowsColor removed

  function handleChange() {
    if (isRunReadOnly) {
      if (dom.saveStatus) {
        dom.saveStatus.textContent = tt("adhoc.readonly", "Read-only (archived)");
        dom.saveStatus.className = "text-muted small";
      }
      return;
    }
    if (!dom.saveStatus) return;
    dom.saveStatus.textContent = tt("adhoc.unsaved", "Unsaved changes...");
    dom.saveStatus.className = "text-warning small";
    clearTimeout(autoSaveTimer);
    autoSaveTimer = setTimeout(saveChanges, 800);
  }

  async function saveChanges() {
    if (isRunReadOnly) return;
    if (!hot || !currentSheetId) return;

    if (isSaving) {
      isPendingSave = true;
      return;
    }

    isSaving = true;

    try {
      // Normalization maps
      const PRIORITY_MAP = {
        high: "High",
        medium: "Medium",
        low: "Low",
      };
      const RESULT_MAP = {
        passed: "Passed",
        failed: "Failed",
        retest: "Retest",
        "not available": "Not Available",
        pending: "Pending",
        "not required": "Not Required",
      };
      const RESULT_VALUES = Object.values(RESULT_MAP);

      const data = hot.getSourceData();

      // Prune deletedItemIds
      const currentIds = new Set(data.map((i) => i.id).filter((id) => id));
      for (const id of deletedItemIds) {
        if (currentIds.has(id)) {
          deletedItemIds.delete(id);
        }
      }

      const payload = data
        .map((row, idx) => {
          // Check if Section
          const isSection = row.test_case_number === "SECTION";

          // Sanitize Priority
          let prio = (row.priority || "").toString().trim();
          const prioLower = prio.toLowerCase();

          if (isSection) {
            prio = "Medium";
          } else {
            if (PRIORITY_MAP[prioLower]) {
              prio = PRIORITY_MAP[prioLower];
            } else if (!["High", "Medium", "Low"].includes(prio)) {
              prio = "Medium";
            }
          }

          // Sanitize Result
          let res = (row.test_result || "").toString().trim();
          const resLower = res.toLowerCase();

          if (isSection) {
            res = "Not Required";
          } else {
            if (RESULT_MAP[resLower]) {
              res = RESULT_MAP[resLower];
            } else if (!RESULT_VALUES.includes(res)) {
              res = null;
            }
          }

          return {
            id: row.id ? Number(row.id) : null,
            row_index: idx,
            test_case_number: isSection
              ? "SECTION"
              : (row.test_case_number || "").trim(),
            title: (row.title || "").trim(),
            priority: prio,
            precondition: (row.precondition || "").trim(),
            steps: (row.steps || "").trim(),
            expected_result: (row.expected_result || "").trim(),
            jira_tickets: (row.jira_tickets || "").trim(),
            test_result: res,
            assignee_name: (row.assignee_name || "").trim(),
            comments: (row.comments || "").trim(),
            bug_list: (row.bug_list || "").trim(),
            meta_json: row.meta_json,
          };
        })
        .filter(
          (r) =>
            r.id ||
            r.title ||
            r.test_case_number ||
            r.comments ||
            r.bug_list ||
            r.assignee_name,
        );

      // Append Deletions
      deletedItemIds.forEach((id) => {
        payload.push({ id: id, _delete: true });
      });

      if (payload.length === 0) {
        dom.saveStatus.textContent = tt("adhoc.saved", "All changes saved");
        dom.saveStatus.className = "text-muted small";
        return;
      }

      dom.saveStatus.textContent = tt("adhoc.saving", "Saving...");
      dom.saveStatus.className = "text-info small";

      const resp = await window.AuthClient.fetch(
        `/api/adhoc-runs/${runId}/sheets/${currentSheetId}/items/batch`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      if (!resp.ok) throw new Error(tt("adhoc.saveFailed", "Failed to save"));
      const result = await resp.json().catch(() => ({}));

      // Success - Clear deletions
      deletedItemIds.clear();

      if (result?.items?.length) {
        // Update IDs using setSourceDataAtCell
        result.items.forEach(({ id, row_index }) => {
          const idx = Number(row_index);
          const newId = Number(id);

          if (
            Number.isInteger(idx) &&
            idx >= 0 &&
            Number.isInteger(newId) &&
            newId > 0
          ) {
            // Use physical index from getSourceData mapping
            hot.setSourceDataAtCell(idx, "id", newId);
          }
        });
        hot.render();
      }
      dom.saveStatus.textContent = tt("adhoc.saved", "All changes saved");
      dom.saveStatus.className = "text-muted small";
    } catch (e) {
      console.error(e);
      dom.saveStatus.textContent = tt("adhoc.saveFailed", "Error saving!");
      dom.saveStatus.className = "text-danger small";
    } finally {
      isSaving = false;
      if (isPendingSave) {
        isPendingSave = false;
        setTimeout(saveChanges, 100); // Small delay to debounce
      }
    }
  }

  async function loadAssignees() {
    let options = [];
    try {
      const resp = await window.AuthClient.fetch(
        "/api/users?page=1&per_page=100",
      );
      if (resp.ok) {
        const data = await resp.json();
        console.info("Assignee users raw", data);
        options = (data?.users || [])
          .filter((u) => {
            const role = (u.role || "").toLowerCase();
            const username = (u.username || "").toLowerCase();
            // 排除預設 admin/super_admin
            return role !== "super_admin" && username !== "admin";
          })
          .map((u) => u.lark_name || u.full_name || u.username || "")
          .filter(Boolean);
        console.info("Assignee options loaded", options.length);
      } else {
        console.warn("Assignee load users failed status", resp.status);
        console.warn(
          "Assignee load users body",
          await resp.text().catch(() => ""),
        );
      }
    } catch (e) {
      console.warn("Assignee load users error", e);
    }

    assigneeOptions = options
      .filter((v, idx, arr) => arr.indexOf(v) === idx)
      .sort((a, b) => a.localeCompare(b));

    if (hot) {
      const cols = buildColumns();
      hot.updateSettings({
        columns: cols,
        colHeaders: cols.map((c) => c.title || ""),
      });
      hot.render();
    }
  }

  function fixAriaHidden() {
    try {
      document
        .querySelectorAll('.handsontableInput[aria-hidden="true"]')
        .forEach((el) => {
          el.setAttribute("aria-hidden", "false");
        });
    } catch (_) {}
  }

  function priorityRenderer(
    instance,
    td,
    row,
    col,
    prop,
    value,
    cellProperties,
  ) {
    const rowData = instance.getSourceDataAtRow(instance.toPhysicalRow(row));
    const isSection = rowData?.test_case_number === "SECTION";
    Handsontable.renderers.TextRenderer.apply(this, arguments);
    if (isSection) {
      td.textContent = "";
      td.style.backgroundColor = "#f3f4f6";
      td.style.color = "#6b7280";
      td.style.fontWeight = "600";
      td.style.textAlign = "center";
      td.style.verticalAlign = "middle";
      return;
    }
    const val = (value || "").toLowerCase();
    td.style.fontWeight = "600";
    td.style.textAlign = "center";
    td.style.verticalAlign = "middle";
    if (val === "high") {
      td.style.backgroundColor = "#fdecea";
      td.style.color = "#b91c1c";
    } else if (val === "medium") {
      td.style.backgroundColor = "#fff4e5";
      td.style.color = "#b45309";
    } else if (val === "low") {
      td.style.backgroundColor = "#eef2ff";
      td.style.color = "#4338ca";
    } else {
      td.style.backgroundColor = "";
      td.style.color = "";
      td.style.fontWeight = "";
    }
  }

  function resultRenderer(instance, td, row, col, prop, value, cellProperties) {
    const rowData = instance.getSourceDataAtRow(instance.toPhysicalRow(row));
    const isSection = rowData?.test_case_number === "SECTION";
    Handsontable.renderers.TextRenderer.apply(this, arguments);
    if (isSection) {
      td.textContent = "";
      td.style.backgroundColor = "#f3f4f6";
      td.style.color = "#6b7280";
      td.style.fontWeight = "600";
      td.style.textAlign = "center";
      td.style.verticalAlign = "middle";
      return;
    }
    const val = (value || "").toLowerCase();
    td.style.fontWeight = "600";
    td.style.textAlign = "center";
    td.style.verticalAlign = "middle";
    td.style.backgroundColor = "";
    td.style.color = "";
    if (val === "passed") {
      td.style.color = "#15803d";
      td.style.backgroundColor = "#e7f6ec";
    } else if (val === "failed") {
      td.style.color = "#b91c1c";
      td.style.backgroundColor = "#fdecea";
    } else if (val === "retest") {
      td.style.color = "#b45309";
      td.style.backgroundColor = "#fff4e5";
    } else if (val === "not available") {
      td.style.color = "#4b5563";
      td.style.backgroundColor = "#f3f4f6";
    } else if (val === "pending") {
      td.style.color = "#92400e";
      td.style.backgroundColor = "#fef3c7";
    } else if (val === "not required") {
      td.style.color = "#6b7280";
      td.style.backgroundColor = "#f3f4f6";
    } else {
      td.style.fontWeight = "";
    }
  }

  // --- Charts & Reports (Ad-hoc) ---
  async function openReports() {
    try {
      ensureReportsModal();
      const modalEl = document.getElementById("adhocReportsModal");
      const contentEl = document.getElementById("adhocReportsContent");
      if (!modalEl || !contentEl) {
        console.warn("reports modal element missing");
        return;
      }
      if (!(window.bootstrap && window.bootstrap.Modal)) {
        console.error("bootstrap Modal not available");
        return;
      }

      // 取最新資料
      console.info("reports fetch run", runId);
      const resp = await window.AuthClient.fetch(`/api/adhoc-runs/${runId}`);
      if (!resp.ok) {
        console.error("reports fetch failed", resp.status);
        throw new Error("load run failed");
      }
      const run = await resp.json();
      console.info("reports run loaded with sheets", (run.sheets || []).length);

      const statuses = [
        "Passed",
        "Failed",
        "Retest",
        "Not Available",
        "Pending",
        "Not Required",
      ];
      const normalize = (v) => (v || "").toLowerCase();

      const sheetRows = [];
      const total = { name: "Total", counts: {} };
      statuses.forEach((s) => (total.counts[s] = 0));

      (run.sheets || []).forEach((sheet) => {
        const counts = {};
        statuses.forEach((s) => (counts[s] = 0));
        (sheet.items || []).forEach((item) => {
          const tcNum = String(item.test_case_number || '').toUpperCase();
          if (tcNum === 'SECTION') return;
          const val = normalize(item.test_result || "");
          const match = statuses.find((s) => s.toLowerCase() === val);
          if (match) counts[match] += 1;
        });
        statuses.forEach((s) => (total.counts[s] += counts[s]));
        sheetRows.push({ name: sheet.name, counts });
      });

      if (sheetRows.length === 0) {
        contentEl.innerHTML =
          '<div class=\"text-muted\">No sheets or data</div>';
      } else {
        renderReportsContent(contentEl, sheetRows, total, statuses);
      }

      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      console.info("showing adhoc reports modal");
      modal.show();
    } catch (e) {
      console.error("adhoc reports error", e);
      alert(tt("adhoc.loadFailed", "Failed to load reports"));
    }
  }

  function ensureReportsModal() {
    if (document.getElementById("adhocReportsModal")) return;
    const wrapper = document.createElement("div");
    wrapper.innerHTML = `
        <div class="modal fade" id="adhocReportsModal" tabindex="-1" aria-labelledby="adhocReportsModalLabel" aria-hidden="true">
          <div class="modal-dialog modal-lg modal-dialog-centered">
            <div class="modal-content">
              <div class="modal-header">
                <h5 class="modal-title" id="adhocReportsModalLabel"><i class="fas fa-chart-pie me-2"></i><span data-i18n="testRun.chartsReports">Charts & Reports</span></h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
              </div>
              <div class="modal-body">
                <div id="adhocReportsContent" class="table-responsive"></div>
              </div>
              <div class="modal-footer">
                <button type="button" class="btn btn-primary" id="adhocOpenHtmlBtn">
                  <i class="fas fa-file-alt me-1"></i> Open HTML Report
                </button>
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal" data-i18n="common.close">Close</button>
              </div>
            </div>
          </div>
        </div>`;
    document.body.appendChild(wrapper.firstElementChild);

    const openBtn = document.getElementById("adhocOpenHtmlBtn");
    if (openBtn && !openBtn.dataset.bound) {
      openBtn.dataset.bound = "true";
      openBtn.addEventListener("click", openHtmlReportView);
    }
  }

  function renderReportsContent(container, sheetRows, total, statuses) {
    const colors = {
      Passed: "#16a34a",
      Failed: "#dc2626",
      Retest: "#ea580c",
      "Not Available": "#6b7280",
      Pending: "#d97706",
      "Not Required": "#9ca3af",
    };

    const renderRow = (label, counts) => {
      const tds = statuses
        .map((s) => `<td class=\"text-center\">${counts[s] || 0}</td>`)
        .join("");
      return `<tr><th scope=\"row\">${label}</th>${tds}</tr>`;
    };

    const table = `
            <table class=\"table table-sm align-middle mb-3\">
                <thead>
                    <tr>
                        <th scope=\"col\">Sheet</th>
                        ${statuses.map((s) => `<th scope=\"col\" class=\"text-center\">${s}</th>`).join("")}
                    </tr>
                </thead>
                <tbody>
                    ${renderRow("Total", total.counts)}
                    ${sheetRows.map((r) => renderRow(r.name, r.counts)).join("")}
                </tbody>
            </table>
        `;

    const labels = statuses;
    const totalData = labels.map((l) => total.counts[l] || 0);
    const datasets = [
      {
        label: "Total",
        data: totalData,
        backgroundColor: labels.map((l) => colors[l] || "#9ca3af"),
      },
    ];

    // per-sheet stacked
    const perSheetDatasets = labels.map((label, idx) => ({
      label,
      data: sheetRows.map((r) => r.counts[label] || 0),
      backgroundColor: colors[label] || "#9ca3af",
    }));

    container.innerHTML = `
            <div class=\"row g-3\">
                <div class=\"col-md-6\">
                    <div class=\"card h-100\">
                        <div class=\"card-body\">
                            <h6 class=\"card-title\">Summary (All Sheets)</h6>
                            <canvas id=\"adhocPie\"></canvas>
                        </div>
                    </div>
                </div>
                <div class=\"col-md-6\">
                    <div class=\"card h-100\">
                        <div class=\"card-body\">
                            <h6 class=\"card-title\">Per Sheet (Stacked)</h6>
                            <canvas id=\"adhocBar\"></canvas>
                        </div>
                    </div>
                </div>
            </div>
            <div class=\"mt-3\">${table}</div>
        `;

    const pieCtx = document.getElementById("adhocPie");
    const barCtx = document.getElementById("adhocBar");
    if (!pieCtx || !barCtx) return;

    new Chart(pieCtx, {
      type: "pie",
      data: {
        labels,
        datasets: [
          {
            data: totalData,
            backgroundColor: labels.map((l) => colors[l] || "#9ca3af"),
          },
        ],
      },
      options: {
        plugins: { legend: { position: "bottom" } },
      },
    });

    new Chart(barCtx, {
      type: "bar",
      data: {
        labels: sheetRows.map((r) => r.name),
        datasets: perSheetDatasets,
      },
      options: {
        responsive: true,
        scales: {
          x: { stacked: true },
          y: { stacked: true, beginAtZero: true },
        },
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  // 簡單跳脫 HTML，避免報表輸出 XSS
  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  async function exportHtmlReport() {
    try {
      const run = await fetchRunForReport();
      const html = buildReportHtml(run);

      const blob = new Blob([html], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `adhoc-run-${runId}-report.html`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("export html error", e);
      alert("Failed to export HTML report");
    }
  }

  async function fetchRunForReport() {
    const resp = await window.AuthClient.fetch(`/api/adhoc-runs/${runId}`);
    if (!resp.ok) throw new Error("Failed to load data for report");
    return await resp.json();
  }

  function buildReportHtml(run) {
    const statuses = [
      "Passed",
      "Failed",
      "Retest",
      "Not Available",
      "Pending",
      "Not Required",
    ];
    const normalize = (v) => (v || "").toLowerCase();
    const total = {};
    statuses.forEach((s) => (total[s] = 0));

    const sheetBlocks = (run.sheets || [])
      .map((sheet) => {
        const counts = {};
        statuses.forEach((s) => (counts[s] = 0));
        (sheet.items || []).forEach((item) => {
          const tcNum = String(item.test_case_number || '').toUpperCase();
          if (tcNum === 'SECTION') return;
          const val = normalize(item.test_result || "");
          const match = statuses.find((s) => s.toLowerCase() === val);
          if (match) counts[match] += 1;
        });
        statuses.forEach((s) => (total[s] += counts[s]));

        const rows =
          (sheet.items || [])
            .map(
              (it) => `
                <tr>
                    <td>${escapeHtml(it.test_case_number || "")}</td>
                    <td>${escapeHtml(it.title || "")}</td>
                    <td>${escapeHtml(it.priority || "")}</td>
                    <td>${escapeHtml(it.test_result || "")}</td>
                    <td>${escapeHtml(it.assignee_name || "")}</td>
                    <td>${escapeHtml(it.comments || "")}</td>
                    <td>${escapeHtml(it.bug_list || "")}</td>
                </tr>
            `,
            )
            .join("") ||
          '<tr><td colspan="7" class="text-muted">No items</td></tr>';

        const summaryTds = statuses
          .map((s) => `<td>${counts[s] || 0}</td>`)
          .join("");

        return `
                <h3>${escapeHtml(sheet.name || "")}</h3>
                <table class="summary"><thead><tr><th>Status</th>${statuses.map((s) => `<th>${s}</th>`).join("")}</tr></thead><tbody><tr><td>Count</td>${summaryTds}</tr></tbody></table>
                <table class="items">
                    <thead><tr><th>Test Case #</th><th>Title</th><th>Priority</th><th>Result</th><th>Assignee</th><th>Comments</th><th>Bug List</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            `;
      })
      .join("<hr/>");

    const totalRow = statuses.map((s) => `<td>${total[s] || 0}</td>`).join("");
    const now = new Date().toLocaleString();
    const runName = run.name || `Ad-hoc Run ${runId}`;

    return `<!doctype html>
<html><head><meta charset="UTF-8"><title>${escapeHtml(runName)} Report</title>
<style>
body { font-family: Arial, sans-serif; margin: 20px; color: #111827; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; }
th, td { border: 1px solid #e5e7eb; padding: 6px 8px; font-size: 13px; text-align: left; }
th { background: #f3f4f6; }
.summary th, .summary td { text-align: center; }
h1 { margin-bottom: 0; }
.meta { color: #6b7280; margin-bottom: 16px; }
hr { border: none; border-top: 1px solid #e5e7eb; margin: 24px 0; }
</style>
</head><body>
<h1>${escapeHtml(runName)} - HTML Report</h1>
<div class="meta">Generated at ${escapeHtml(now)}</div>
<h3>Total Summary</h3>
<table class="summary"><thead><tr><th>Status</th>${statuses.map((s) => `<th>${s}</th>`).join("")}</tr></thead><tbody><tr><td>Count</td>${totalRow}</tr></tbody></table>
${sheetBlocks}
</body></html>`;
  }

  async function openHtmlReportView() {
    try {
      const run = await fetchRunForReport();
      const html = buildReportHtml(run);
      const blob = new Blob([html], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (e) {
      console.error("open html report error", e);
      alert("Failed to open HTML report");
    }
  }
});
