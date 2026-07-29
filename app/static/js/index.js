(() => {
    'use strict';

    const state = {
        dashboard: null,
        currentUser: null,
        requestId: 0,
        loading: false,
        preferredTeam: { userId: null, teamId: null },
        preferenceModalTeams: [],
        preferenceCandidateId: null,
    };

    const MAX_VISIBLE_ACTIVITY_ITEMS = 5;
    const SVG_NAMESPACE = 'http://www.w3.org/2000/svg';

    const root = () => document.getElementById('dashboard-root');
    const content = () => document.getElementById('dashboard-content');
    const loading = () => document.getElementById('dashboard-loading');
    const error = () => document.getElementById('dashboard-error');

    function t(key, fallback, params = {}) {
        return window.i18n?.t ? window.i18n.t(key, params, fallback) : fallback;
    }

    function element(tag, className = '', textValue = null) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (textValue !== null) node.textContent = String(textValue);
        return node;
    }

    function svgElement(tag, className = '') {
        const node = document.createElementNS(SVG_NAMESPACE, tag);
        if (className) node.setAttribute('class', className);
        return node;
    }

    function icon(name, extraClass = '') {
        return element('i', `fas ${name}${extraClass ? ` ${extraClass}` : ''}`);
    }

    function button(label, variant = 'secondary', onClick = null, iconName = null) {
        const node = element('button', `btn btn-${variant} btn-sm`);
        node.type = 'button';
        if (iconName) node.append(icon(iconName, 'me-1'));
        node.append(document.createTextNode(label));
        if (onClick) node.addEventListener('click', onClick);
        return node;
    }

    function card(title, iconName = null) {
        const node = element('section', 'card');
        const header = element(
            'div',
            'card-header bg-light d-flex align-items-center justify-content-between flex-wrap gap-2'
        );
        const heading = element('h6', 'mb-0');
        if (iconName) heading.append(icon(iconName, 'text-primary me-1'));
        heading.append(document.createTextNode(title));
        header.append(heading);
        const body = element('div', 'card-body');
        node.append(header, body);
        return { node, header, body };
    }

    function compactCard(title, iconName, className) {
        const node = element('section', `card dashboard-compact-card ${className}`);
        const body = element('div', 'card-body dashboard-compact-card-body');
        const heading = element('h6', 'dashboard-compact-card-title mb-0');
        heading.append(icon(iconName, 'text-primary me-1'));
        heading.append(document.createTextNode(title));
        body.append(heading);
        node.append(body);
        return { node, body };
    }

    function sectionState(section) {
        if (!section || section.state === 'ready') return null;
        const node = element('div', 'dashboard-section-state');
        const isPartial = section.state === 'partial';
        node.append(icon(isPartial ? 'fa-circle-info' : 'fa-circle-exclamation'));
        node.append(document.createTextNode(
            isPartial
                ? t('dashboard.partial', '部分近期資料暫時無法顯示。')
                : t('dashboard.unavailable', '此區塊目前無法取得資料。')
        ));
        return node;
    }

    function emptyState(message) {
        const node = element('div', 'dashboard-empty');
        node.append(icon('fa-inbox', 'me-1'));
        node.append(document.createTextNode(message));
        return node;
    }

    function formatDate(value) {
        if (!value) return t('common.notSet', '未設定');
        return window.AppUtils?.formatDate
            ? window.AppUtils.formatDate(value, 'datetime')
            : String(value);
    }

    function resultBadge(result, classOverride = null) {
        const normalized = String(result || '').toLowerCase().replace(/\s+/g, '-');
        const classMap = {
            passed: 'bg-success',
            success: 'bg-success',
            failed: 'bg-danger',
            error: 'bg-danger',
            retest: 'bg-warning',
            'not-available': 'bg-warning',
            pending: 'bg-secondary',
            'not-required': 'bg-info',
            skip: 'bg-info',
            running: 'bg-info',
            skipped: 'bg-info',
        };
        return element(
            'span',
            `badge ${classOverride || classMap[normalized] || 'bg-secondary'} dashboard-status-badge`,
            result || t('dashboard.notExecuted', '尚未執行')
        );
    }

    function outcomePresentation(result) {
        const normalized = String(result || '').toLowerCase().replace(/\s+/g, '-');
        const presentations = {
            passed: {
                fallback: 'Passed',
                i18nKey: 'testRun.passed',
                order: 0,
                slug: 'passed',
            },
            failed: {
                fallback: 'Failed',
                i18nKey: 'testRun.failed',
                order: 1,
                slug: 'failed',
            },
            retest: {
                fallback: 'Retest',
                i18nKey: 'testRun.retest',
                order: 2,
                slug: 'retest',
            },
            'not-available': {
                fallback: 'Not Available',
                i18nKey: 'testRun.notAvailable',
                order: 3,
                slug: 'not-available',
            },
            'not-required': {
                fallback: 'Not Required',
                i18nKey: 'testRun.notRequired',
                order: 4,
                slug: 'not-required',
            },
            skip: {
                fallback: 'Skip',
                i18nKey: 'testRun.skip',
                order: 5,
                slug: 'skip',
            },
        };
        const presentation = presentations[normalized];
        if (!presentation) {
            return {
                label: t('dashboard.unknownOutcome', 'Unknown outcome'),
                order: 99,
                slug: 'other',
            };
        }
        return {
            ...presentation,
            label: t(presentation.i18nKey, presentation.fallback),
        };
    }

    function setOutcomeCircleGeometry(circle) {
        circle.setAttribute('cx', '21');
        circle.setAttribute('cy', '21');
        circle.setAttribute('r', '15.9155');
        circle.setAttribute('pathLength', '100');
    }

    function userStorageKey(userId) {
        return `tcrt:dashboard:preferred-team:${userId}`;
    }

    function hasStoredAuthSession() {
        try {
            return Boolean(
                window.localStorage.getItem('access_token')
                && window.localStorage.getItem('token_expiry')
            );
        } catch (_) {
            return false;
        }
    }

    function normalizeAuthUser(user) {
        if (!user || typeof user !== 'object') return null;
        const userId = user.id ?? user.user_id;
        if (userId === null || userId === undefined || userId === '') return null;
        return user.id === userId ? user : { ...user, id: userId };
    }

    function preferredDisplayName(authUser, dashboardUser) {
        const values = [authUser?.lark_name, authUser?.username, dashboardUser?.display_name];
        const displayName = values
            .map((value) => String(value || '').trim())
            .find(Boolean);
        return displayName || String(dashboardUser?.id || '');
    }

    function readPreferredTeam(userId, teams) {
        if (
            String(state.preferredTeam.userId) === String(userId)
            && teams.some((team) => team.id === state.preferredTeam.teamId)
        ) {
            return state.preferredTeam.teamId;
        }
        state.preferredTeam = { userId: null, teamId: null };
        const key = userStorageKey(userId);
        try {
            const raw = window.localStorage.getItem(key);
            if (!raw) return null;
            if (!/^[1-9]\d*$/.test(raw)) {
                window.localStorage.removeItem(key);
                return null;
            }
            const teamId = Number(raw);
            if (!teams.some((team) => team.id === teamId)) {
                window.localStorage.removeItem(key);
                return null;
            }
            state.preferredTeam = { userId, teamId };
            return teamId;
        } catch (_) {
            return null;
        }
    }

    function savePreferredTeam(userId, teamId) {
        state.preferredTeam = { userId, teamId };
        try {
            window.localStorage.setItem(userStorageKey(userId), String(teamId));
            return true;
        } catch (_) {
            window.AppUtils?.showWarning?.(t('dashboard.preferenceUnavailable', '無法儲存團隊偏好。'));
            return false;
        }
    }

    function preferredTeamFrom(teams) {
        const preferredId = readPreferredTeam(state.dashboard.current_user.id, teams);
        return teams.find((team) => team.id === preferredId) || null;
    }

    function updatePreferenceCandidate(teamId) {
        state.preferenceCandidateId = teamId;
        document.querySelectorAll('#dashboard-preference-options [data-team-id]').forEach((option) => {
            const selected = Number(option.dataset.teamId) === teamId;
            option.classList.toggle('dashboard-preference-option-selected', selected);
            option.setAttribute('aria-checked', String(selected));
            const optionIcon = option.querySelector('.dashboard-preference-option-icon');
            if (optionIcon) {
                optionIcon.classList.toggle('fa-circle', !selected);
                optionIcon.classList.toggle('fa-circle-check', selected);
            }
        });
        const saveButton = document.getElementById('dashboard-preference-save');
        if (saveButton) saveButton.disabled = !teamId;
    }

    function openPreferredTeamModal(teams, required = false) {
        const modalElement = document.getElementById('dashboard-preference-modal');
        const options = document.getElementById('dashboard-preference-options');
        if (!modalElement || !options || !window.bootstrap?.Modal || !teams.length) return;

        state.preferenceModalTeams = [...teams];
        const currentTeam = preferredTeamFrom(teams);
        state.preferenceCandidateId = currentTeam?.id || null;
        document.getElementById('dashboard-preference-close')?.classList.toggle('d-none', required);
        document.getElementById('dashboard-preference-cancel')?.classList.toggle('d-none', required);
        const intro = document.getElementById('dashboard-preference-intro');
        if (intro) {
            intro.dataset.i18n = required
                ? 'dashboard.preferenceFirstVisit'
                : 'dashboard.preferenceChangeIntro';
            intro.textContent = required
                ? t('dashboard.preferenceFirstVisit', '請先選擇常用團隊；之後可隨時修改。')
                : t('dashboard.preferenceChangeIntro', '選擇要顯示在首頁的團隊。');
        }

        options.replaceChildren();
        teams.forEach((team) => {
            const option = element('button', 'dashboard-preference-option');
            option.type = 'button';
            option.dataset.teamId = String(team.id);
            option.setAttribute('role', 'radio');
            option.append(icon('fa-circle', 'dashboard-preference-option-icon'));
            option.append(element('span', 'fw-semibold', team.name));
            option.addEventListener('click', () => updatePreferenceCandidate(team.id));
            options.append(option);
        });
        updatePreferenceCandidate(state.preferenceCandidateId);
        window.bootstrap.Modal.getOrCreateInstance(modalElement, {
            backdrop: 'static',
            keyboard: false,
        }).show();
    }

    function navigateWithTeam(team, href) {
        if (!team || !href) return;
        if (window.AppUtils?.setCurrentTeam) {
            window.AppUtils.setCurrentTeam({ id: team.id, name: team.name });
        }
        window.location.href = href;
    }

    function bindTeamAnchor(anchor, team, href) {
        anchor.href = href;
        anchor.addEventListener('click', (event) => {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
                return;
            }
            event.preventDefault();
            navigateWithTeam(team, href);
        });
    }

    function renderHero(parent, isSystem) {
        const hero = element('section', 'dashboard-hero');
        const heroContent = element('div', 'dashboard-hero-content');
        const greeting = isSystem
            ? t('dashboard.systemGreeting', '系統管理工作台')
            : t('dashboard.greeting', '你好，{name}', { name: state.dashboard.current_user.display_name });
        heroContent.append(element('h2', 'h4 mb-1', greeting));
        heroContent.append(element(
            'p',
            'mb-0 text-muted',
            isSystem
                ? t('dashboard.systemIntro', '檢視可安全呈現的系統狀態與管理入口。')
                : t('dashboard.intro', '從目前工作、近期成果與常用入口繼續。')
        ));
        hero.append(heroContent);
        parent.append(hero);
    }

    function renderTeams(parent, section) {
        const view = compactCard(
            t('dashboard.teams', '偏好團隊'),
            'fa-star',
            'dashboard-preferred-team-card'
        );
        const stateNotice = sectionState(section);
        if (stateNotice) {
            stateNotice.classList.add('dashboard-compact-state');
            view.body.append(stateNotice);
        }
        const items = section?.items || [];
        if (!items.length) {
            view.body.append(element(
                'div',
                'dashboard-compact-empty',
                t('dashboard.noTeams', '目前沒有可用的團隊。')
            ));
            parent.append(view.node);
            return;
        }
        const preferredTeam = preferredTeamFrom(items);
        if (!preferredTeam) {
            view.body.append(element(
                'div',
                'dashboard-compact-empty',
                t('dashboard.noPreferredTeam', '請先選擇要顯示在首頁的偏好團隊。')
            ));
            view.body.append(button(
                t('dashboard.choosePreferred', '選擇偏好'),
                'secondary',
                () => openPreferredTeamModal(items, true),
                'fa-star'
            ));
            parent.append(view.node);
            const userId = state.dashboard.current_user.id;
            window.setTimeout(() => {
                if (String(state.dashboard?.current_user?.id) !== String(userId)) return;
                const modalElement = document.getElementById('dashboard-preference-modal');
                if (
                    !modalElement?.classList.contains('show')
                    && !readPreferredTeam(userId, items)
                ) {
                    openPreferredTeamModal(items, true);
                }
            }, 0);
            return;
        }
        const teamName = element(
            'div',
            'dashboard-preferred-team-value',
            preferredTeam.name
        );
        teamName.title = preferredTeam.name;
        view.body.append(teamName);
        view.body.append(button(
            t('dashboard.changePreferred', '修改偏好'),
            'secondary',
            () => openPreferredTeamModal(items),
            'fa-pen'
        ));
        parent.append(view.node);
    }

    function renderResume(parent, section) {
        const view = card(t('dashboard.resume', '繼續進行'), 'fa-forward');
        view.node.classList.add('dashboard-resume-card');
        const stateNotice = sectionState(section);
        if (stateNotice) view.body.append(stateNotice);
        const items = section?.items || [];
        if (!items.length) {
            view.body.append(emptyState(t('dashboard.noResume', '沒有可繼續的近期工作。')));
            parent.append(view.node);
            return;
        }
        const list = element('div', 'dashboard-resume-list');
        items.forEach((item) => {
            const kind = String(item.kind || '');
            const presentations = {
                test_run: {
                    iconName: 'fa-play',
                    typeLabel: t('dashboard.resumeTypeTestRun', 'Test Run'),
                    name: String(item.run?.name || ''),
                    actionLabel: t('dashboard.returnToRun', '回到 Test Run'),
                },
                test_case: {
                    iconName: 'fa-list-check',
                    typeLabel: t('dashboard.resumeTypeTestCase', 'Test Case'),
                    name: String(item.resource?.id || t('dashboard.resumeTypeTestCase', 'Test Case')),
                    actionLabel: t('dashboard.returnToTestCase', '回到 Test Case'),
                },
                user_story_map: {
                    iconName: 'fa-project-diagram',
                    typeLabel: t('dashboard.resumeTypeUserStoryMap', 'User Story Map'),
                    name: t('dashboard.userStoryMapResource', 'Map #{id}', {
                        id: String(item.resource?.id || ''),
                    }),
                    actionLabel: t('dashboard.returnToUserStoryMap', '回到 User Story Map'),
                },
                automation_hub: {
                    iconName: 'fa-robot',
                    typeLabel: t('dashboard.resumeTypeAutomationHub', 'Automation Hub'),
                    name: t('dashboard.automationHubWork', 'Automation Hub'),
                    actionLabel: t('dashboard.returnToAutomationHub', '回到 Automation Hub'),
                },
            };
            const presentation = presentations[kind];
            if (!presentation || !item.team || !item.link) return;
            const entry = element('article', 'dashboard-resume-run');
            const runMark = element('span', 'dashboard-resume-run-mark');
            runMark.setAttribute('aria-hidden', 'true');
            runMark.append(icon(presentation.iconName));

            const main = element('div', 'dashboard-resume-run-main');
            main.append(element('span', 'dashboard-resume-run-kind', presentation.typeLabel));
            main.append(element('span', 'dashboard-resume-run-name', presentation.name));
            const meta = element('div', 'dashboard-resume-run-meta');
            const team = element('span', 'dashboard-resume-run-meta-item');
            team.append(icon('fa-users', 'me-1'));
            team.append(document.createTextNode(item.team.name));
            team.title = item.team.name;
            const lastWorked = element('span', 'dashboard-resume-run-meta-item');
            lastWorked.append(icon('fa-clock-rotate-left', 'me-1'));
            const lastWorkedAt = formatDate(item.last_activity_at);
            const lastWorkedLabel = t(
                'dashboard.lastWorked',
                '上次操作 {time}',
                { time: lastWorkedAt }
            );
            lastWorked.append(document.createTextNode(lastWorkedAt));
            lastWorked.title = lastWorkedLabel;
            meta.append(team, lastWorked);
            main.append(meta);

            const returnButton = element(
                'button',
                'btn btn-primary btn-sm dashboard-resume-run-action'
            );
            returnButton.type = 'button';
            returnButton.setAttribute('aria-label', presentation.actionLabel);
            returnButton.title = presentation.actionLabel;
            returnButton.append(
                icon('fa-arrow-right', 'me-1 dashboard-resume-run-action-icon'),
                element('span', 'dashboard-resume-run-action-label', presentation.actionLabel)
            );
            returnButton.addEventListener('click', () => navigateWithTeam(item.team, item.link));
            entry.append(runMark, main, returnButton);
            list.append(entry);
        });
        view.body.append(list);
        parent.append(view.node);
    }

    function renderAssigned(parent, section) {
        const view = card(t('dashboard.assigned', '指派給我的 Test Run'), 'fa-list-check');
        view.node.classList.add('dashboard-assigned-card');
        const stateNotice = sectionState(section);
        if (stateNotice) view.body.append(stateNotice);
        const runs = section?.items || [];
        if (!runs.length) {
            view.body.append(emptyState(t('dashboard.noAssigned', '目前沒有指派給你的 Test Run。')));
            parent.append(view.node);
            return;
        }
        const list = element('div', 'dashboard-assigned-runs');
        runs.forEach((item) => {
            const itemCount = Math.max(0, Number(item.item_count) || 0);
            const execute = item.action_mode === 'execute';
            const previewItems = Array.isArray(item.preview_items) ? item.preview_items : [];
            const disclosure = element('details', 'dashboard-assigned-run');
            const summary = element('summary', 'dashboard-assigned-run-summary');
            const updateSummaryState = () => {
                const key = disclosure.open
                    ? 'dashboard.collapseAssignedRun'
                    : 'dashboard.expandAssignedRun';
                const fallback = disclosure.open
                    ? '收合 Test Run {name} 預覽'
                    : '展開 Test Run {name} 預覽，共 {count} 個指派項目';
                summary.setAttribute('aria-label', t(key, fallback, {
                    name: item.run.name,
                    count: itemCount,
                }));
                summary.setAttribute('aria-expanded', String(disclosure.open));
            };
            summary.append(icon('fa-chevron-right', 'dashboard-assigned-run-chevron'));
            summary.append(element('span', 'dashboard-assigned-run-name', item.run.name));
            summary.append(element(
                'span',
                'badge bg-secondary dashboard-assigned-run-count',
                t('dashboard.assignedItemCount', '項目 · {count}', { count: itemCount })
            ));
            disclosure.addEventListener('toggle', () => {
                updateSummaryState();
            });
            updateSummaryState();

            const preview = element('div', 'dashboard-assigned-run-preview');
            if (previewItems.length) {
                const previewList = element('div', 'dashboard-assigned-preview-list');
                previewItems.forEach((previewItem) => {
                    const caseNumber = String(previewItem.test_case?.number || '');
                    const caseTitle = String(previewItem.test_case?.title || '');
                    const itemLink = element('a', 'dashboard-assigned-preview-link');
                    bindTeamAnchor(itemLink, item.team, previewItem.item_link);
                    itemLink.setAttribute('aria-label', t(
                        'dashboard.openAssignedItem',
                        '開啟指派項目 {number}',
                        { number: caseNumber }
                    ));
                    const itemMain = element('span', 'dashboard-assigned-preview-main');
                    itemMain.append(element(
                        'span',
                        'dashboard-assigned-preview-number',
                        caseNumber
                    ));
                    if (caseTitle) {
                        itemMain.append(element(
                            'span',
                            'dashboard-assigned-preview-title',
                            caseTitle
                        ));
                    }
                    itemLink.append(itemMain, resultBadge(previewItem.test_result));
                    previewList.append(itemLink);
                });
                preview.append(previewList);
            }

            const footer = element('div', 'dashboard-assigned-run-footer');
            const openRun = element('a', 'btn btn-primary btn-sm');
            bindTeamAnchor(openRun, item.team, item.run_link);
            openRun.append(icon(execute ? 'fa-play' : 'fa-eye', 'me-1'));
            openRun.append(document.createTextNode(t('dashboard.openTestRun', '開啟 Test Run')));
            footer.append(openRun);
            footer.append(element(
                'span',
                'dashboard-team-meta',
                t('dashboard.assignedPreviewCount', '預覽 {shown} / {total} 個項目', {
                    shown: previewItems.length,
                    total: itemCount,
                })
            ));
            preview.append(footer);
            disclosure.append(summary, preview);
            list.append(disclosure);
        });
        view.body.append(list);
        parent.append(view.node);
    }

    function activityLabel(item) {
        return item.kind === 'execution'
            ? t('dashboard.executionUpdated', '更新了測試執行結果')
            : t('dashboard.commentActivity', '新增了測試項目活動');
    }

    function activitySummaryEntry(item) {
        const entry = element('div', 'dashboard-activity-summary-entry');
        const mark = element('span', 'dashboard-activity-summary-mark');
        mark.setAttribute('aria-hidden', 'true');
        mark.append(icon(item.kind === 'execution' ? 'fa-check' : 'fa-comment'));
        entry.append(mark, element('div', 'dashboard-activity-summary-label', activityLabel(item)));
        if (item.test_result) entry.append(resultBadge(item.test_result));
        entry.append(element('time', 'dashboard-activity-summary-time', formatDate(item.timestamp)));
        return entry;
    }

    function activityDetailEntry(item) {
        const entry = element('tr', 'dashboard-activity-detail-entry');
        const eventCell = element('td', 'dashboard-activity-detail-event');
        const eventMain = element('span', 'dashboard-activity-detail-event-main');
        const mark = element('span', 'dashboard-activity-detail-mark');
        mark.setAttribute('aria-hidden', 'true');
        mark.append(icon(item.kind === 'execution' ? 'fa-check' : 'fa-comment'));
        eventMain.append(
            mark,
            element('strong', 'dashboard-activity-detail-title', activityLabel(item))
        );
        eventCell.append(eventMain);

        const contextText = [item.team?.name, item.run?.name]
            .filter(Boolean)
            .join(' · ') || t('common.notSet', '未設定');
        const contextCell = element('td', 'dashboard-activity-detail-context', contextText);
        contextCell.title = contextText;

        const testCaseText = [item.test_case?.number, item.test_case?.title]
            .filter(Boolean)
            .join(' · ') || t('common.notSet', '未設定');
        const testCaseCell = element(
            'td',
            'dashboard-activity-detail-test-case',
            testCaseText
        );
        testCaseCell.title = testCaseText;

        const resultCell = element('td', 'dashboard-activity-detail-result');
        if (item.test_result) resultCell.append(resultBadge(item.test_result));

        const timeCell = element('td', 'dashboard-activity-detail-time');
        timeCell.append(element('time', '', formatDate(item.timestamp)));

        const actionCell = element('td', 'dashboard-activity-detail-action-cell');

        if (item.team && item.run_link) {
            const openLink = element('a', 'btn btn-primary btn-sm dashboard-activity-detail-action');
            bindTeamAnchor(openLink, item.team, item.run_link);
            const actionLabel = t('dashboard.openActivityItem', '前往該 Test Run 項目');
            openLink.setAttribute('aria-label', actionLabel);
            openLink.title = actionLabel;
            openLink.append(icon('fa-arrow-right'));
            actionCell.append(openLink);
        }
        entry.append(
            eventCell,
            contextCell,
            testCaseCell,
            resultCell,
            timeCell,
            actionCell
        );
        return entry;
    }

    function openActivityModal(items) {
        const modalElement = document.getElementById('dashboard-activity-modal');
        const modalList = document.getElementById('dashboard-activity-modal-list');
        if (!modalElement || !modalList || !window.bootstrap?.Modal) return;
        modalList.replaceChildren();
        items.forEach((item) => modalList.append(activityDetailEntry(item)));
        window.bootstrap.Modal.getOrCreateInstance(modalElement).show();
    }

    function renderActivity(parent, section) {
        const view = card(t('dashboard.activity', '近期活動'), 'fa-clock-rotate-left');
        view.node.classList.add('dashboard-activity-card');
        const stateNotice = sectionState(section);
        if (stateNotice) view.body.append(stateNotice);
        const items = section?.items || [];
        if (!items.length) {
            view.body.append(emptyState(t('dashboard.noActivity', '最近沒有可顯示的活動。')));
            parent.append(view.node);
            return;
        }
        view.header.append(button(
            t('dashboard.viewAllActivity', '查看全部（{count}）', { count: items.length }),
            'secondary',
            () => openActivityModal(items),
            'fa-list'
        ));
        const list = element('div', 'dashboard-activity-list');
        items.slice(0, MAX_VISIBLE_ACTIVITY_ITEMS).forEach((item) => {
            list.append(activitySummaryEntry(item));
        });
        view.body.append(list);
        parent.append(view.node);
    }

    function renderOutcomes(parent, section) {
        const view = compactCard(
            t('dashboard.outcomes', '近七日成果'),
            'fa-chart-pie',
            'dashboard-outcome-card'
        );
        view.body.classList.add('dashboard-outcome-card-body');
        const stateNotice = sectionState(section);
        if (stateNotice) {
            view.body.classList.add('dashboard-outcome-card-body-has-state');
            stateNotice.classList.add('dashboard-outcome-state');
            view.body.append(stateNotice);
        }
        const total = Number(section?.total || 0);
        const counts = section?.counts || {};
        const entries = Object.entries(counts)
            .map(([result, count]) => ({
                count: Math.max(0, Number(count) || 0),
                presentation: outcomePresentation(result),
                result,
            }))
            .filter((entry) => entry.count > 0)
            .sort((left, right) => left.presentation.order - right.presentation.order);
        if (!total || !entries.length) {
            view.body.append(element(
                'div',
                'dashboard-compact-empty dashboard-outcome-empty',
                t('dashboard.noOutcomes', '近七日尚無可計算的成果。')
            ));
            parent.append(view.node);
            return;
        }
        const summaryText = t(
            'dashboard.outcomeTotal',
            '共 {count} 個結果',
            { count: total }
        );
        const figure = element('figure', 'dashboard-outcome-figure mb-0');
        const chart = element('div', 'dashboard-outcome-chart');
        const svg = svgElement('svg', 'dashboard-outcome-chart-svg');
        svg.setAttribute('viewBox', '0 0 42 42');
        svg.setAttribute('role', 'img');
        svg.setAttribute('aria-label', summaryText);
        const base = svgElement('circle', 'dashboard-outcome-chart-base');
        setOutcomeCircleGeometry(base);
        svg.append(base);

        let offset = 0;
        entries.forEach((entry) => {
            const percentage = (entry.count / total) * 100;
            const segment = svgElement(
                'circle',
                `dashboard-outcome-chart-segment dashboard-outcome-segment-${entry.presentation.slug}`
            );
            setOutcomeCircleGeometry(segment);
            segment.setAttribute('stroke-dasharray', `${percentage} ${100 - percentage}`);
            segment.setAttribute('stroke-dashoffset', String(-offset));
            segment.setAttribute('aria-hidden', 'true');
            svg.append(segment);
            offset += percentage;
        });

        const center = element('div', 'dashboard-outcome-chart-center');
        center.setAttribute('aria-hidden', 'true');
        center.append(element('strong', 'dashboard-outcome-total', total));
        chart.append(svg, center);
        figure.append(chart, element('figcaption', 'visually-hidden', summaryText));

        const legend = element('div', 'dashboard-outcome-legend');
        entries.forEach((entry) => {
            const item = element('div', 'dashboard-outcome-legend-item');
            const swatch = element(
                'span',
                `dashboard-outcome-swatch dashboard-outcome-swatch-${entry.presentation.slug}`
            );
            swatch.setAttribute('aria-hidden', 'true');
            item.append(
                swatch,
                element('span', 'dashboard-outcome-legend-label', entry.presentation.label),
                element('strong', 'dashboard-outcome-legend-count', entry.count)
            );
            legend.append(item);
        });
        view.body.append(figure, legend);
        parent.append(view.node);
    }

    function renderQuickActions(parent, actions, preferredTeam = null, compact = false) {
        const title = t('dashboard.quickActions', '快速功能');
        const view = compact
            ? compactCard(title, 'fa-bolt', 'dashboard-quick-actions-card')
            : card(title, 'fa-bolt');
        const grid = element(
            'div',
            compact
                ? 'dashboard-quick-actions dashboard-quick-actions-compact'
                : 'dashboard-quick-actions'
        );
        actions.forEach((action) => {
            const actionLabel = t(action.key, action.key);
            const requiresTeamPath = action.href.includes('{team_id}');
            const actionHref = requiresTeamPath && preferredTeam
                ? action.href.replace('{team_id}', encodeURIComponent(String(preferredTeam.id)))
                : action.href;
            const actionButton = element(
                'button',
                compact
                    ? 'dashboard-quick-action dashboard-quick-action-compact'
                    : 'dashboard-quick-action'
            );
            actionButton.type = 'button';
            actionButton.append(icon(action.icon, 'dashboard-quick-action-icon'));
            if (!compact) {
                actionButton.append(element(
                    'span',
                    'dashboard-quick-action-label',
                    actionLabel
                ));
            }
            actionButton.setAttribute('aria-label', actionLabel);
            actionButton.title = actionLabel;
            actionButton.disabled = requiresTeamPath && !preferredTeam;
            actionButton.addEventListener('click', () => {
                if (requiresTeamPath && !preferredTeam) return;
                if (preferredTeam) {
                    navigateWithTeam(preferredTeam, actionHref);
                    return;
                }
                window.location.href = actionHref;
            });
            grid.append(actionButton);
        });
        view.body.append(grid);
        parent.append(view.node);
    }

    function renderPersonalDashboard() {
        const target = content();
        renderHero(target, false);
        const grid = element('div', 'dashboard-grid');
        grid.classList.add('dashboard-personal-grid');
        const main = element('div', 'dashboard-column dashboard-main-column');
        const side = element('aside', 'dashboard-column dashboard-side-column');
        const sections = state.dashboard.sections || {};
        const preferredTeam = preferredTeamFrom(sections.teams?.items || []);
        renderResume(main, sections.resume);
        renderAssigned(main, sections.assigned);
        renderTeams(side, sections.teams);
        renderQuickActions(side, state.dashboard.quick_actions || [], preferredTeam, true);
        renderOutcomes(side, sections.outcomes);
        renderActivity(side, sections.activity);
        grid.append(main, side);
        target.append(grid);
    }

    function systemMetric(label, value, iconName) {
        const metric = element('div', 'dashboard-system-metric');
        const metricIcon = element('span', 'dashboard-system-metric-icon');
        metricIcon.append(icon(iconName));
        metricIcon.setAttribute('aria-hidden', 'true');
        const copy = element('span', 'dashboard-system-metric-copy');
        copy.append(
            element('strong', 'dashboard-system-metric-value', value),
            element('span', 'dashboard-system-metric-label', label)
        );
        copy.title = label;
        metric.append(metricIcon, copy);
        return metric;
    }

    function renderSystemOverview(parent, section) {
        const view = compactCard(
            t('dashboard.systemOverview', '系統摘要'),
            'fa-gauge-high',
            'dashboard-system-overview-card'
        );
        const stateNotice = sectionState(section);
        if (stateNotice) view.body.append(stateNotice);
        if (section?.state === 'ready') {
            const grid = element('div', 'dashboard-system-metrics');
            grid.append(
                systemMetric(t('dashboard.activeTeams', '啟用團隊'), section.active_teams, 'fa-users'),
                systemMetric(t('dashboard.activeUsers', '啟用帳號'), section.active_users, 'fa-user-check'),
                systemMetric(t('dashboard.activeRuns', '進行中 Test Run'), section.active_runs, 'fa-play-circle')
            );
            view.body.append(grid);
        }
        parent.append(view.node);
    }

    function renderSystemServices(parent, section) {
        const view = card(t('dashboard.scheduledServices', '排程服務'), 'fa-clock');
        view.node.classList.add('dashboard-system-services-card');
        const stateNotice = sectionState(section);
        if (stateNotice) view.body.append(stateNotice);
        const items = section?.items || [];
        if (!items.length) {
            if (!stateNotice) {
                view.body.append(emptyState(
                    t('dashboard.noScheduledServices', '沒有可顯示的排程服務。')
                ));
            }
            parent.append(view.node);
            return;
        }
        const wrapper = element(
            'div',
            'table-responsive dashboard-system-service-table-wrap'
        );
        const table = element(
            'table',
            'table table-sm table-hover align-middle mb-0 dashboard-system-service-table'
        );
        const head = element('thead', 'sticky-top');
        const headerRow = element('tr');
        [
            t('dashboard.service', '服務'),
            t('dashboard.lastRun', '最近執行'),
            t('dashboard.serviceState', '狀態'),
            t('dashboard.serviceResult', '結果'),
        ].forEach((label) => {
            const header = element('th', null, label);
            header.scope = 'col';
            headerRow.append(header);
        });
        head.append(headerRow);
        const body = element('tbody');
        items.forEach((item) => {
            const row = element('tr');
            const service = element(
                'td',
                'dashboard-system-service-name fw-semibold',
                item.service_key
            );
            service.title = item.service_key;
            const lastRun = element(
                'td',
                'dashboard-system-service-date',
                formatDate(item.last_run_at)
            );
            const serviceState = element('td');
            const stateLabel = item.running
                ? t('dashboard.running', '執行中')
                : item.enabled
                    ? t('dashboard.enabled', '已啟用')
                    : t('dashboard.disabled', '已停用');
            const stateClass = item.running
                ? 'bg-info'
                : item.enabled
                    ? 'bg-success'
                    : 'bg-secondary';
            serviceState.append(resultBadge(stateLabel, stateClass));
            const serviceResult = element('td');
            serviceResult.append(resultBadge(item.outcome));
            row.append(service, lastRun, serviceState, serviceResult);
            body.append(row);
        });
        table.append(head, body);
        wrapper.append(table);
        view.body.append(wrapper);
        parent.append(view.node);
    }

    function appendSystemHealthGroup(parent, title, iconName, section, renderReady) {
        const group = element('section', 'dashboard-system-health-group');
        const heading = element('div', 'dashboard-system-health-group-title');
        heading.append(icon(iconName, 'me-1'));
        heading.append(document.createTextNode(title));
        group.append(heading);
        const stateNotice = sectionState(section);
        if (stateNotice) group.append(stateNotice);
        if (section?.state === 'ready') {
            renderReady(group, section);
        }
        parent.append(group);
    }

    function systemHealthRow(label, value) {
        const row = element('div', 'dashboard-system-health-row');
        row.append(element('span', 'dashboard-system-health-label', label), value);
        return row;
    }

    function renderSystemHealth(parent, providerSection, attentionSection) {
        const view = card(t('dashboard.systemHealth', '系統狀態'), 'fa-heart-pulse');
        view.node.classList.add('dashboard-system-health-card');
        const health = element('div', 'dashboard-system-health');
        appendSystemHealthGroup(
            health,
            t('dashboard.attention', '需要注意'),
            'fa-triangle-exclamation',
            attentionSection,
            (group, section) => {
                const count = Number(section.count || 0);
                const countBadge = element(
                    'span',
                    `badge ${count > 0 ? 'bg-warning' : 'bg-success'} dashboard-system-attention-count`,
                    count
                );
                group.append(
                    systemHealthRow(t('dashboard.attention', '需要注意'), countBadge),
                    systemHealthRow(
                        t('dashboard.lastObserved', '最後觀察'),
                        element(
                            'span',
                            'dashboard-system-health-value',
                            formatDate(section.latest_at)
                        )
                    )
                );
            }
        );
        appendSystemHealthGroup(
            health,
            t('dashboard.providerAvailability', '整合可用性'),
            'fa-plug',
            providerSection,
            (group, section) => {
                [
                    [t('dashboard.ciProvider', 'CI Provider'), section.ci_configured],
                    [t('dashboard.resultProvider', 'Result Provider'), section.result_configured],
                ].forEach(([name, configured]) => {
                    group.append(systemHealthRow(
                        name,
                        resultBadge(
                            configured
                                ? t('dashboard.configured', '已設定')
                                : t('dashboard.notConfigured', '未設定'),
                            configured ? 'bg-success' : 'bg-secondary'
                        )
                    ));
                });
            }
        );
        view.body.append(health);
        parent.append(view.node);
    }

    function renderSystemDashboard() {
        const target = content();
        const sections = state.dashboard.sections || {};
        renderHero(target, true);
        const grid = element('div', 'dashboard-grid');
        grid.classList.add('dashboard-system-grid');
        const main = element('div', 'dashboard-column dashboard-system-main-column');
        const side = element('aside', 'dashboard-column dashboard-system-side-column');
        renderSystemOverview(main, sections.overview);
        renderSystemServices(main, sections.scheduled_services);
        renderQuickActions(side, state.dashboard.quick_actions || [], null, true);
        renderSystemHealth(side, sections.providers, sections.attention);
        grid.append(main, side);
        target.append(grid);
    }

    function renderDashboard() {
        const target = content();
        if (!target || !state.dashboard) return;
        target.replaceChildren();
        if (state.dashboard.dashboard_type === 'system_administration') {
            renderSystemDashboard();
        } else {
            renderPersonalDashboard();
        }
        target.classList.remove('d-none');
        error()?.classList.add('d-none');
        if (
            typeof window.i18n?.isReady === 'function'
            && window.i18n.isReady()
            && typeof window.i18n.retranslate === 'function'
        ) {
            window.i18n.retranslate(target);
        }
        updatePageTitle();
    }

    function showLoading() {
        loading()?.classList.remove('d-none');
        content()?.classList.add('d-none');
        error()?.classList.add('d-none');
    }

    function showError() {
        loading()?.classList.add('d-none');
        content()?.classList.add('d-none');
        error()?.classList.remove('d-none');
    }

    function clearDashboard() {
        state.dashboard = null;
        content()?.replaceChildren();
        content()?.classList.add('d-none');
        ['dashboard-preference-modal', 'dashboard-activity-modal'].forEach((modalId) => {
            const modalElement = document.getElementById(modalId);
            if (modalElement && window.bootstrap?.Modal) {
                window.bootstrap.Modal.getInstance(modalElement)?.hide();
            }
        });
        document.getElementById('dashboard-preference-options')?.replaceChildren();
        document.getElementById('dashboard-activity-modal-list')?.replaceChildren();
        state.preferenceModalTeams = [];
        state.preferenceCandidateId = null;
    }

    function guardIsCurrent(guard) {
        return window.AuthClient?.getToken?.() === guard.token
            && String(state.currentUser?.id) === String(guard.userId);
    }

    async function resolveCurrentUser() {
        const cachedUser = normalizeAuthUser(state.currentUser);
        if (cachedUser?.id) {
            state.currentUser = cachedUser;
            return cachedUser;
        }
        const user = normalizeAuthUser(await window.AuthClient?.getUserInfo?.());
        if (user?.id) state.currentUser = user;
        return user;
    }

    async function loadDashboard() {
        if (state.loading) return;
        if (!window.AuthClient) {
            showError();
            return;
        }
        const user = await resolveCurrentUser();
        const token = window.AuthClient.getToken?.();
        if (!user?.id || !token) {
            if (token) showError();
            return;
        }
        const requestId = ++state.requestId;
        const guard = { userId: user.id, token };
        state.loading = true;
        showLoading();
        try {
            const response = await window.AuthClient.fetch('/api/dashboard', { cache: 'no-store' });
            if (!guardIsCurrent(guard) || requestId !== state.requestId) return;
            if (!response.ok) throw new Error('dashboard unavailable');
            const dashboard = await response.json();
            if (!guardIsCurrent(guard) || requestId !== state.requestId) return;
            if (!dashboard?.current_user || String(dashboard.current_user.id) !== String(guard.userId)) return;
            dashboard.current_user.display_name = preferredDisplayName(user, dashboard.current_user);
            state.dashboard = dashboard;
            state.currentUser = {
                ...user,
                id: dashboard.current_user.id,
                display_name: dashboard.current_user.display_name,
            };
            loading()?.classList.add('d-none');
            renderDashboard();
        } catch (_) {
            if (guardIsCurrent(guard) && requestId === state.requestId) showError();
        } finally {
            if (requestId === state.requestId) state.loading = false;
        }
    }

    function updatePageTitle() {
        const pageTitle = state.dashboard?.dashboard_type === 'system_administration'
            ? t('dashboard.systemPageTitle', '系統管理工作台')
            : t('dashboard.pageTitle', '個人工作台');
        const siteTitle = t('navigation.title', 'Test Case Repository');
        const heading = document.getElementById('dashboard-page-title');
        if (heading) heading.textContent = pageTitle;
        document.title = `${pageTitle} - ${siteTitle}`;
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('dashboard-retry')?.addEventListener('click', () => {
            clearDashboard();
            loadDashboard();
        });
        document.getElementById('dashboard-preference-save')?.addEventListener('click', () => {
            const selectedTeam = state.preferenceModalTeams.find(
                (team) => team.id === state.preferenceCandidateId
            );
            const userId = state.dashboard?.current_user?.id;
            if (!selectedTeam || !userId) return;
            savePreferredTeam(userId, selectedTeam.id);
            const modalElement = document.getElementById('dashboard-preference-modal');
            if (modalElement && window.bootstrap?.Modal) {
                window.bootstrap.Modal.getInstance(modalElement)?.hide();
            }
            state.preferenceModalTeams = [];
            state.preferenceCandidateId = null;
            renderDashboard();
        });
        loadDashboard();
    });

    document.addEventListener('authReady', (event) => {
        state.requestId += 1;
        state.loading = false;
        state.currentUser = normalizeAuthUser(event.detail);
        if (root()) {
            clearDashboard();
            loadDashboard();
        }
    });

    document.addEventListener('tokenRefreshed', () => {
        state.requestId += 1;
        state.loading = false;
        state.currentUser = null;
        if (root()) loadDashboard();
    });

    document.addEventListener('tokenCleared', () => {
        state.currentUser = null;
        clearDashboard();
    });

    window.addEventListener('storage', (event) => {
        if (event.key !== 'access_token' && event.key !== 'token_expiry') return;
        state.requestId += 1;
        state.loading = false;
        state.currentUser = null;
        clearDashboard();
        if (event.key === 'access_token' && !event.newValue) return;
        window.setTimeout(() => {
            if (root() && hasStoredAuthSession()) loadDashboard();
        }, 0);
    });

    document.addEventListener('languageChanged', () => {
        if (!state.dashboard) {
            updatePageTitle();
            return;
        }
        const activityModal = document.getElementById('dashboard-activity-modal');
        const activityModalWasVisible = activityModal?.classList.contains('show');
        renderDashboard();
        if (activityModalWasVisible) {
            openActivityModal(state.dashboard.sections?.activity?.items || []);
        }
    });

    window.addEventListener('pageshow', (event) => {
        if (!event.persisted) return;
        state.requestId += 1;
        state.loading = false;
        clearDashboard();
        state.currentUser = null;
        loadDashboard();
    });
})();
