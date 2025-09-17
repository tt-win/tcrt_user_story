#!/usr/bin/env python3
"""
版本服務：管理伺服器版本 timestamp
"""
from datetime import datetime
from typing import Optional
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class VersionService:
    _instance: Optional['VersionService'] = None
    _server_timestamp: Optional[int] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self._update_timestamp()
            logger.info(f"版本服務初始化，伺服器時間戳: {self._server_timestamp}")

    def _update_timestamp(self) -> None:
        """更新伺服器時間戳"""
        self._server_timestamp = int(datetime.now().timestamp() * 1000)  # 毫秒級時間戳
        logger.info(f"伺服器時間戳已更新: {self._server_timestamp}")

    def get_server_timestamp(self) -> int:
        """取得伺服器時間戳"""
        if self._server_timestamp is None:
            self._update_timestamp()
        return self._server_timestamp

    def refresh_timestamp(self) -> int:
        """手動刷新時間戳（用於檔案變化或重啟）"""
        self._update_timestamp()
        return self._server_timestamp

# 全域實例
version_service = VersionService()

def get_version_service() -> VersionService:
    """取得版本服務實例"""
    return version_service