/**
 * Test Case Set 和 Section 多語系翻譯補充
 *
 * 此文件擴展全域 i18n_dict 對象，添加新功能的翻譯
 */

if (!window.i18n_dict) {
  window.i18n_dict = {};
}

// 繁體中文翻譯
if (!window.i18n_dict['zh-TW']) {
  window.i18n_dict['zh-TW'] = {};
}

Object.assign(window.i18n_dict['zh-TW'], {
  // Test Case Set
  'testCaseSet': '測試案例集合',
  'testCaseSets': '測試案例集合',
  'selectOrCreate': '選擇或建立一個測試案例集合來開始管理測試案例',
  'addSet': '新增集合',
  'createSet': '建立集合',
  'updateSet': '更新集合',
  'deleteSet': '刪除集合',
  'setName': '集合名稱',
  'setDescription': '集合描述',
  'setNameGlobalUnique': '集合名稱必須全域唯一',
  'nameAlreadyExists': '集合名稱已存在',
  'defaultSetCannotDelete': '無法刪除預設集合',
  'switchSet': '切換集合',
  'currentSet': '當前集合',
  'manageSet': '管理集合',
  'testCaseCount': '個測試案例',
  'noTestCases': '沒有測試案例',

  // Test Case Section
  'section': '區段',
  'sections': '區段',
  'testCaseSection': '測試案例區段',
  'addSection': '新增區段',
  'createSection': '建立區段',
  'updateSection': '更新區段',
  'deleteSection': '刪除區段',
  'sectionName': '區段名稱',
  'sectionDescription': '區段描述',
  'unassigned': '未分配',
  'parentSection': '父區段',
  'noSection': '沒有區段',
  'sectionList': '區段列表',
  'sectionTree': '區段樹狀結構',
  'sectionLevel': '區段層級',
  'maxSectionDepth': '區段最多 5 層',
  'moveToSection': '移動到區段',
  'selectSection': '選擇區段',
  'deleteConfirm': '確定要刪除此區段嗎？該區段下的測試案例將被移到 Unassigned。',
  'deleteSetConfirm': '確定要刪除此測試案例集合嗎？此操作無法撤銷。',

  // 跨 Set 操作
  'copyAcrossSets': '跨集合複製',
  'moveAcrossSets': '跨集合搬移',
  'copyToSet': '複製到其他集合',
  'moveToSet': '搬移到其他集合',
  'targetSet': '目標集合',
  'targetSection': '目標區段',
  'selectTargetSet': '選擇目標集合',
  'selectTargetSection': '選擇目標區段',
  'copyMode': '複製模式',
  'moveMode': '搬移模式',
  'confirmCopy': '確認複製',
  'confirmMove': '確認搬移',
  'copiedSuccessfully': '成功複製',
  'movedSuccessfully': '成功搬移',
  'copyFailed': '複製失敗',
  'moveFailed': '搬移失敗',
  'moveWarning': '搬移是永久操作，測試案例將從當前集合移除',
  'testCasesSelected': '個測試案例已選取',
  'testCasesCopied': '個測試案例已複製',
  'testCasesMoved': '個測試案例已搬移',

  // 拖拽功能
  'dragDropEnabled': '已啟用拖拽功能',
  'dragDropDisabled': '拖拽功能已停用',
  'dragTestCase': '拖拽測試案例',
  'dragSection': '拖拽區段',
  'dropHere': '放開以完成操作',

  // 批量操作
  'bulkCopy': '批量複製',
  'bulkMove': '批量搬移',
  'selectedItems': '個項目已選取',
  'noItemsSelected': '未選取任何項目',

  // 驗證和錯誤
  'nameRequired': '名稱為必填',
  'nameEmpty': '名稱不可為空',
  'pleaseSelectSet': '請先選擇集合',
  'pleaseSelectSection': '請先選擇區段',
  'loadingFailed': '載入資料失敗',
  'operationFailed': '操作失敗',
  'unknownError': '發生未知錯誤',

  // 狀態信息
  'creating': '建立中...',
  'updating': '更新中...',
  'deleting': '刪除中...',
  'loading': '載入中...',
  'saving': '儲存中...',
  'copied': '已複製',
  'moved': '已搬移'
});

// 簡體中文翻譯
if (!window.i18n_dict['zh-CN']) {
  window.i18n_dict['zh-CN'] = {};
}

Object.assign(window.i18n_dict['zh-CN'], {
  // Test Case Set
  'testCaseSet': '测试用例集合',
  'testCaseSets': '测试用例集合',
  'selectOrCreate': '选择或创建一个测试用例集合来开始管理测试用例',
  'addSet': '新增集合',
  'createSet': '创建集合',
  'updateSet': '更新集合',
  'deleteSet': '删除集合',
  'setName': '集合名称',
  'setDescription': '集合描述',
  'setNameGlobalUnique': '集合名称必须全局唯一',
  'nameAlreadyExists': '集合名称已存在',
  'defaultSetCannotDelete': '无法删除默认集合',
  'switchSet': '切换集合',
  'currentSet': '当前集合',
  'manageSet': '管理集合',
  'testCaseCount': '个测试用例',
  'noTestCases': '没有测试用例',

  // Test Case Section
  'section': '区段',
  'sections': '区段',
  'testCaseSection': '测试用例区段',
  'addSection': '新增区段',
  'createSection': '创建区段',
  'updateSection': '更新区段',
  'deleteSection': '删除区段',
  'sectionName': '区段名称',
  'sectionDescription': '区段描述',
  'unassigned': '未分配',
  'parentSection': '父区段',
  'noSection': '没有区段',
  'sectionList': '区段列表',
  'sectionTree': '区段树状结构',
  'sectionLevel': '区段层级',
  'maxSectionDepth': '区段最多 5 层',
  'moveToSection': '移动到区段',
  'selectSection': '选择区段',
  'deleteConfirm': '确定要删除此区段吗？该区段下的测试用例将被移到 Unassigned。',
  'deleteSetConfirm': '确定要删除此测试用例集合吗？此操作无法撤销。',

  // 跨 Set 操作
  'copyAcrossSets': '跨集合复制',
  'moveAcrossSets': '跨集合移动',
  'copyToSet': '复制到其他集合',
  'moveToSet': '移动到其他集合',
  'targetSet': '目标集合',
  'targetSection': '目标区段',
  'selectTargetSet': '选择目标集合',
  'selectTargetSection': '选择目标区段',
  'copyMode': '复制模式',
  'moveMode': '移动模式',
  'confirmCopy': '确认复制',
  'confirmMove': '确认移动',
  'copiedSuccessfully': '成功复制',
  'movedSuccessfully': '成功移动',
  'copyFailed': '复制失败',
  'moveFailed': '移动失败',
  'moveWarning': '移动是永久操作，测试用例将从当前集合移除',
  'testCasesSelected': '个测试用例已选取',
  'testCasesCopied': '个测试用例已复制',
  'testCasesMoved': '个测试用例已移动',

  // 拖拽功能
  'dragDropEnabled': '已启用拖拽功能',
  'dragDropDisabled': '拖拽功能已停用',
  'dragTestCase': '拖拽测试用例',
  'dragSection': '拖拽区段',
  'dropHere': '放开以完成操作',

  // 批量操作
  'bulkCopy': '批量复制',
  'bulkMove': '批量移动',
  'selectedItems': '个项目已选取',
  'noItemsSelected': '未选取任何项目',

  // 验证和错误
  'nameRequired': '名称为必填',
  'nameEmpty': '名称不可为空',
  'pleaseSelectSet': '请先选择集合',
  'pleaseSelectSection': '请先选择区段',
  'loadingFailed': '加载数据失败',
  'operationFailed': '操作失败',
  'unknownError': '发生未知错误',

  // 状态信息
  'creating': '创建中...',
  'updating': '更新中...',
  'deleting': '删除中...',
  'loading': '加载中...',
  'saving': '保存中...',
  'copied': '已复制',
  'moved': '已移动'
});

// 英文翻譯
if (!window.i18n_dict['en-US']) {
  window.i18n_dict['en-US'] = {};
}

Object.assign(window.i18n_dict['en-US'], {
  // Test Case Set
  'testCaseSet': 'Test Case Set',
  'testCaseSets': 'Test Case Sets',
  'selectOrCreate': 'Select or create a test case set to start managing test cases',
  'addSet': 'Add Set',
  'createSet': 'Create Set',
  'updateSet': 'Update Set',
  'deleteSet': 'Delete Set',
  'setName': 'Set Name',
  'setDescription': 'Set Description',
  'setNameGlobalUnique': 'Set name must be globally unique',
  'nameAlreadyExists': 'Set name already exists',
  'defaultSetCannotDelete': 'Cannot delete default set',
  'switchSet': 'Switch Set',
  'currentSet': 'Current Set',
  'manageSet': 'Manage Sets',
  'testCaseCount': 'Test Cases',
  'noTestCases': 'No Test Cases',

  // Test Case Section
  'section': 'Section',
  'sections': 'Sections',
  'testCaseSection': 'Test Case Section',
  'addSection': 'Add Section',
  'createSection': 'Create Section',
  'updateSection': 'Update Section',
  'deleteSection': 'Delete Section',
  'sectionName': 'Section Name',
  'sectionDescription': 'Section Description',
  'unassigned': 'Unassigned',
  'parentSection': 'Parent Section',
  'noSection': 'No Sections',
  'sectionList': 'Section List',
  'sectionTree': 'Section Tree',
  'sectionLevel': 'Section Level',
  'maxSectionDepth': 'Section maximum depth is 5 levels',
  'moveToSection': 'Move to Section',
  'selectSection': 'Select Section',
  'deleteConfirm': 'Are you sure you want to delete this section? Test cases in this section will be moved to Unassigned.',
  'deleteSetConfirm': 'Are you sure you want to delete this test case set? This action cannot be undone.',

  // Cross Set Operations
  'copyAcrossSets': 'Copy Across Sets',
  'moveAcrossSets': 'Move Across Sets',
  'copyToSet': 'Copy to Another Set',
  'moveToSet': 'Move to Another Set',
  'targetSet': 'Target Set',
  'targetSection': 'Target Section',
  'selectTargetSet': 'Select Target Set',
  'selectTargetSection': 'Select Target Section',
  'copyMode': 'Copy Mode',
  'moveMode': 'Move Mode',
  'confirmCopy': 'Confirm Copy',
  'confirmMove': 'Confirm Move',
  'copiedSuccessfully': 'Copied Successfully',
  'movedSuccessfully': 'Moved Successfully',
  'copyFailed': 'Copy Failed',
  'moveFailed': 'Move Failed',
  'moveWarning': 'Moving is permanent. Test cases will be removed from current set.',
  'testCasesSelected': 'Test Cases Selected',
  'testCasesCopied': 'Test Cases Copied',
  'testCasesMoved': 'Test Cases Moved',

  // Drag Drop
  'dragDropEnabled': 'Drag and Drop Enabled',
  'dragDropDisabled': 'Drag and Drop Disabled',
  'dragTestCase': 'Drag Test Case',
  'dragSection': 'Drag Section',
  'dropHere': 'Drop to complete the operation',

  // Bulk Operations
  'bulkCopy': 'Bulk Copy',
  'bulkMove': 'Bulk Move',
  'selectedItems': 'Items Selected',
  'noItemsSelected': 'No items selected',

  // Validation and Errors
  'nameRequired': 'Name is required',
  'nameEmpty': 'Name cannot be empty',
  'pleaseSelectSet': 'Please select a set first',
  'pleaseSelectSection': 'Please select a section first',
  'loadingFailed': 'Failed to load data',
  'operationFailed': 'Operation failed',
  'unknownError': 'An unknown error occurred',

  // Status
  'creating': 'Creating...',
  'updating': 'Updating...',
  'deleting': 'Deleting...',
  'loading': 'Loading...',
  'saving': 'Saving...',
  'copied': 'Copied',
  'moved': 'Moved'
});
