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


class AuthService:
    """JWT 認證服務"""
    
    def __init__(self):
        self.settings = get_settings()
        self.secret_key = self.settings.auth.jwt_secret_key
        self.algorithm = "HS256"
        self.expire_days = self.settings.auth.jwt_expire_days
    
    def create_access_token(
        self, 
        user_id: int, 
        username: str, 
        role: UserRole,
        expires_delta: Optional[timedelta] = None
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
        return token, jti, expire
    
    def verify_token(self, token: str) -> Optional[TokenData]:
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
    
    def refresh_token(self, old_token: str) -> Optional[tuple[str, str, datetime]]:
        """
        刷新 Token（重新生成）
        
        Args:
            old_token: 舊的 JWT Token
            
        Returns:
            tuple: (new_token, new_jti, expires_at) 或 None
        """
        token_data = self.verify_token(old_token)
        if not token_data:
            return None
            
        # TODO: 檢查 JTI 是否已被撤銷
        # TODO: 撤銷舊 Token 的 JTI
        
        return self.create_access_token(
            token_data.user_id,
            token_data.username, 
            token_data.role
        )
    
    def revoke_token(self, jti: str) -> bool:
        """
        撤銷 Token（將 JTI 加入黑名單）
        
        Args:
            jti: JWT ID
            
        Returns:
            是否成功撤銷
        """
        # TODO: 實作 JTI 黑名單機制
        # 這將在會話管理服務中實作
        return True
    
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