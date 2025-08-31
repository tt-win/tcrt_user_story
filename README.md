Test Case Repository Web Tool
================================

A comprehensive FastAPI + Bootstrap web application for managing Test Cases, executing Test Runs, and tracking Bug Tickets. Features enterprise-grade JIRA integration, real-time status updates, and full internationalization (zh-TW / en-US).

Features
- **Test Case Management**: Smart search, advanced filtering, inline editing, batch operations
- **Test Run Management**: Complete lifecycle management with flexible Test Case assignment
- **Test Run Execution**:
  - Real-time result tracking with comprehensive history
  - Restart flow with multiple modes (all/failed/pending) and custom naming
  - Advanced batch operations (modify assignee/results, bulk delete)
  - Integrated assignee selector with team management
- **Bug Tickets Management** ✨ NEW:
  - Full CRUD operations for bug ticket tracking per test case
  - JIRA integration with real-time status updates
  - Bug Tickets Summary with advanced status filtering
  - Interactive tooltips with ticket details and direct JIRA links
- **JIRA Integration**:
  - Real-time ticket information fetching
  - Status synchronization and updates
  - Hover previews in Test Case Details
  - Direct links to JIRA tickets
- **Internationalization**: Complete zh-TW and en-US support with runtime language switching

Getting Started
1) Requirements
- Python 3.10+
- pip

2) Install dependencies
```
pip install -r requirements.txt
```

3) (Optional) Configure Lark/test-case sources
- See `config.yaml.example` and `README_DATABASE.md` for context.
- Local mode works out of the box with SQLite files in repo root (e.g., `test_case_repo.db`).

4) Run the app
```
uvicorn app.main:app --reload --port 9999
```
Then open http://localhost:9999

Project Structure (high-level)
- `app/main.py`: FastAPI app + page routes.
- `app/api/`: REST endpoints (teams, test cases, test run configs, items, attachments, etc.).
- `app/templates/`: Jinja HTML templates for pages.
- `app/static/`: CSS/JS assets and i18n JSON files.
- `app/models/`: Pydantic and SQLAlchemy models.
- `app/database.py`: DB engine and session.

Key Endpoints
- **Test Run Configs**: `/api/teams/{team_id}/test-run-configs`
  - `POST /{config_id}/restart`: Clone a new Test Run from an existing config
    - Body: `{ "mode": "all" | "failed" | "pending", "name"?: "Rerun - Original" }`
    - Response: `{ success, mode, new_config_id, created_count }`
- **Test Run Items**: `/api/teams/{team_id}/test-run-configs/{config_id}/items`
  - `GET /`: List items with sorting and filtering
  - `PUT /{item_id}`: Update assignee/result with history tracking
  - `POST /batch-update-results`: Batch update operations
- **Bug Tickets**: `/api/teams/{team_id}/test-run-configs/{config_id}/items`
  - `POST /{item_id}/bug-tickets`: Add bug ticket to test case
  - `DELETE /{item_id}/bug-tickets/{ticket_number}`: Remove bug ticket
  - `GET /bug-tickets/summary`: Get aggregated bug tickets summary with status
- **JIRA Integration**: `/api/jira`
  - `GET /ticket/{ticket_key}`: Fetch ticket details with real-time status
  - `GET /connection-test`: Test JIRA connectivity
  - `GET /projects`: List available JIRA projects

Notable UI Features
- **Unified Interface**: Consistent batch action bars across Test Case and Test Run management
- **Smart Navigation**: Ascending Test Case Number sorting for logical flow
- **Modal Management**: Advanced z-index handling for multiple modal layers
- **Bug Tickets Integration**:
  - Summary modal with status filtering (All, Open, To Do, In Progress, Resolved, Scheduled, Closed)
  - Real-time JIRA status updates with refresh functionality
  - Interactive tooltips in Test Case Details with hover previews
- **Internationalization**: Complete runtime language switching with persistent preferences
- **Advanced Interactions**: 
  - Restart modal with custom naming (defaults to "Rerun - {original name}")
  - Batch operations with comprehensive validation and feedback

Development Notes
- **Database**: SQLite with auto-creation on startup (see `app/models/database_models.py`)
- **Logging**: Console output; configure via `logging.basicConfig` in `app/main.py`
- **JIRA Configuration**: Set up JIRA credentials in `config.yaml` for Bug Tickets functionality
- **Frontend Architecture**: Bootstrap 5 + vanilla JavaScript with modular components
- **Testing**: Run with `pytest -q` (add tests under `tests/` directory)

## Recent Updates (2025)
- ✅ **Bug Tickets Management**: Complete JIRA integration with CRUD operations
- ✅ **Advanced Modal System**: Multi-layer modal management with proper z-index handling  
- ✅ **JIRA Tooltips**: Interactive hover previews with real-time ticket information
- ✅ **UI/UX Improvements**: Status filtering, layout optimizations, enhanced user interactions
- ✅ **Internationalization**: Full i18n support for all new Bug Tickets features

License
- Internal project; no public license headers added.
