"""Print the script-inferred default WEB_CONCURRENCY to stdout（單一真相來源）。

docker/app-entrypoint.sh 與 start.sh 在 `WEB_CONCURRENCY` 未設或空字串時呼叫本 helper，
使啟動腳本與 `GET /api/admin/system-runtime-settings` 都從 **resolved settings**
（env 與 config.yaml 合併後的 main DB engine）推導同一個預設值：
SQLite → 1、MySQL / PostgreSQL → 5、其他 → 1。

openspec: add-system-runtime-settings-viewer
"""

from __future__ import annotations


def main() -> None:
    from app.config import settings
    from app.services.system_runtime_settings import (
        INFERRED_WEB_CONCURRENCY_DEFAULTS,
        db_endpoint_from_url,
    )

    engine = db_endpoint_from_url(settings.app.database_url)["engine"]
    print(INFERRED_WEB_CONCURRENCY_DEFAULTS[engine])


if __name__ == "__main__":
    main()
