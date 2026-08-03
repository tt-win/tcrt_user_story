// Test Run execution deep-link team routing:
//   node --test app/testsuite/js/test-run-execution-deep-link.test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(
  path.join(here, '../../static/js/test-run-execution/utils.js'),
  'utf-8',
);
const initSource = readFileSync(
  path.join(here, '../../static/js/test-run-execution/init.js'),
  'utf-8',
);

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function createHarness({ currentTeam, teams, responseOk = true }) {
  const fetchCalls = [];
  const setCalls = [];
  let selectedTeam = currentTeam;
  let badgeUpdates = 0;
  const appUtils = {
    getCurrentTeam: () => selectedTeam,
    setCurrentTeam(team) {
      selectedTeam = team;
      setCalls.push(team);
    },
    updateTeamNameBadge() {
      badgeUpdates += 1;
    },
  };
  const context = vm.createContext({
    AppUtils: appUtils,
    URL,
    URLSearchParams,
    console: { warn() {} },
    document: {},
    navigator: {},
    window: {
      AuthClient: {
        async fetch(url) {
          fetchCalls.push(url);
          return {
            ok: responseOk,
            async json() {
              return teams;
            },
          };
        },
      },
      location: { origin: 'https://test.example' },
    },
  });

  vm.runInContext(source, context);
  return {
    context,
    fetchCalls,
    get badgeUpdates() {
      return badgeUpdates;
    },
    get selectedTeam() {
      return selectedTeam;
    },
    setCalls,
  };
}

function createStartupHarness() {
  const fetchCalls = [];
  const loadTeamIds = [];
  let domContentLoaded;
  let selectedTeam = { id: 1, name: 'Current Team' };
  const element = { dataset: {}, addEventListener() {} };
  const appUtils = {
    getCurrentTeam: () => selectedTeam,
    setCurrentTeam(team) {
      selectedTeam = team;
    },
    updateTeamNameBadge() {},
    showError(message) {
      throw new Error(message);
    },
  };
  const context = vm.createContext({
    AppUtils: appUtils,
    URL,
    URLSearchParams,
    applyTestRunExecutionPermissions: async () => {},
    bindBugTicketEvents() {},
    bindEventListeners() {},
    bootstrap: { Modal: class {} },
    console: { debug() {}, error() {}, warn() {} },
    document: {
      addEventListener(event, callback) {
        if (event === 'DOMContentLoaded') domContentLoaded = callback;
      },
      getElementById() {
        return element;
      },
      querySelector() {
        return null;
      },
    },
    handleBatchModifyConfirm() {},
    handleRestartConfirm() {},
    initializeExecutionFilters() {},
    loadTestRunConfig() {
      loadTeamIds.push(context.currentTeamId);
    },
    setTimeout() {
      return 0;
    },
    setupQuickSearch_TR() {},
    testRunConfig: null,
    toggleBatchAssigneeInput() {},
    toggleBatchCommentInput() {},
    toggleBatchResultSelect() {},
    window: {
      AuthClient: {
        async fetch(url) {
          fetchCalls.push(url);
          return {
            ok: true,
            async json() {
              return [
                { id: 1, name: 'Current Team' },
                { id: 7, name: 'Linked Team' },
              ];
            },
          };
        },
        on() {},
      },
      addEventListener() {},
      location: {
        href: 'https://test.example/test-run-execution?config_id=1688&team_id=7',
        search: '?config_id=1688&team_id=7',
      },
    },
  });

  vm.runInContext(source, context);
  vm.runInContext(initSource, context);
  context.bindEventListeners = () => {};
  return {
    fetchCalls,
    loadTeamIds,
    run: () => domContentLoaded(),
    get selectedTeam() {
      return selectedTeam;
    },
  };
}

test('execution startup loads a cross-team link with its URL team', async () => {
  const harness = createStartupHarness();

  await harness.run();

  assert.deepEqual(harness.fetchCalls, ['/api/teams/']);
  assert.deepEqual(plain(harness.selectedTeam), { id: 7, name: 'Linked Team' });
  assert.deepEqual(harness.loadTeamIds, [7]);
});

test('team-qualified execution link replaces a different selected team', async () => {
  const harness = createHarness({
    currentTeam: { id: 1, name: 'Current Team' },
    teams: [
      { id: 1, name: 'Current Team' },
      { id: 7, name: 'Linked Team' },
    ],
  });

  const resolved = await harness.context.resolveTeamFromUrl_TRE('7');

  assert.deepEqual(plain(resolved), { id: 7, name: 'Linked Team' });
  assert.deepEqual(harness.fetchCalls, ['/api/teams/']);
  assert.deepEqual(plain(harness.setCalls), [{ id: 7, name: 'Linked Team' }]);
  assert.deepEqual(plain(harness.selectedTeam), { id: 7, name: 'Linked Team' });
  assert.equal(harness.badgeUpdates, 1);
});

test('unavailable execution-link team leaves the selected team unchanged', async () => {
  const harness = createHarness({
    currentTeam: { id: 1, name: 'Current Team' },
    teams: [{ id: 1, name: 'Current Team' }],
  });

  const resolved = await harness.context.resolveTeamFromUrl_TRE('7');

  assert.equal(resolved, null);
  assert.deepEqual(harness.fetchCalls, ['/api/teams/']);
  assert.deepEqual(harness.setCalls, []);
  assert.deepEqual(plain(harness.selectedTeam), { id: 1, name: 'Current Team' });
});
