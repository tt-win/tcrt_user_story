"""
會話管理服務

處理 JWT Token 的撤銷、黑名單管理、會話清理等功能。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Set

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.database_models import ActiveSession

logger = logging.getLogger(__name__)


class SessionService:
    """會話管理服務"""

    def __init__(self, main_boundary: MainAccessBoundary | None = None):
        self.settings = get_settings()
        self.main_boundary = main_boundary or get_main_access_boundary()
        self._revoked_jtis: Set[str] = set()
        self._challenges: dict = {}

    async def create_session(
        self,
        user_id: int,
        jti: str,
        expires_at: datetime,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> bool:
        """創建新的會話記錄"""
        try:
            async def _create(session: AsyncSession) -> bool:
                active_session = ActiveSession(
                    user_id=user_id,
                    jti=jti,
                    token_type="access",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    expires_at=expires_at,
                    created_at=datetime.utcnow(),
                )
                session.add(active_session)
                await session.flush()
                return True

            created = await self.main_boundary.run_write(_create)
            logger.debug("創建會話記錄: user_id=%s, jti=%s", user_id, jti)
            return created
        except Exception as exc:  # noqa: BLE001
            logger.error("創建會話記錄失敗: %s", exc)
            return False

    async def is_jti_revoked(self, jti: str) -> bool:
        """檢查 JTI 是否已被撤銷"""
        if jti in self._revoked_jtis:
            return True

        try:
            async def _load(session: AsyncSession) -> bool:
                result = await session.execute(
                    select(ActiveSession).where(
                        and_(
                            ActiveSession.jti == jti,
                            ActiveSession.is_revoked == True,
                        )
                    )
                )
                return result.scalar_one_or_none() is not None

            revoked = await self.main_boundary.run_read(_load)
            if revoked:
                self._revoked_jtis.add(jti)
            return revoked
        except Exception as exc:  # noqa: BLE001
            logger.error("檢查 JTI 撤銷狀態失敗: %s", exc)
            return False

    async def revoke_jti(self, jti: str, reason: str = "logout") -> bool:
        """撤銷指定的 JTI"""
        try:
            async def _revoke(session: AsyncSession) -> bool:
                result = await session.execute(
                    select(ActiveSession).where(ActiveSession.jti == jti)
                )
                active_session = result.scalar_one_or_none()
                if not active_session:
                    return False

                active_session.is_revoked = True
                active_session.revoked_at = datetime.utcnow()
                active_session.revoked_reason = reason
                await session.flush()
                return True

            revoked = await self.main_boundary.run_write(_revoke)
            if revoked:
                self._revoked_jtis.add(jti)
                logger.debug("撤銷 JTI: %s, 原因: %s", jti, reason)
            else:
                logger.warning("找不到要撤銷的會話: %s", jti)
            return revoked
        except Exception as exc:  # noqa: BLE001
            logger.error("撤銷 JTI 失敗: %s", exc)
            return False

    async def revoke_user_sessions(self, user_id: int, reason: str = "admin_revoke") -> int:
        """撤銷指定使用者的所有會話"""
        try:
            async def _revoke(session: AsyncSession) -> int:
                result = await session.execute(
                    select(ActiveSession).where(
                        and_(
                            ActiveSession.user_id == user_id,
                            ActiveSession.is_revoked == False,
                        )
                    )
                )
                active_sessions = result.scalars().all()
                revoked_count = 0
                revoked_time = datetime.utcnow()

                for active_session in active_sessions:
                    active_session.is_revoked = True
                    active_session.revoked_at = revoked_time
                    active_session.revoked_reason = reason
                    self._revoked_jtis.add(active_session.jti)
                    revoked_count += 1

                await session.flush()
                return revoked_count

            revoked_count = await self.main_boundary.run_write(_revoke)
            logger.info("撤銷使用者 %s 的 %s 個會話", user_id, revoked_count)
            return revoked_count
        except Exception as exc:  # noqa: BLE001
            logger.error("撤銷使用者會話失敗: %s", exc)
            return 0

    async def get_active_sessions(self, user_id: Optional[int] = None) -> List[ActiveSession]:
        """取得活躍會話列表"""
        try:
            async def _load(session: AsyncSession) -> List[ActiveSession]:
                query = select(ActiveSession).where(
                    and_(
                        ActiveSession.is_revoked == False,
                        ActiveSession.expires_at > datetime.utcnow(),
                    )
                )
                if user_id:
                    query = query.where(ActiveSession.user_id == user_id)
                result = await session.execute(query)
                return list(result.scalars().all())

            return await self.main_boundary.run_read(_load)
        except Exception as exc:  # noqa: BLE001
            logger.error("取得活躍會話失敗: %s", exc)
            return []

    async def cleanup_expired_sessions(self) -> int:
        """清理過期的會話記錄"""
        try:
            current_time = datetime.utcnow()
            cleanup_time = current_time - timedelta(days=self.settings.auth.session_cleanup_days)

            async def _cleanup(session: AsyncSession) -> int:
                result = await session.execute(
                    delete(ActiveSession).where(
                        or_(
                            ActiveSession.expires_at < current_time,
                            and_(
                                ActiveSession.is_revoked == True,
                                ActiveSession.revoked_at < cleanup_time,
                            ),
                        )
                    )
                )
                return result.rowcount or 0

            deleted_count = await self.main_boundary.run_write(_cleanup)
            if deleted_count > 0:
                logger.info("清理了 %s 個過期會話", deleted_count)

            self._cleanup_memory_cache()
            return deleted_count
        except Exception as exc:  # noqa: BLE001
            logger.error("清理過期會話失敗: %s", exc)
            return 0

    async def store_challenge(self, identifier: str, challenge: str, expires_at: datetime) -> bool:
        """暫存 challenge"""
        try:
            self._challenges[identifier] = (challenge, expires_at)
            logger.debug("暫存 challenge for %s", identifier)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("暫存 challenge 失敗: %s", exc)
            return False

    async def verify_challenge(self, identifier: str, challenge: str) -> bool:
        """驗證 challenge"""
        try:
            if identifier not in self._challenges:
                logger.warning("找不到 challenge for %s", identifier)
                return False

            stored_challenge, expires_at = self._challenges[identifier]
            if datetime.utcnow() > expires_at:
                logger.warning("Challenge 已過期 for %s", identifier)
                del self._challenges[identifier]
                return False

            if stored_challenge != challenge:
                logger.warning("Challenge 不匹配 for %s", identifier)
                return False

            del self._challenges[identifier]
            logger.debug("Challenge 驗證成功 for %s", identifier)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("驗證 challenge 失敗: %s", exc)
            return False

    def _cleanup_memory_cache(self):
        """清理記憶體中的 JTI 快取"""
        if len(self._revoked_jtis) > 10000:
            jti_list = list(self._revoked_jtis)
            self._revoked_jtis = set(jti_list[len(jti_list) // 2 :])
            logger.debug("清理了一半的 JTI 記憶體快取")

        current_time = datetime.utcnow()
        expired_identifiers = [
            identifier
            for identifier, (_, expires_at) in self._challenges.items()
            if expires_at < current_time
        ]
        for identifier in expired_identifiers:
            del self._challenges[identifier]
        if expired_identifiers:
            logger.debug("清理了 %s 個過期 challenge", len(expired_identifiers))

    async def get_session_statistics(self) -> dict:
        """取得會話統計資訊"""
        try:
            current_time = datetime.utcnow()

            async def _stats(session: AsyncSession) -> dict:
                total_result = await session.execute(
                    select(func.count()).select_from(ActiveSession)
                )
                active_result = await session.execute(
                    select(func.count()).select_from(ActiveSession).where(
                        and_(
                            ActiveSession.is_revoked == False,
                            ActiveSession.expires_at > current_time,
                        )
                    )
                )
                revoked_result = await session.execute(
                    select(func.count()).select_from(ActiveSession).where(
                        ActiveSession.is_revoked == True
                    )
                )
                return {
                    "total_sessions": total_result.scalar(),
                    "active_sessions": active_result.scalar(),
                    "revoked_sessions": revoked_result.scalar(),
                    "memory_cached_jtis": len(self._revoked_jtis),
                }

            return await self.main_boundary.run_read(_stats)
        except Exception as exc:  # noqa: BLE001
            logger.error("取得會話統計失敗: %s", exc)
            return {}


session_service = SessionService()


async def is_token_revoked(jti: str) -> bool:
    """檢查 Token 是否已被撤銷"""
    return await session_service.is_jti_revoked(jti)


async def revoke_token(jti: str, reason: str = "logout") -> bool:
    """撤銷 Token"""
    return await session_service.revoke_jti(jti, reason)


async def create_session_record(
    user_id: int,
    jti: str,
    expires_at: datetime,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> bool:
    """創建會話記錄"""
    return await session_service.create_session(
        user_id,
        jti,
        expires_at,
        ip_address,
        user_agent,
    )
