/* ============================================================
   TEST CASE MANAGEMENT - SECTION LIST INIT
   ============================================================ */

// 立即初始化（不等待 DOMContentLoaded，以確保事件監聽器在事件發送前設置好）
if (typeof TestCaseSectionList !== 'undefined') {
    if (typeof testCaseSectionList !== 'undefined') {
        window.testCaseSectionList = testCaseSectionList;
    } else if (!window.testCaseSectionList) {
        window.testCaseSectionList = new TestCaseSectionList();
    }
} else {
    console.warn('TestCaseSectionList class not loaded');
}
