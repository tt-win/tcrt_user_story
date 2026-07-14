"""跨引擎執行期鎖。

提供兩種鎖：

- ``bootstrap_lock()``：短命、阻塞式 context manager，序列化平行啟動下的資料庫
  schema 變更（避免兩個行程同時跑 Alembic upgrade）。
- ``BackgroundLeaderLock``：長命、非阻塞 try-acquire，選出唯一執行背景服務
  （排程器 + automation ticker）的 leader 行程，使 web 層可多 worker / 多副本而
  不重複扇出。

跨引擎實作：

- PostgreSQL：session-level advisory lock（``pg_advisory_lock`` /
  ``pg_try_advisory_lock`` / ``pg_advisory_unlock``），lock 與連線（session）綁定。
- MySQL / MariaDB：``GET_LOCK`` / ``RELEASE_LOCK``（連線層級）。
- SQLite 及其他：``portalocker`` 檔案鎖。

PG/MySQL 的鎖與其專屬連線綁定、SQLite 的鎖與檔案 handle 綁定；行程結束時連線/檔案
關閉即自動釋放，避免 leader 當掉後鎖永久卡住。
"""
from __future__ import annotations

import logging
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# 固定 lock 識別碼（bootstrap 與 leader 使用不同 key，彼此互不阻擋）
_BOOTSTRAP_LOCK_KEY = 0x54435242  # 'TCRB' → postgres bigint advisory key
_LEADER_LOCK_KEY = 0x54435254     # 'TCRT'
_BOOTSTRAP_LOCK_NAME = "tcrt_bootstrap"          # mysql GET_LOCK 名稱 / sqlite 檔名
_LEADER_LOCK_NAME = "tcrt_background_leader"
_BOOTSTRAP_LOCK_TIMEOUT_SECONDS = 120


def _sync_main_url() -> str:
    """取得主資料庫的 sync 連線字串。"""
    from app.db_migrations import resolve_main_database_url
    from app.db_url import normalize_sync_database_url

    return normalize_sync_database_url(resolve_main_database_url())


def _backend_name(sync_url: str) -> str:
    try:
        return make_url(sync_url).get_backend_name().lower()
    except Exception:  # noqa: BLE001
        return ""


def _bootstrap_lock_url(sync_url: str, backend: str) -> str:
    """PG/MySQL 的 advisory lock 是 server 全域的，改連 maintenance DB（保留原帳密），
    使鎖在 target DB 尚未建立時也能運作（避免 bootstrap 雞生蛋問題）。"""
    try:
        url = make_url(sync_url)
        if backend == "postgresql":
            url = url.set(database="postgres")
        elif backend in ("mysql", "mariadb"):
            url = url.set(database=None)
        else:
            return sync_url
        # 注意：str(URL) 會遮蔽密碼成 ***，必須用 render_as_string(hide_password=False) 保留密碼
        return url.render_as_string(hide_password=False)
    except Exception:  # noqa: BLE001
        return sync_url


def _connect_for_bootstrap_lock(sync_url: str, backend: str):
    """建立 bootstrap 鎖要用的連線：優先連 maintenance DB（讓鎖在 target DB 尚未建立時
    也能運作），若帳號權限受限連不上 maintenance DB（例如企業常見的「service account
    只給 target DB 權限、不給碰 postgres 系統庫」），退回直接連 target DB。

    這個退回不會削弱鎖的語意：PostgreSQL 的 advisory lock 與 MySQL 的 GET_LOCK 都是
    server 全域的 key 命名空間，不是「連到哪個 database 鎖就只在那個 database 生效」，
    只差在「target DB 還不存在時能不能連得上」——連不上 maintenance DB 的帳號，本來也
    多半沒有「自己建立 target DB」的權限，代表 target DB 十之八九已由 DBA 事先建好，
    此時直接連 target DB 一樣能正確取得 server 全域的鎖。"""
    maintenance_url = _bootstrap_lock_url(sync_url, backend)
    if maintenance_url == sync_url:
        engine = create_engine(sync_url, poolclass=NullPool, future=True)
        return engine, engine.connect().execution_options(isolation_level="AUTOCOMMIT")

    try:
        engine = create_engine(maintenance_url, poolclass=NullPool, future=True)
        conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        return engine, conn
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "無法連線 maintenance DB 取得 bootstrap 鎖（可能是帳號權限受限，只能存取 "
            "target DB）：%s；改直接連 target DB 取得同一把 server 全域鎖。",
            exc,
        )
        engine = create_engine(sync_url, poolclass=NullPool, future=True)
        return engine, engine.connect().execution_options(isolation_level="AUTOCOMMIT")


def _lock_file_path(name: str) -> Path:
    return Path(tempfile.gettempdir()) / f"{name}.lock"


@contextmanager
def bootstrap_lock() -> Iterator[None]:
    """序列化平行 bootstrap 的 schema 變更；取得後 yield，離開時釋放。"""
    sync_url = _sync_main_url()
    backend = _backend_name(sync_url)

    if backend in ("postgresql", "mysql", "mariadb"):
        engine, conn = _connect_for_bootstrap_lock(sync_url, backend)
        try:
            if backend == "postgresql":
                conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _BOOTSTRAP_LOCK_KEY})
            else:
                got = conn.execute(
                    text("SELECT GET_LOCK(:n, :t)"),
                    {"n": _BOOTSTRAP_LOCK_NAME, "t": _BOOTSTRAP_LOCK_TIMEOUT_SECONDS},
                ).scalar()
                if got != 1:
                    raise TimeoutError(f"無法在 {_BOOTSTRAP_LOCK_TIMEOUT_SECONDS}s 內取得 bootstrap 鎖（GET_LOCK 回 {got!r}）")
            logger.info("已取得 bootstrap 鎖（%s）", backend)
            yield
        finally:
            try:
                if backend == "postgresql":
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _BOOTSTRAP_LOCK_KEY})
                else:
                    conn.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": _BOOTSTRAP_LOCK_NAME})
            except Exception as exc:  # noqa: BLE001
                logger.warning("釋放 bootstrap 鎖失敗（連線關閉時仍會自動釋放）：%s", exc)
            finally:
                conn.close()
                engine.dispose()
    else:
        # SQLite 及其他：阻塞式檔案鎖
        import portalocker

        path = _lock_file_path(_BOOTSTRAP_LOCK_NAME)
        handle = open(path, "a+")  # noqa: SIM115
        try:
            portalocker.lock(handle, portalocker.LOCK_EX)
            logger.info("已取得 bootstrap 檔案鎖：%s", path)
            yield
        finally:
            try:
                portalocker.unlock(handle)
            finally:
                handle.close()


class BackgroundLeaderLock:
    """背景服務 leader 鎖（非阻塞 try-acquire；唯有取得者才執行背景服務）。"""

    def __init__(self) -> None:
        self._engine = None
        self._conn = None
        self._file = None
        self._backend: Optional[str] = None
        self.is_leader = False

    def try_acquire(self) -> bool:
        """嘗試取得 leadership。已是 leader 則直接回 True；取不到回 False。"""
        if self.is_leader:
            return True
        sync_url = _sync_main_url()
        backend = _backend_name(sync_url)
        try:
            if backend in ("postgresql", "mysql", "mariadb"):
                engine = create_engine(sync_url, poolclass=NullPool, future=True)
                conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
                if backend == "postgresql":
                    got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LEADER_LOCK_KEY}).scalar())
                else:
                    got = conn.execute(text("SELECT GET_LOCK(:n, 0)"), {"n": _LEADER_LOCK_NAME}).scalar() == 1
                if got:
                    self._engine, self._conn, self._backend, self.is_leader = engine, conn, backend, True
                    return True
                conn.close()
                engine.dispose()
                return False

            # SQLite 及其他：非阻塞檔案鎖
            import portalocker

            handle = open(_lock_file_path(_LEADER_LOCK_NAME), "a+")  # noqa: SIM115
            try:
                portalocker.lock(handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
            except portalocker.exceptions.LockException:
                handle.close()
                return False
            self._file, self._backend, self.is_leader = handle, backend, True
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("嘗試取得背景 leader 鎖失敗：%s", exc)
            return False

    def release(self) -> None:
        """釋放 leadership（行程正常關閉時呼叫；異常結束時亦會因連線/檔案關閉而自動釋放）。"""
        if not self.is_leader:
            return
        self.is_leader = False
        if self._conn is not None:
            try:
                if self._backend == "postgresql":
                    self._conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LEADER_LOCK_KEY})
                elif self._backend in ("mysql", "mariadb"):
                    self._conn.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": _LEADER_LOCK_NAME})
            except Exception:  # noqa: BLE001
                pass
            finally:
                try:
                    self._conn.close()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    self._engine.dispose()
                except Exception:  # noqa: BLE001
                    pass
                self._conn = self._engine = None
        if self._file is not None:
            try:
                import portalocker

                portalocker.unlock(self._file)
            except Exception:  # noqa: BLE001
                pass
            finally:
                try:
                    self._file.close()
                except Exception:  # noqa: BLE001
                    pass
                self._file = None


# 模組層級 singleton，與 task_scheduler / automation_background_manager 的模式一致
background_leader_lock = BackgroundLeaderLock()
