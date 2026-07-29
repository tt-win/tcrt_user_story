// Test Run assignee UI runtime regressions:
//   node --test app/testsuite/js/test-run-assignment.test.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(
  path.join(here, '../../static/js/test-run-execution/render.js'),
  'utf-8',
);

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function createHarness({
  selectedContact = null,
  assigneeValue = '',
  stubBatchModifyItems = true,
} = {}) {
  const warnings = [];
  const errors = [];
  const batchCalls = [];
  const elements = new Map([
    ['batchModifyAssignee', { checked: true }],
    ['batchModifyResult', { checked: false }],
    ['batchModifyComment', { checked: false }],
    ['batchResultSelect', { value: '' }],
    ['batchCommentInput', { value: '' }],
    ['batchAssigneeInput', {
      value: assigneeValue,
      _assigneeSelector: {
        displayInput: { value: assigneeValue },
        getSelectedContact: () => selectedContact,
        setValue(value) { this.displayInput.value = value; },
      },
    }],
  ]);
  const context = vm.createContext({
    window: { i18n: null },
    document: {
      addEventListener() {},
      getElementById(id) { return elements.get(id) || null; },
      querySelector() { return null; },
    },
    console: { log() {}, warn() {}, error() {} },
    navigator: {},
    URL,
    URLSearchParams,
    setTimeout,
    clearTimeout,
    AppUtils: {
      showWarning(message) { warnings.push(message); },
      showError(message) { errors.push(message); },
      showSuccess() {},
    },
    getTrePermissions: () => ({ canAssign: true, canBatchModify: true }),
    showExecutionPermissionDenied() {},
    treTranslate: (_key, fallback) => fallback,
  });
  vm.runInContext(source, context);
  context.__batchCalls = batchCalls;
  vm.runInContext(
    'batchModifyModal = { hide() { globalThis.__modalHidden = true; } };',
    context,
  );
  if (stubBatchModifyItems) {
    vm.runInContext(`
      batchModifyItems = async (modifications) => {
        globalThis.__batchCalls.push(modifications);
      };
    `, context);
  }
  return { context, warnings, errors, batchCalls, elements };
}

test('buildAssigneeUpdate preserves exactly one machine identity', () => {
  const { context } = createHarness();

  assert.deepEqual(
    plain(context.buildAssigneeUpdate({ local_user_id: 7, id: 'local:7' })),
    { assignee_user_id: 7 },
  );
  assert.deepEqual(
    plain(context.buildAssigneeUpdate({
      id: 'ou-user',
      email: 'STALE@example.com',
      name: 'Lark User',
    })),
    { assignee: { id: 'ou-user', name: 'Lark User' } },
  );
  assert.deepEqual(
    plain(context.buildAssigneeUpdate({ email: ' USER@example.com ', name: 'Email User' })),
    { assignee: { email: 'user@example.com', name: 'Email User' } },
  );
  assert.deepEqual(plain(context.buildAssigneeUpdate(' Custom User ')), {
    assignee_name: 'Custom User',
  });
  assert.deepEqual(plain(context.buildAssigneeUpdate(null)), { assignee_name: null });
});

test('batch confirm executes selected local assignee without a ReferenceError', async () => {
  const selectedContact = { local_user_id: 9, id: 'local:9', name: 'Local User' };
  const { context, warnings, errors, batchCalls } = createHarness({ selectedContact });

  await context.handleBatchModifyConfirm();

  assert.deepEqual(warnings, []);
  assert.deepEqual(errors, []);
  assert.equal(batchCalls.length, 1);
  assert.deepEqual(plain(batchCalls[0].assigneeSelection), selectedContact);
  assert.equal(context.__modalHidden, true);
});

test('batch confirm supports custom text and rejects a blank assignee', async () => {
  const custom = createHarness({ assigneeValue: 'Custom User' });
  await custom.context.handleBatchModifyConfirm();
  assert.deepEqual(custom.errors, []);
  assert.equal(custom.batchCalls.length, 1);
  assert.equal(custom.batchCalls[0].assigneeSelection, 'Custom User');

  const blank = createHarness();
  await blank.context.handleBatchModifyConfirm();
  assert.equal(blank.batchCalls.length, 0);
  assert.deepEqual(blank.errors, []);
  assert.deepEqual(blank.warnings, ['請輸入執行者姓名']);
});

test('single clear sends an explicit null assignee without throwing', async () => {
  const { context, errors } = createHarness();
  const requests = [];
  context.window.AuthClient = {
    async fetch(url, options) {
      requests.push({ url, options });
      return {
        ok: true,
        async json() {
          return {
            assignee_user_id: null,
            assignee_id: null,
            assignee_name: null,
            assignee_en_name: null,
            assignee_email: null,
          };
        },
      };
    },
  };
  context.currentTeamId = 1;
  context.currentConfigId = 2;
  context.testRunItems = [{ id: 3, assignee_name: 'Previous User' }];

  await context.updateAssignee(3, null);

  assert.deepEqual(errors, []);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/teams/1/test-run-configs/2/items/3');
  assert.deepEqual(JSON.parse(requests[0].options.body), { assignee_name: null });
});

test('batchModifyItems emits exact assignee payloads without leaking stale fields', async () => {
  const { context } = createHarness({ stubBatchModifyItems: false });
  const requests = [];
  context.window.AuthClient = {
    async fetch(url, options) {
      requests.push({ url, options });
      return {
        ok: true,
        async json() {
          return { success: true, success_count: 2, processed_count: 2 };
        },
      };
    },
  };
  context.currentTeamId = 1;
  context.currentConfigId = 2;
  context.testRunItems = [];
  context.loadTestRunItems = async () => {};
  context.updateStatistics = async () => {};
  context.updateItemSelectionUI = () => {};
  context.renderTestRunItems = () => {};
  vm.runInContext('selectedItems = new Set([11, 12]);', context);

  await context.batchModifyItems({
    modifyAssignee: true,
    modifyResult: false,
    modifyComment: false,
    assigneeSelection: { local_user_id: 9, id: 'local:9', name: 'Local User' },
    testResult: '',
    comment: '',
  });

  assert.equal(requests.length, 1);
  assert.equal(
    requests[0].url,
    '/api/teams/1/test-run-configs/2/items/batch-update-results',
  );
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    updates: [
      { id: 11, assignee_user_id: 9 },
      { id: 12, assignee_user_id: 9 },
    ],
  });

  requests.length = 0;
  vm.runInContext('selectedItems = new Set([13]);', context);
  await context.batchModifyItems({
    modifyAssignee: true,
    modifyResult: false,
    modifyComment: false,
    assigneeSelection: {
      id: 'ou-user',
      email: 'stale@example.com',
      name: 'Lark User',
    },
    testResult: '',
    comment: '',
  });
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    updates: [{ id: 13, assignee: { id: 'ou-user', name: 'Lark User' } }],
  });

  requests.length = 0;
  vm.runInContext('selectedItems = new Set([14]);', context);
  await context.batchModifyItems({
    modifyAssignee: true,
    modifyResult: false,
    modifyComment: false,
    assigneeSelection: { email: ' EMAIL@example.com ', name: 'Email User' },
    testResult: '',
    comment: '',
  });
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    updates: [{ id: 14, assignee: { email: 'email@example.com', name: 'Email User' } }],
  });

  requests.length = 0;
  vm.runInContext('selectedItems = new Set([15]);', context);
  await context.batchModifyItems({
    modifyAssignee: true,
    modifyResult: false,
    modifyComment: false,
    assigneeSelection: 'Custom User',
    testResult: '',
    comment: '',
  });
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    updates: [{ id: 15, assignee_name: 'Custom User' }],
  });

  requests.length = 0;
  vm.runInContext('selectedItems = new Set([16]);', context);
  await context.batchModifyItems({
    modifyAssignee: false,
    modifyResult: true,
    modifyComment: false,
    assigneeSelection: null,
    testResult: 'Passed',
    comment: '',
  });
  const resultOnly = JSON.parse(requests[0].options.body).updates[0];
  assert.equal(resultOnly.id, 16);
  assert.equal(resultOnly.test_result, 'Passed');
  assert.equal(Object.hasOwn(resultOnly, 'assignee_user_id'), false);
  assert.equal(Object.hasOwn(resultOnly, 'assignee'), false);
  assert.equal(Object.hasOwn(resultOnly, 'assignee_name'), false);

  requests.length = 0;
  vm.runInContext('selectedItems = new Set([17]);', context);
  await assert.rejects(
    context.batchModifyItems({
      modifyAssignee: true,
      modifyResult: false,
      modifyComment: false,
      assigneeSelection: '',
      testResult: '',
      comment: '',
    }),
    /請輸入執行者姓名/,
  );
  assert.equal(requests.length, 0);
});
