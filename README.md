Test Case Repository Web Tool
================================

A FastAPI + Jinja web app for managing Test Cases and executing Test Runs. It supports local storage (SQLite), Lark integration stubs, flexible Test Run management, batch actions, and full i18n (zh-TW / en-US).

Features
- Test Case Management: search, filter, view/edit, batch delete.
- Test Run Management: create, edit basic settings, add/remove Test Cases, delete.
- Test Run Execution:
  - Execute and update results with history tracking.
  - Restart flow creates a new Test Run from an existing one (modes: all/failed/pending) and lets you name it (defaults to “Rerun - {original}”).
  - Sorted by Test Case Number ascending (aligned with Test Case Management).
  - Batch modify (assignee/result) and batch delete.
- i18n: zh-TW and en-US with runtime updates (including assignee selector UI).

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

Key Endpoints (Local Mode)
- Test Run Configs: `/api/teams/{team_id}/test-run-configs`
  - `POST /{config_id}/restart`: Clone a new Test Run from an existing config.
    - Body: `{ "mode": "all" | "failed" | "pending", "name"?: "Rerun - Original" }`
    - Behavior:
      - `all`: copy all items.
      - `failed`: copy only Failed/Retest items.
      - `pending`: copy items not Passed/Failed (includes unexecuted/Retest/Not Available).
    - Response: `{ success, mode, new_config_id, created_count }`
- Test Run Items: `/api/teams/{team_id}/test-run-configs/{config_id}/items`
  - `GET /`: list items (used by execution page; client sorts by case number asc).
  - `PUT /{item_id}`: update assignee/result (+history).
  - `POST /batch-update-results`: batch update results/assignee.

Notable UI Behaviors
- Test Case Management and Test Run Execution share a unified batch actions bar style.
- Execution page item list, row numbers, and navigation follow ascending Test Case Number.
- Restart modal includes a name field; default is “Rerun - {original name}”.
- Batch Modify dialog is fully localized; the assignee selector updates text on language changes.

Development Notes
- DB is SQLite; tables are auto-created on startup (see `app/models/database_models.py`).
- Logs print to console; you can tweak `logging.basicConfig` in `app/main.py`.
- To run tests (if any are applicable in your env): `pytest -q`.

License
- Internal project; no public license headers added.
