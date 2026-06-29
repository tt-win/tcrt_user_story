const TeamNav = (() => {
    const DROPDOWN_ID = 'team-nav-dropdown-menu';

    function t(key) {
        return (window.i18n && window.i18n.isReady()) ? window.i18n.t(key) : key.split('.').pop();
    }

    function buildPath(template, teamId) {
        return template.replace('{team_id}', teamId || '');
    }

    function isActive(template, teamId) {
        const path = buildPath(template, teamId);
        // strip {team_id} placeholder pages from active check if team unknown
        if (path.includes('{')) return false;
        return window.location.pathname.startsWith(path);
    }

    let renderGen = 0;

    async function renderItems(team) {
        const ul = document.getElementById(DROPDOWN_ID);
        if (!ul) return;
        const gen = ++renderGen;

        // Resolve async visibility conditions BEFORE touching the DOM, so the
        // clear + append below runs synchronously and concurrent refresh() calls
        // can't interleave their appends (which would duplicate items).
        const visiblePages = [];
        for (const page of TEAM_NAV_PAGES) {
            if (page.condition && !(await page.condition())) continue;
            visiblePages.push(page);
        }

        // A newer render started while we awaited — abort to avoid clobbering it.
        if (gen !== renderGen) return;

        const teamId = team ? team.id : null;
        ul.innerHTML = '';
        for (const page of visiblePages) {
            const needsTeamId = page.pathTemplate.includes('{team_id}');
            const href = needsTeamId ? (teamId ? buildPath(page.pathTemplate, teamId) : '#') : page.pathTemplate;
            const active = isActive(page.pathTemplate, teamId);
            const label = t(page.i18nKey);

            const li = document.createElement('li');
            const a = document.createElement('a');
            a.className = 'dropdown-item' + (active ? ' active' : '');
            a.href = href;
            a.setAttribute('data-team-nav-key', page.key);
            a.innerHTML = `<i class="fas ${page.iconClass} me-2"></i>${label}`;
            li.appendChild(a);
            ul.appendChild(li);
        }
    }

    function updateBadge(team) {
        const wrapper = document.getElementById('team-nav-badge-wrapper');
        const text = document.getElementById('team-name-text');
        if (!wrapper || !text) return;

        if (team && team.name) {
            text.textContent = team.name;
            wrapper.classList.remove('d-none');
        } else {
            wrapper.classList.add('d-none');
        }
    }

    function refresh() {
        const team = (typeof AppUtils !== 'undefined') ? AppUtils.getCurrentTeam() : null;
        updateBadge(team);
        renderItems(team);
    }

    function init() {
        refresh();
        window.addEventListener('teamChanged', () => refresh());
        window.addEventListener('teamCleared', () => refresh());
        // re-render when i18n loads or language switches
        document.addEventListener('i18nReady', () => refresh());
        document.addEventListener('languageChanged', () => refresh());
    }

    return { init, refresh };
})();

window.TeamNav = TeamNav;

document.addEventListener('DOMContentLoaded', () => TeamNav.init());
