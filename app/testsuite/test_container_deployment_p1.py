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
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

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


def test_leader_lock_is_exclusive_across_processes():
    """一個行程持有 leader 鎖時，另一個行程 try_acquire 應失敗。"""
    holder = subprocess.Popen(
        [sys.executable, "-c", _LEADER_HOLDER],
        cwd=str(REPO),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
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
        [sys.executable, "-c", _LEADER_TRY], cwd=str(REPO), capture_output=True, text=True, timeout=60
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
