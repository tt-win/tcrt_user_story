"""
會話管理服務

處理 JWT Token 的撤銷、黑名單管理、會話清理等功能。
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Set
from sqlalchemy import select, delete, and_, func, or_

from app.database import get_async_session
from app.models.database_models import ActiveSession
from app.config import get_settings

logger = logging.getLogger(__name__)


class SessionService:
    """會話管理服務"""

    def __init__(self):
        self.settings = get_settings()
        self._revoked_jtis: Set[str] = set()  # 記憶體中的撤銷 JTI 集合
        self._challenges: dict = {}  # 暫存 challenges {identifier: (challenge, expires_at)}
        
    async def create_session(
        self, 
        user_id: int, 
        jti: str, 
        expires_at: datetime,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """
        創建新的會話記錄
        
        Args:
            user_id: 使用者 ID
            jti: JWT ID
            expires_at: 過期時間
            ip_address: 來源 IP
            user_agent: 使用者代理
            
        Returns:
            是否創建成功
        """
        try:
            async with get_async_session() as session:
                active_session = ActiveSession(
                    user_id=user_id,
                    jti=jti,
                    token_type="access",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    expires_at=expires_at,
                    created_at=datetime.utcnow()
                )
                
                session.add(active_session)
                await session.commit()
                
                logger.debug(f"創建會話記錄: user_id={user_id}, jti={jti}")
                return True
                
        except Exception as e:
            logger.error(f"創建會話記錄失敗: {e}")
            return False
    
    async def is_jti_revoked(self, jti: str) -> bool:
        """
        檢查 JTI 是否已被撤銷
        
        Args:
            jti: JWT ID
            
        Returns:
            是否已被撤銷
        """
        # 先檢查記憶體快取
        if jti in self._revoked_jtis:
            return True
            
        # 檢查資料庫
        try:
            async with get_async_session() as session:
                result = await session.execute(
                    select(ActiveSession).where(
                        and_(
                            ActiveSession.jti == jti,
                            ActiveSession.is_revoked == True
                        )
                    )
                )
                revoked_session = result.scalar_one_or_none()
                
                if revoked_session:
                    # 加入記憶體快取
                    self._revoked_jtis.add(jti)
                    return True
                    
                return False
                
        except Exception as e:
            logger.error(f"檢查 JTI 撤銷狀態失敗: {e}")
            return False
    
    async def revoke_jti(self, jti: str, reason: str = "logout") -> bool:
        """
        撤銷指定的 JTI
        
        Args:
            jti: JWT ID
            reason: 撤銷原因
            
        Returns:
            是否撤銷成功
        """
        try:
            async with get_async_session() as session:
                # 更新會話狀態
                result = await session.execute(
                    select(ActiveSession).where(ActiveSession.jti == jti)
                )
                active_session = result.scalar_one_or_none()
                
                if active_session:
                    active_session.is_revoked = True
                    active_session.revoked_at = datetime.utcnow()
                    active_session.revoked_reason = reason
                    
                    await session.commit()
                    
                    # 加入記憶體快取
                    self._revoked_jtis.add(jti)
                    
                    logger.debug(f"撤銷 JTI: {jti}, 原因: {reason}")
                    return True
                else:
                    logger.warning(f"找不到要撤銷的會話: {jti}")
                    return False
                    
        except Exception as e:
            logger.error(f"撤銷 JTI 失敗: {e}")
            return False
    
    async def revoke_user_sessions(self, user_id: int, reason: str = "admin_revoke") -> int:
        """
        撤銷指定使用者的所有會話
        
        Args:
            user_id: 使用者 ID
            reason: 撤銷原因
            
        Returns:
            撤銷的會話數量
        """
        try:
            async with get_async_session() as session:
                # 查詢使用者的活躍會話
                result = await session.execute(
                    select(ActiveSession).where(
                        and_(
                            ActiveSession.user_id == user_id,
                            ActiveSession.is_revoked == False
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
                    
                    # 加入記憶體快取
                    self._revoked_jtis.add(active_session.jti)
                    revoked_count += 1
                
                await session.commit()
                
                logger.info(f"撤銷使用者 {user_id} 的 {revoked_count} 個會話")
                return revoked_count
                
        except Exception as e:
            logger.error(f"撤銷使用者會話失敗: {e}")
            return 0
    
    async def get_active_sessions(self, user_id: Optional[int] = None) -> List[ActiveSession]:
        """
        取得活躍會話列表
        
        Args:
            user_id: 使用者 ID（可選，為 None 時返回所有會話）
            
        Returns:
            活躍會話列表
        """
        try:
            async with get_async_session() as session:
                query = select(ActiveSession).where(
                    and_(
                        ActiveSession.is_revoked == False,
                        ActiveSession.expires_at > datetime.utcnow()
                    )
                )
                
                if user_id:
                    query = query.where(ActiveSession.user_id == user_id)
                    
                result = await session.execute(query)
                return list(result.scalars().all())
                
        except Exception as e:
            logger.error(f"取得活躍會話失敗: {e}")
            return []
    
    async def cleanup_expired_sessions(self) -> int:
        """
        清理過期的會話記錄
        
        Returns:
            清理的記錄數量
        """
        try:
            async with get_async_session() as session:
                # 清理過期的會話
                current_time = datetime.utcnow()
                cleanup_time = current_time - timedelta(days=self.settings.auth.session_cleanup_days)
                
                result = await session.execute(
                    delete(ActiveSession).where(
                        or_(
                            ActiveSession.expires_at < current_time,
                            and_(
                                ActiveSession.is_revoked == True,
                                ActiveSession.revoked_at < cleanup_time
                            )
                        )
                    )
                )
                
                deleted_count = result.rowcount
                await session.commit()
                
                if deleted_count > 0:
                    logger.info(f"清理了 {deleted_count} 個過期會話")
                    
                # 清理記憶體快取中的過期 JTI
                self._cleanup_memory_cache()
                
                return deleted_count
                
        except Exception as e:
            logger.error(f"清理過期會話失敗: {e}")
            return 0
    
    async def store_challenge(self, identifier: str, challenge: str, expires_at: datetime) -> bool:
        """
        暫存 challenge

        Args:
            identifier: 使用者識別 (username 或 email)
            challenge: 隨機 challenge 字串
            expires_at: 過期時間

        Returns:
            是否暫存成功
        """
        try:
            self._challenges[identifier] = (challenge, expires_at)
            logger.debug(f"暫存 challenge for {identifier}")
            return True
        except Exception as e:
            logger.error(f"暫存 challenge 失敗: {e}")
            return False

    async def verify_challenge(self, identifier: str, challenge: str) -> bool:
        """
        驗證 challenge

        Args:
            identifier: 使用者識別
            challenge: 要驗證的 challenge

        Returns:
            是否驗證成功
        """
        try:
            if identifier not in self._challenges:
                logger.warning(f"找不到 challenge for {identifier}")
                return False

            stored_challenge, expires_at = self._challenges[identifier]

            # 檢查是否過期
            if datetime.utcnow() > expires_at:
                logger.warning(f"Challenge 已過期 for {identifier}")
                del self._challenges[identifier]
                return False

            # 驗證 challenge
            if stored_challenge != challenge:
                logger.warning(f"Challenge 不匹配 for {identifier}")
                return False

            # 驗證成功，刪除 challenge (一次性使用)
            del self._challenges[identifier]
            logger.debug(f"Challenge 驗證成功 for {identifier}")
            return True

        except Exception as e:
            logger.error(f"驗證 challenge 失敗: {e}")
            return False

    def _cleanup_memory_cache(self):
        """清理記憶體中的 JTI 快取"""
        # 這裡可以實作更精細的快取清理邏輯
        # 目前簡單地限制快取大小
        if len(self._revoked_jtis) > 10000:
            # 清理一半的快取
            jti_list = list(self._revoked_jtis)
            self._revoked_jtis = set(jti_list[len(jti_list)//2:])
            logger.debug("清理了一半的 JTI 記憶體快取")

        # 清理過期的 challenges
        current_time = datetime.utcnow()
        expired_identifiers = [
            identifier for identifier, (_, expires_at) in self._challenges.items()
            if expires_at < current_time
        ]
        for identifier in expired_identifiers:
            del self._challenges[identifier]
        if expired_identifiers:
            logger.debug(f"清理了 {len(expired_identifiers)} 個過期 challenge")
    
    async def get_session_statistics(self) -> dict:
        """
        取得會話統計資訊
        
        Returns:
            統計資訊字典
        """
        try:
            async with get_async_session() as session:
                current_time = datetime.utcnow()
                
                # 總會話數
                total_result = await session.execute(
                    select(func.count()).select_from(ActiveSession)
                )
                total_sessions = total_result.scalar()
                
                # 活躍會話數
                active_result = await session.execute(
                    select(func.count()).select_from(ActiveSession).where(
                        and_(
                            ActiveSession.is_revoked == False,
                            ActiveSession.expires_at > current_time
                        )
                    )
                )
                active_sessions = active_result.scalar()
                
                # 已撤銷會話數
                revoked_result = await session.execute(
                    select(func.count()).select_from(ActiveSession).where(
                        ActiveSession.is_revoked == True
                    )
                )
                revoked_sessions = revoked_result.scalar()
                
                return {
                    "total_sessions": total_sessions,
                    "active_sessions": active_sessions,
                    "revoked_sessions": revoked_sessions,
                    "memory_cached_jtis": len(self._revoked_jtis)
                }
                
        except Exception as e:
            logger.error(f"取得會話統計失敗: {e}")
            return {}


# 全域會話服務實例
session_service = SessionService()


# 便利函數
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
    user_agent: Optional[str] = None
) -> bool:
    """創建會話記錄"""
    return await session_service.create_session(
        user_id, jti, expires_at, ip_address, user_agent
    )
