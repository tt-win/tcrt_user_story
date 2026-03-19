"""使用者服務

統一處理使用者的建立、更新、查詢等操作。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.auth.models import UserCreate, UserRole, UserUpdate
from app.auth.password_service import PasswordService
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.database_models import LarkUser, User

logger = logging.getLogger(__name__)


class UserService:
    """統一的使用者服務"""

    @staticmethod
    def _resolve_main_boundary(
        main_boundary: MainAccessBoundary | None = None,
    ) -> MainAccessBoundary:
        return main_boundary or get_main_access_boundary()

    @staticmethod
    def create_user(user_create: UserCreate, db: Session) -> User:
        """建立新使用者（同步版本，用於系統初始化）"""
        existing_user = db.query(User).filter(User.username == user_create.username).first()
        if existing_user:
            raise ValueError(f"使用者名稱 '{user_create.username}' 已存在")

        if user_create.email and user_create.email.strip():
            existing_email = db.query(User).filter(User.email == user_create.email.strip()).first()
            if existing_email:
                raise ValueError(f"電子信箱 '{user_create.email}' 已存在")

        hashed_password = PasswordService.hash_password(user_create.password)
        email_value = user_create.email.strip() if user_create.email and user_create.email.strip() else None

        new_user = User(
            username=user_create.username,
            email=email_value,
            full_name=user_create.full_name,
            role=user_create.role,
            hashed_password=hashed_password,
            is_active=user_create.is_active,
            lark_user_id=user_create.lark_user_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        db.add(new_user)
        db.flush()
        db.refresh(new_user)
        return new_user

    @staticmethod
    async def create_user_async(
        user_create: UserCreate,
        *,
        main_boundary: MainAccessBoundary | None = None,
    ) -> User:
        """建立新使用者（異步版本，用於 API）"""

        async def _create(session: AsyncSession) -> User:
            username_result = await session.execute(
                select(User).where(User.username == user_create.username)
            )
            if username_result.scalar():
                raise ValueError(f"使用者名稱 '{user_create.username}' 已存在")

            if user_create.email and user_create.email.strip():
                email_result = await session.execute(
                    select(User).where(User.email == user_create.email.strip())
                )
                if email_result.scalar():
                    raise ValueError(f"電子信箱 '{user_create.email}' 已存在")

            password = user_create.password or PasswordService.generate_temp_password()
            hashed_password = PasswordService.hash_password(password)
            email_value = user_create.email.strip() if user_create.email and user_create.email.strip() else None

            new_user = User(
                username=user_create.username,
                email=email_value,
                full_name=user_create.full_name,
                role=user_create.role,
                hashed_password=hashed_password,
                is_active=user_create.is_active,
                lark_user_id=user_create.lark_user_id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )

            session.add(new_user)
            await session.flush()
            await session.refresh(new_user)
            return new_user

        return await UserService._resolve_main_boundary(main_boundary).run_write(_create)

    @staticmethod
    async def get_user_by_id(
        user_id: int,
        *,
        main_boundary: MainAccessBoundary | None = None,
    ) -> Optional[User]:
        """根據 ID 取得使用者"""

        async def _get(session: AsyncSession) -> Optional[User]:
            result = await session.execute(select(User).where(User.id == user_id))
            return result.scalar_one_or_none()

        return await UserService._resolve_main_boundary(main_boundary).run_read(_get)

    @staticmethod
    async def get_user_by_username(
        username: str,
        *,
        main_boundary: MainAccessBoundary | None = None,
    ) -> Optional[User]:
        """根據使用者名稱取得使用者"""

        async def _get(session: AsyncSession) -> Optional[User]:
            result = await session.execute(select(User).where(User.username == username))
            return result.scalar_one_or_none()

        return await UserService._resolve_main_boundary(main_boundary).run_read(_get)

    @staticmethod
    async def get_user_by_email(
        email: str,
        *,
        main_boundary: MainAccessBoundary | None = None,
    ) -> Optional[User]:
        """根據電子信箱取得使用者"""

        async def _get(session: AsyncSession) -> Optional[User]:
            result = await session.execute(select(User).where(User.email == email))
            return result.scalar_one_or_none()

        return await UserService._resolve_main_boundary(main_boundary).run_read(_get)

    @staticmethod
    async def update_user(
        user_id: int,
        user_update: UserUpdate,
        *,
        main_boundary: MainAccessBoundary | None = None,
    ) -> Optional[User]:
        """更新使用者資訊"""

        async def _update(session: AsyncSession) -> Optional[User]:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return None

            update_data = user_update.dict(exclude_unset=True)
            if "password" in update_data:
                update_data["hashed_password"] = PasswordService.hash_password(update_data.pop("password"))

            update_data["updated_at"] = datetime.utcnow()
            for field, value in update_data.items():
                setattr(user, field, value)

            await session.flush()
            await session.refresh(user)
            return user

        return await UserService._resolve_main_boundary(main_boundary).run_write(_update)

    @staticmethod
    async def list_users(
        page: int = 1,
        per_page: int = 20,
        search: Optional[str] = None,
        role: Optional[UserRole] = None,
        is_active: Optional[bool] = None,
        *,
        main_boundary: MainAccessBoundary | None = None,
    ) -> tuple[List[User], int]:
        """列出使用者清單"""

        async def _list(session: AsyncSession) -> tuple[List[User], int]:
            query = select(User)

            if search:
                query = query.where(
                    or_(
                        User.username.ilike(f"%{search}%"),
                        User.email.ilike(f"%{search}%"),
                        User.full_name.ilike(f"%{search}%"),
                    )
                )

            if role:
                query = query.where(User.role == role)

            if is_active is not None:
                query = query.where(User.is_active == is_active)

            total_query = select(func.count()).select_from(query.subquery())
            total_result = await session.execute(total_query)
            total = total_result.scalar() or 0

            offset = (page - 1) * per_page
            paged_query = query.offset(offset).limit(per_page).order_by(User.created_at.desc())
            result = await session.execute(paged_query)
            return list(result.scalars().all()), total

        return await UserService._resolve_main_boundary(main_boundary).run_read(_list)

    @staticmethod
    async def delete_user(
        user_id: int,
        *,
        main_boundary: MainAccessBoundary | None = None,
    ) -> bool:
        """刪除使用者"""

        async def _delete(session: AsyncSession) -> bool:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return False

            await session.delete(user)
            await session.flush()
            return True

        return await UserService._resolve_main_boundary(main_boundary).run_write(_delete)

    @staticmethod
    async def check_lark_integration_status(
        user_id: int,
        *,
        main_boundary: MainAccessBoundary | None = None,
    ) -> Dict[str, Any]:
        """檢查用戶的 Lark 整合狀態"""

        async def _check(session: AsyncSession) -> Dict[str, Any]:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return {
                    "lark_linked": False,
                    "has_lark_data": False,
                    "lark_user_id": None,
                    "message": "使用者不存在",
                }

            lark_user_id = getattr(user, "lark_user_id", None)
            if not lark_user_id:
                return {
                    "lark_linked": False,
                    "has_lark_data": False,
                    "lark_user_id": None,
                    "message": "使用者未連結 Lark 帳號",
                }

            lark_result = await session.execute(
                select(LarkUser).where(LarkUser.user_id == lark_user_id)
            )
            lark_user = lark_result.scalar_one_or_none()
            if lark_user:
                has_display_data = bool(lark_user.name or lark_user.avatar_240)
                status_message = (
                    "Lark 帳號已連結並有顯示資料"
                    if has_display_data
                    else "Lark 帳號已連結但缺少顯示資料"
                )
                return {
                    "lark_linked": True,
                    "has_lark_data": has_display_data,
                    "lark_user_id": lark_user_id,
                    "name": lark_user.name,
                    "avatar": lark_user.avatar_240,
                    "message": status_message,
                }

            return {
                "lark_linked": True,
                "has_lark_data": False,
                "lark_user_id": lark_user_id,
                "name": None,
                "avatar": None,
                "message": "Lark 帳號已連結但本地沒有快取資料，可能需要重新同步",
            }

        return await UserService._resolve_main_boundary(main_boundary).run_read(_check)

    @staticmethod
    async def deactivate_user(
        user_id: int,
        *,
        main_boundary: MainAccessBoundary | None = None,
    ) -> Optional[User]:
        """停用使用者"""

        async def _deactivate(session: AsyncSession) -> Optional[User]:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return None

            user.is_active = False
            user.updated_at = datetime.utcnow()
            await session.flush()
            await session.refresh(user)
            return user

        return await UserService._resolve_main_boundary(main_boundary).run_write(_deactivate)


user_service = UserService()
