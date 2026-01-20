        // Ensure React Flow is available in window scope
        // The UMD build should expose ReactFlow to window, but we verify it
        if (typeof window.ReactFlow === "undefined") {
            console.warn("Attempting to use global ReactFlow variable");
            if (typeof ReactFlow !== "undefined") {
                window.ReactFlow = ReactFlow;
            } else {
                console.error(
                    "React Flow failed to load. Check CDN availability.",
                );
            }
        }

      document.addEventListener('DOMContentLoaded', () => {
        const sidebar = document.querySelector('.usm-sidebar');
        const textTab = document.getElementById('text-tab');
        const visualTab = document.getElementById('visual-tab');
        const mapBtns = document.querySelector('.usm-map-btn-container');
        const hideSidebarForText = () => { if (sidebar) sidebar.classList.add('d-none'); if (mapBtns) mapBtns.classList.add('d-none'); };
        const showSidebarForVisual = () => { if (sidebar) sidebar.classList.remove('d-none'); if (mapBtns) mapBtns.classList.remove('d-none'); };
        if (textTab) textTab.addEventListener('shown.bs.tab', hideSidebarForText);
        if (visualTab) visualTab.addEventListener('shown.bs.tab', showSidebarForVisual);
        const textPane = document.getElementById('text-pane');
        if (textPane && textPane.classList.contains('active')) hideSidebarForText();

        // USM 規範 modal
        const specModalHtml = `
          <div class="modal fade" id="usmSpecModal" tabindex="-1">
            <div class="modal-dialog modal-lg modal-dialog-scrollable">
              <div class="modal-content">
                <div class="modal-header">
                  <h5 class="modal-title"><i class="fas fa-book me-2"></i>${(window.i18n ? window.i18n.t('usm.viewSpec') : 'USM Syntax')}</h5>
                  <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
<pre class="mb-0" style="white-space: pre-wrap; font-size: 13px; line-height: 1.5;">
root: <名稱>
  team: <團隊名稱>
  desc: <描述>
  feature: <名稱>
    desc: <描述>
    story: <名稱>
      desc: <描述>
      as_a: <角色>
      i_want: <需求>
      so_that: <價值>
jira: TCM-123,TCM-456
comment: 文字
related: [@node_id1], [@node_id2]
desc: |
  第一行
  第二行
</pre>
                </div>
              </div>
            </div>
          </div>
        `;
        document.body.insertAdjacentHTML('beforeend', specModalHtml);
        const specBtn = document.getElementById('openUsmSpecBtn');
        if (specBtn) {
          specBtn.addEventListener('click', () => {
            const modalEl = document.getElementById('usmSpecModal');
            const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
            modal.show();
          });
        }

        // 切換回視覺化模式時自動排版
        if (visualTab) {
          visualTab.addEventListener('shown.bs.tab', () => {
            // 延遲至 pane 可見後再排版 + fitView，避免尺寸計算為 0
            setTimeout(() => {
              try {
                window.userStoryMapFlow?.autoLayout?.();
                window.userStoryMapFlow?.fitView?.({ padding: 0.2 });
              } catch (e) {
                console.warn('fitView on visual tab failed', e);
              }
            }, 150);
          });
        }
      });
