// Team-scoped page registry — single source of truth for the team badge navigation dropdown.
// When adding a new team-scoped page, add an entry here.
const TEAM_NAV_PAGES = [
    {
        key: 'test-cases',
        iconClass: 'fa-list-check',
        i18nKey: 'navigation.testCaseManagement',
        pathTemplate: '/test-case-management',
    },
    {
        key: 'test-runs',
        iconClass: 'fa-play-circle',
        i18nKey: 'navigation.testRunManagement',
        pathTemplate: '/test-run-management',
    },
    {
        key: 'automation-hub',
        iconClass: 'fa-robot',
        i18nKey: 'navigation.automationHub',
        pathTemplate: '/automation-hub',
        condition: async () => {
            if (typeof AppUtils === 'undefined') return true;
            return AppUtils.getAutomationHubEntryEnabled();
        },
    },
    {
        key: 'user-story-map',
        iconClass: 'fa-map',
        i18nKey: 'navigation.userStoryMap',
        pathTemplate: '/user-story-map/{team_id}',
    },
];
