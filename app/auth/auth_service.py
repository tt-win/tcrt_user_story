"""
JWT Token 認證服務

提供 JWT Token 的生成、驗證、刷新、撤銷等功能。
"""

import jwt
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from app.config import get_settings
from app.auth.models import TokenData, UserRole
from app.auth.session_service import session_service, is_token_revoked, create_session_record


class AuthService:
    """JWT 認證服務"""
    
    def __init__(self):
        self.settings = get_settings()
        self.secret_key = self.settings.auth.jwt_secret_key
        self.algorithm = "HS256"
        self.expire_days = self.settings.auth.jwt_expire_days
    
    async def create_access_token(
        self, 
        user_id: int, 
        username: str, 
        role: UserRole,
        expires_delta: Optional[timedelta] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> tuple[str, str, datetime]:
        """
        建立 JWT 存取 Token
        
        Args:
            user_id: 使用者 ID
            username: 使用者名稱  
            role: 使用者角色
            expires_delta: 自訂過期時間（可選）
            
        Returns:
            tuple: (token, jti, expires_at)
        """
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(days=self.expire_days)
        
        # 生成唯一的 JWT ID
        jti = str(uuid.uuid4())
        
        payload = {
            "user_id": user_id,
            "username": username, 
            "role": role.value,
            "jti": jti,
            "exp": expire,
            "iat": datetime.utcnow(),
            "iss": "test-case-repo-auth"  # 發行者
        }
        
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        
        # 創建會話記錄
        await create_session_record(
            user_id=user_id,
            jti=jti,
            expires_at=expire,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        return token, jti, expire
    
    async def verify_token(self, token: str, check_revocation: bool = True) -> Optional[TokenData]:
        """
        驗證 JWT Token
        
        Args:
            token: JWT Token 字串
            
        Returns:
            TokenData 或 None（如果無效）
        """
        try:
            payload = jwt.decode(
                token, 
                self.secret_key, 
                algorithms=[self.algorithm],
                options={"verify_exp": True}
            )
            
            # 檢查必要欄位
            user_id = payload.get("user_id")
            username = payload.get("username")
            role = payload.get("role")
            jti = payload.get("jti")
            
            if not all([user_id, username, role, jti]):
                return None
                
            # 檢查 JTI 是否已被撤銷
            if check_revocation and await is_token_revoked(jti):
                return None
            
            return TokenData(
                user_id=user_id,
                username=username,
                role=UserRole(role),
                jti=jti
            )
            
        except jwt.ExpiredSignatureError:
            # Token 已過期
            return None
        except jwt.InvalidTokenError:
            # Token 無效
            return None
        except Exception:
            # 其他錯誤
            return None
    
    async def refresh_token(
        self, 
        old_token: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Optional[tuple[str, str, datetime]]:
        """
        刷新 Token（重新生成）
        
        Args:
            old_token: 舊的 JWT Token
            
        Returns:
            tuple: (new_token, new_jti, expires_at) 或 None
        """
        token_data = await self.verify_token(old_token)
        if not token_data:
            return None
            
        # 撤銷舊 Token
        await session_service.revoke_jti(token_data.jti, "refresh")
        
        return await self.create_access_token(
            token_data.user_id,
            token_data.username, 
            token_data.role,
            ip_address=ip_address,
            user_agent=user_agent
        )
    
    async def revoke_token(self, jti: str, reason: str = "logout") -> bool:
        """
        撤銷 Token（將 JTI 加入黑名單）
        
        Args:
            jti: JWT ID
            reason: 撤銷原因
            
        Returns:
            是否成功撤銷
        """
        return await session_service.revoke_jti(jti, reason)
    
    async def revoke_user_tokens(self, user_id: int, reason: str = "admin_revoke") -> int:
        """
        撤銷使用者的所有 Token
        
        Args:
            user_id: 使用者 ID
            reason: 撤銷原因
            
        Returns:
            撤銷的 Token 數量
        """
        return await session_service.revoke_user_sessions(user_id, reason)
    
    def decode_token_without_verification(self, token: str) -> Optional[Dict[str, Any]]:
        """
        不驗證簽名解碼 Token（僅用於調試）
        
        Args:
            token: JWT Token 字串
            
        Returns:
            Token payload 或 None
        """
        try:
            return jwt.decode(
                token, 
                options={"verify_signature": False, "verify_exp": False}
            )
        except Exception:
            return None