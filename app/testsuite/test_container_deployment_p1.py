"""P1 部署回歸測試（change: harden-container-deployment, sections 3–4）。

涵蓋：
- 5.2 provider 加密金鑰：有 provider 資料但缺金鑰時 bootstrap 檢查失敗。
- 5.4 背景服務 leader 鎖：跨行程互斥（唯一 leader）。
- 5.5 bootstrap 鎖：跨行程序列化（critical section 不交錯）。

leader / bootstrap 鎖在本機（SQLite）以 portalocker 檔案鎖實作；fcntl 鎖為「行程層級」，
故互斥/序列化必須以**獨立子行程**驗證（同一行程多次上鎖不會互斥）。
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

POSTGRES_URL_ENV = "TCRT_TEST_POSTGRES_URL"
_RESTRICTED_ROLE = "tcrt_test_restricted_role"
_RESTRICTED_DB = "tcrt_test_restricted_db"

# 子行程：取得 leader 鎖後 hold（讀 stdin 才釋放），讓父行程能在持鎖期間測試競爭
_LEADER_HOLDER = """
import sys
from app.runtime_locks import BackgroundLeaderLock
lk = BackgroundLeaderLock()
got = lk.try_acquire()
sys.stdout.write(("LEADER" if got else "NOT_LEADER") + "\\n")
sys.stdout.flush()
sys.stdin.readline()
lk.release()
"""

# 子行程：嘗試取得 leader 鎖，印出結果後立即退出
_LEADER_TRY = """
from app.runtime_locks import BackgroundLeaderLock
lk = BackgroundLeaderLock()
print("LEADER" if lk.try_acquire() else "NOT_LEADER")
lk.release()
"""

# 子行程：進入 bootstrap_lock，記錄 ENTER/EXIT 時間到共享檔，hold 0.6s
_BOOTSTRAP_WORKER = """
import sys, time
from app.runtime_locks import bootstrap_lock
tag, logpath = sys.argv[1], sys.argv[2]
with bootstrap_lock():
    with open(logpath, "a") as f:
        f.write(tag + " ENTER\\n"); f.flush()
    time.sleep(0.6)
    with open(logpath, "a") as f:
        f.write(tag + " EXIT\\n"); f.flush()
"""


def test_leader_lock_is_exclusive_across_processes(tmp_path):
    """一個行程持有 leader 鎖時，另一個行程 try_acquire 應失敗。"""
    env = {**os.environ, "TCRT_RUNTIME_LOCK_DIR": str(tmp_path)}
    holder = subprocess.Popen(
        [sys.executable, "-c", _LEADER_HOLDER],
        cwd=str(REPO),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        first = holder.stdout.readline().strip()
        assert first == "LEADER", f"holder 未取得 leadership: {first!r}"

        result = subprocess.run(
            [sys.executable, "-c", _LEADER_TRY],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        assert "NOT_LEADER" in result.stdout, f"第二行程不應取得 leadership: {result.stdout!r} / {result.stderr[-500:]!r}"
    finally:
        try:
            holder.stdin.write("\n")
            holder.stdin.flush()
            holder.wait(timeout=15)
        except Exception:
            holder.kill()

    # holder 釋放後，新行程應能取得 leadership（驗證鎖確實隨行程結束釋放）
    after = subprocess.run(
        [sys.executable, "-c", _LEADER_TRY],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert "LEADER" in after.stdout and "NOT_LEADER" not in after.stdout, after.stdout


def test_bootstrap_lock_serializes_across_processes(tmp_path):
    """兩個行程同時進入 bootstrap_lock，critical section 不得交錯。"""
    logpath = tmp_path / "order.log"
    workers = [
        subprocess.Popen([sys.executable, "-c", _BOOTSTRAP_WORKER, tag, str(logpath)], cwd=str(REPO))
        for tag in ("P1", "P2")
    ]
    for w in workers:
        assert w.wait(timeout=90) == 0

    events = [line.split() for line in logpath.read_text().splitlines() if line.strip()]
    assert len(events) == 4, f"預期 4 筆事件，得到 {events}"
    # 序列化 → 必為 [X ENTER, X EXIT, Y ENTER, Y EXIT]，不得交錯
    assert events[0][1] == "ENTER" and events[1][1] == "EXIT" and events[0][0] == events[1][0], events
    assert events[2][1] == "ENTER" and events[3][1] == "EXIT" and events[2][0] == events[3][0], events
    assert events[0][0] != events[2][0], f"兩行程 tag 應不同: {events}"


def _require_postgres_admin_url() -> str:
    url = os.getenv(POSTGRES_URL_ENV)
    if not url:
        pytest.skip(f"{POSTGRES_URL_ENV} 未設定，略過需要真實 PostgreSQL server 的整合測試")
    return url


@contextmanager
def _restricted_postgres_role(admin_url: str):
    """建立一個 CONNECT 權限只到自己 target DB、連不上 maintenance DB(`postgres`)的
    PostgreSQL role，用來驗證 bootstrap_lock() 的 fallback
    （見 app/runtime_locks.py::_connect_for_bootstrap_lock）。"""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.pool import NullPool

    def _cleanup() -> None:
        engine = create_engine(admin_url, poolclass=NullPool, future=True)
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :db AND pid <> pg_backend_pid()"
                    ),
                    {"db": _RESTRICTED_DB},
                )
                conn.execute(text(f"DROP DATABASE IF EXISTS {_RESTRICTED_DB}"))
                conn.execute(text(f"DROP ROLE IF EXISTS {_RESTRICTED_ROLE}"))
        finally:
            engine.dispose()

    _cleanup()  # 清掉前次跑到一半留下的殘留
    engine = create_engine(admin_url, poolclass=NullPool, future=True)
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f"CREATE ROLE {_RESTRICTED_ROLE} LOGIN PASSWORD 'tcrt_test_pw'"))
            conn.execute(text(f"CREATE DATABASE {_RESTRICTED_DB} OWNER {_RESTRICTED_ROLE}"))
            conn.execute(text(f"REVOKE CONNECT ON DATABASE postgres FROM {_RESTRICTED_ROLE}"))
    finally:
        engine.dispose()

    base = make_url(admin_url)
    restricted_url = base.set(
        username=_RESTRICTED_ROLE, password="tcrt_test_pw", database=_RESTRICTED_DB
    ).render_as_string(hide_password=False)

    try:
        yield restricted_url
    finally:
        _cleanup()


def test_bootstrap_lock_falls_back_and_still_serializes_with_restricted_postgres_account(tmp_path):
    """service account 連不上 maintenance DB(`postgres`)、只能連自己 target DB 時，
    bootstrap_lock() 應退回直接連 target DB 取得同一把 server 全域鎖——且這把鎖仍要是
    「真的互斥」，不是退化成每次都放行。

    若 fallback 沒接上，worker 會在連 maintenance DB 時就丟 OperationalError 而
    returncode != 0；若鎖退化成每次放行，兩個 worker 的 ENTER/EXIT 會交錯而非
    序列化——這兩種壞情況這個測試都會抓到。
    """
    admin_url = _require_postgres_admin_url()
    with _restricted_postgres_role(admin_url) as restricted_url:
        logpath = tmp_path / "order.log"
        env = {**os.environ, "DATABASE_URL": restricted_url}
        workers = [
            subprocess.Popen(
                [sys.executable, "-c", _BOOTSTRAP_WORKER, tag, str(logpath)],
                cwd=str(REPO),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for tag in ("R1", "R2")
        ]
        for w in workers:
            out, err = w.communicate(timeout=90)
            assert w.returncode == 0, f"worker 失敗 (returncode={w.returncode}): stdout={out!r} stderr={err!r}"

        events = [line.split() for line in logpath.read_text().splitlines() if line.strip()]
        assert len(events) == 4, f"預期 4 筆事件，得到 {events}"
        assert events[0][1] == "ENTER" and events[1][1] == "EXIT" and events[0][0] == events[1][0], events
        assert events[2][1] == "ENTER" and events[3][1] == "EXIT" and events[2][0] == events[3][0], events
        assert events[0][0] != events[2][0], f"兩行程 tag 應不同: {events}"


def test_provider_encryption_key_required_when_providers_exist(tmp_path, monkeypatch):
    """有 provider 資料但缺 encryption key 時，bootstrap 檢查回 False（快速失敗依據）。"""
    from sqlalchemy import create_engine, text

    import database_init
    from app.config import settings

    dbfile = tmp_path / "main.db"
    engine = create_engine(f"sqlite:///{dbfile}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE team_automation_providers (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO team_automation_providers (id) VALUES (1)"))

    logger = database_init.Logger(quiet=True)

    monkeypatch.setattr(settings.automation_provider, "encryption_key", "")
    ok, message = database_init.verify_automation_provider_encryption_key(engine, logger)
    assert ok is False and message

    valid_key = base64.b64encode(b"0" * 32).decode()
    monkeypatch.setattr(settings.automation_provider, "encryption_key", valid_key)
    ok2, _ = database_init.verify_automation_provider_encryption_key(engine, logger)
    assert ok2 is True

    engine.dispose()
