"""MySQL / PostgreSQL 的 db_backup dump-restore 整合測試。

預設 skip：這兩個引擎的備份/還原需要真實可連線的 server，標準
`uv run pytest app/testsuite -q` 不會啟動 docker 服務，故本檔測試在對應
環境變數未設定或本機缺少 dump/restore client 時會自動 skip。

若要實際驗證，先起 disposable 服務再帶「sync driver」的連線字串執行：

    docker compose -f docker-compose.mysql.yml up -d
    TCRT_TEST_MYSQL_URL='mysql+pymysql://tcrt:tcrt@127.0.0.1:33060/tcrt_main' \\
        uv run pytest app/testsuite/test_db_backup_server_engines.py -k mysql -q

    docker compose -f docker-compose.postgres.yml up -d
    TCRT_TEST_POSTGRES_URL='postgresql+psycopg://tcrt:tcrt@127.0.0.1:5433/tcrt_main' \\
        uv run pytest app/testsuite/test_db_backup_server_engines.py -k postgres -q
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.db_backup import create_backup, restore_backup

MYSQL_URL_ENV = "TCRT_TEST_MYSQL_URL"
POSTGRES_URL_ENV = "TCRT_TEST_POSTGRES_URL"


def _require_env_and_client(env_var: str, *client_names: str) -> str:
    url = os.getenv(env_var)
    if not url:
        pytest.skip(f"{env_var} 未設定，略過需要真實 server 的整合測試")
    missing = [name for name in client_names if shutil.which(name) is None]
    if missing:
        pytest.skip(f"本機缺少 dump/restore client：{missing}")
    return url


def _reset_widgets_table(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS widgets"))
            conn.execute(text("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name VARCHAR(50))"))
            conn.execute(text("INSERT INTO widgets (id, name) VALUES (1, 'a'), (2, 'b'), (3, 'c')"))
    finally:
        engine.dispose()


def _widget_names(database_url: str) -> set[str]:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as conn:
            return {row[0] for row in conn.execute(text("SELECT name FROM widgets"))}
    finally:
        engine.dispose()


def test_mysql_backup_and_restore_roundtrip(tmp_path: Path) -> None:
    database_url = _require_env_and_client(MYSQL_URL_ENV, "mysqldump", "mysql")
    _reset_widgets_table(database_url)

    result = create_backup(
        "main",
        database_url=database_url,
        from_revision="abc123",
        to_revision="def456",
        backup_dir=tmp_path / "backups",
    )
    assert result.path.exists()

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO widgets (id, name) VALUES (4, 'd')"))
            conn.execute(text("DELETE FROM widgets WHERE name = 'a'"))
    finally:
        engine.dispose()
    assert _widget_names(database_url) == {"b", "c", "d"}

    restore_backup(result, database_url=database_url)

    assert _widget_names(database_url) == {"a", "b", "c"}


def test_postgres_backup_and_restore_roundtrip(tmp_path: Path) -> None:
    database_url = _require_env_and_client(POSTGRES_URL_ENV, "pg_dump", "pg_restore")
    _reset_widgets_table(database_url)

    result = create_backup(
        "main",
        database_url=database_url,
        from_revision="abc123",
        to_revision="def456",
        backup_dir=tmp_path / "backups",
    )
    assert result.path.exists()

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO widgets (id, name) VALUES (4, 'd')"))
            conn.execute(text("DELETE FROM widgets WHERE name = 'a'"))
    finally:
        engine.dispose()
    assert _widget_names(database_url) == {"b", "c", "d"}

    restore_backup(result, database_url=database_url)

    assert _widget_names(database_url) == {"a", "b", "c"}
