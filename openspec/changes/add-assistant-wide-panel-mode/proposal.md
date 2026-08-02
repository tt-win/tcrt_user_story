## Why

目前 AI Assistant 需要同時支援窄版、右下角中版與中央寬版；循環式單一尺寸按鈕無法讓使用者直接選取目標尺寸，也不利於鍵盤與輔助技術理解目前狀態。新增中央 wide 模式並改為三個 direct mode buttons，可在不離開目前頁面的情況下取得約 80% 視窗寬度的工作空間。

## What Changes

- 將面板尺寸明確建模為 `narrow`、`medium`、`wide` 三種 canonical mode。
- 新增 `wide`：桌面上約佔 viewport 80% 寬度與高度，並在畫面中央定位。
- 保留 `narrow` 390px 小窗與 `medium` 右下角約 50vw 大窗的既有幾何。
- 將循環尺寸按鈕改為三個原生 button，直接選取 narrow、medium 或 wide；以 `aria-pressed` 顯示唯一 active mode。
- 以 `tcrt_assistant_panel_size_mode` 保存 canonical preference；既有 `tcrt_assistant_panel_size` 的 compact/expanded 值遷移為 narrow/medium，未知值 fail-closed 回到 narrow，並保留 legacy mirror。
- 讓 wide 模式在 mobile breakpoint 下沿用全螢幕行為，並明確重置中央定位的 transform；mobile 仍保留三個 direct mode buttons。
- wide 開啟時顯示頁面級暗化/模糊 backdrop 以突顯面板，但不攔截底層互動、不啟用 focus trap 或 body scroll lock。
- 更新三語系尺寸 label、動態 title、aria-label、aria-pressed 與前端核心測試。
- Closed panel SHALL be `aria-hidden`/`inert` and return focus to FAB; open panel restores keyboard and assistive-technology access.
- 不新增會攔截互動的 modal backdrop、focus trap 或 body scroll lock；wide backdrop 僅提供視覺暗化/模糊。

## Capabilities

### New Capabilities

（無；此變更擴充既有 Assistant widget UI capability。）

### Modified Capabilities

- `assistant-widget-ui`: 面板尺寸從 compact/expanded 二態擴充為 narrow/medium/wide 三態，增加中央寬版、direct mode controls、canonical preference migration 與 mobile fallback 契約。

## Impact

- Frontend JavaScript：`app/static/js/assistant-widget.js` 的 canonical mode 正規化、legacy localStorage migration、DOM class 套用、direct mode button 與動態 accessibility state。
- Frontend CSS：`app/static/css/assistant-widget.css` 的中央定位、約 80% viewport 尺寸、wide 背景暗化/模糊 backdrop、transform 動畫與 mobile specificity 覆蓋。
- i18n：`app/static/locales/en-US.json`、`zh-CN.json`、`zh-TW.json`。
- Tests：`app/testsuite/js/assistant-widget.test.mjs`。
- OpenSpec：修改 `assistant-widget-ui` 的面板尺寸需求。
- Compatibility：canonical key `tcrt_assistant_panel_size_mode` 優先；既有 `compact`/`expanded` 值遷移為 `narrow`/`medium`，legacy mirror 讓舊版遇到 `wide` 時安全回到 compact。
