"""使用者服務\n統一處理使用者的建立、更新、查詢等操作"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select, or_, func
import logging

from app.models.database_models import User
from app.auth.models import UserRole, UserCreate, UserUpdate
from app.auth.password_service import PasswordService
from app.database import get_async_session

# 添加日誌記錄器
logger = logging.getLogger(__name__)

from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select, or_, func

from app.models.database_models import User
from app.auth.models import UserRole, UserCreate, UserUpdate
from app.auth.password_service import PasswordService
from app.database import get_async_session


class UserService:
    """統一的使用者服務"""
    
    @staticmethod
    def create_user(user_create: UserCreate, db: Session) -> User:
        """
        建立新使用者（同步版本，用於系統初始化）
        
        Args:
            user_create: 使用者建立資料
            db: 資料庫會話
            
        Returns:
            建立的使用者物件
            
        Raises:
            ValueError: 當使用者名稱或 email 已存在時
        """
        # 檢查使用者名稱是否已存在
        existing_user = db.query(User).filter(User.username == user_create.username).first()
        if existing_user:
            raise ValueError(f"使用者名稱 '{user_create.username}' 已存在")
        
        # 檢查 email 是否已存在（如果提供且不為空字串）
        if user_create.email and user_create.email.strip():
            existing_email = db.query(User).filter(User.email == user_create.email.strip()).first()
            if existing_email:
                raise ValueError(f"電子信箱 '{user_create.email}' 已存在")
        
        # 雜湊密碼
        hashed_password = PasswordService.hash_password(user_create.password)
        
        # 處理 email 欄位（空字串轉為 None）
        email_value = user_create.email.strip() if user_create.email and user_create.email.strip() else None
        
        # 建立新使用者
        new_user = User(
            username=user_create.username,
            email=email_value,
            full_name=user_create.full_name,
            role=user_create.role,
            hashed_password=hashed_password,
            is_active=user_create.is_active,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        db.add(new_user)
        db.flush()  # 取得 ID 但不提交
        db.refresh(new_user)
        
        return new_user
    
    @staticmethod
    async def create_user_async(user_create: UserCreate) -> User:
        """
        建立新使用者（異步版本，用於 API）
        
        Args:
            user_create: 使用者建立資料
            
        Returns:
            建立的使用者物件
            
        Raises:
            ValueError: 當使用者名稱或 email 已存在時
        """
        async with get_async_session() as session:
            # 檢查使用者名稱是否已存在
            result = await session.execute(
                select(User).where(User.username == user_create.username)
            )
            if result.scalar():
                raise ValueError(f"使用者名稱 '{user_create.username}' 已存在")
            
            # 檢查 email 是否已存在（如果提供且不為空字串）
            if user_create.email and user_create.email.strip():
                result = await session.execute(
                    select(User).where(User.email == user_create.email.strip())
                )
                if result.scalar():
                    raise ValueError(f"電子信箱 '{user_create.email}' 已存在")
            
            # 生成密碼（如果未提供）
            password = user_create.password
            if not password:
                password = PasswordService.generate_temp_password()
            
            # 雜湊密碼
            hashed_password = PasswordService.hash_password(password)
            
            # 處理 email 欄位（空字串轉為 None）
            email_value = user_create.email.strip() if user_create.email and user_create.email.strip() else None
            
            # 建立新使用者
            new_user = User(
                username=user_create.username,
                email=email_value,
                full_name=user_create.full_name,
                role=user_create.role,
                hashed_password=hashed_password,
                is_active=user_create.is_active,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            session.add(new_user)
            await session.commit()
            await session.refresh(new_user)
            
            return new_user
    
    @staticmethod
    async def get_user_by_id(user_id: int) -> Optional[User]:
        """根據 ID 取得使用者"""
        async with get_async_session() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def get_user_by_username(username: str) -> Optional[User]:
        """根據使用者名稱取得使用者"""
        async with get_async_session() as session:
            result = await session.execute(
                select(User).where(User.username == username)
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def get_user_by_email(email: str) -> Optional[User]:
        """根據電子信箱取得使用者"""
        async with get_async_session() as session:
            result = await session.execute(
                select(User).where(User.email == email)
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def update_user(user_id: int, user_update: UserUpdate) -> Optional[User]:
        """更新使用者資訊"""
        async with get_async_session() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                return None
            
            # 更新欄位
            update_data = user_update.dict(exclude_unset=True)
            
            # 如果要更新密碼，先雜湊
            if 'password' in update_data:
                update_data['hashed_password'] = PasswordService.hash_password(update_data.pop('password'))
            
            # 更新時間
            update_data['updated_at'] = datetime.utcnow()
            
            for field, value in update_data.items():
                setattr(user, field, value)
            
            await session.commit()
            await session.refresh(user)
            
            return user
    
    @staticmethod
    async def list_users(
        page: int = 1,
        per_page: int = 20,
        search: Optional[str] = None,
        role: Optional[UserRole] = None,
        is_active: Optional[bool] = None
    ) -> tuple[List[User], int]:
        """
        列出使用者清單
        
        Returns:
            tuple: (users, total_count)
        """
        async with get_async_session() as session:
            # 建立基礎查詢
            query = select(User)
            
            # 搜尋條件
            if search:
                search_filter = or_(
                    User.username.ilike(f"%{search}%"),
                    User.email.ilike(f"%{search}%"),
                    User.full_name.ilike(f"%{search}%")
                )
                query = query.where(search_filter)
            
            # 角色篩選
            if role:
                query = query.where(User.role == role)
            
            # 狀態篩選
            if is_active is not None:
                query = query.where(User.is_active == is_active)
            
            # 總數查詢
            total_query = select(func.count()).select_from(query.subquery())
            total_result = await session.execute(total_query)
            total = total_result.scalar()
            
            # 分頁查詢
            offset = (page - 1) * per_page
            query = query.offset(offset).limit(per_page).order_by(User.created_at.desc())
            
            result = await session.execute(query)
            users = result.scalars().all()
            
            return list(users), total
    
    @staticmethod
    async def delete_user(user_id: int) -> bool:
        """刪除使用者"""
        async with get_async_session() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                return False
            
            await session.delete(user)
            await session.commit()
            
            return True

    @staticmethod
    async def check_lark_integration_status(user_id: int) -> Dict[str, Any]:
        """檢查用戶的 Lark 整合狀態"""
        async with get_async_session() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                return {
                    "lark_linked": False,
                    "has_lark_data": False,
                    "lark_user_id": None,
                    "message": "使用者不存在"
                }
            
            # 檢查是否有連結 Lark 用戶
            lark_user_id = getattr(user, 'lark_user_id', None)
            if not lark_user_id:
                return {
                    "lark_linked": False,
                    "has_lark_data": False,
                    "lark_user_id": None,
                    "message": "使用者未連結 Lark 帳號"
                }
            
            # 檢查本地快取的 Lark 數據
            from app.models.database_models import LarkUser
            lark_result = await session.execute(
                select(LarkUser).where(LarkUser.user_id == lark_user_id)
            )
            lark_user = lark_result.scalar_one_or_none()
            
            if lark_user:
                # 檢查是否有可用的顯示數據
                has_display_data = bool(lark_user.name or lark_user.avatar_240)
                status_message = "Lark 帳號已連結並有顯示資料" if has_display_data else "Lark 帳號已連結但缺少顯示資料"
                
                return {
                    "lark_linked": True,
                    "has_lark_data": has_display_data,
                    "lark_user_id": lark_user_id,
                    "name": lark_user.name,
                    "avatar": lark_user.avatar_240,
                    "message": status_message
                }
            else:
                # 本地沒有 Lark 數據，可能需要重新同步
                return {
                    "lark_linked": True,
                    "has_lark_data": False,
                    "lark_user_id": lark_user_id,
                    "name": None,
                    "avatar": None,
                    "message": "Lark 帳號已連結但本地沒有快取資料，可能需要重新同步"
                }
    
    @staticmethod
    async def deactivate_user(user_id: int) -> Optional[User]:
        """停用使用者"""
        async with get_async_session() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                return None
            
            user.is_active = False
            user.updated_at = datetime.utcnow()
            
            await session.commit()
            await session.refresh(user)
            
            return user


# 創建全域 UserService 實例
user_service = UserService()