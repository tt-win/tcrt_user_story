"""Authenticated avatar proxy endpoints.

Serves user / Lark avatars from the application origin. Upstream failures
degrade to a locally generated initials SVG — never to an external redirect.

``<img src>`` cannot send an Authorization header, so these endpoints also
accept ``?access_token=`` (same JWT as Bearer) for browser image loads.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.auth_service import auth_service
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.database_models import LarkUser, User
from app.services.avatar_proxy_service import get_avatar_proxy_service
from app.services.user_service import UserService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/avatars", tags=["avatars"])

_CACHE_CONTROL = "private, max-age=3600"
_optional_bearer = HTTPBearer(auto_error=False)


async def get_avatar_viewer(
    request: Request,
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_optional_bearer),
    access_token: Optional[str] = Query(
        None,
        description="JWT for <img src> loads that cannot send Authorization",
    ),
) -> User:
    """Authenticate via Bearer header or access_token query (img-tag compatible)."""
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    elif access_token and access_token.strip():
        token = access_token.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    token_data = await auth_service.verify_token(token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "無效或過期的存取 Token"},
        )

    user = await UserService.get_user_by_id(token_data.user_id, main_boundary=main_boundary)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "USER_NOT_FOUND_OR_INACTIVE",
                "message": "使用者不存在或已停用",
            },
        )

    request.state.current_user = user
    return user


def _avatar_response(payload) -> Response:
    return Response(
        content=payload.body,
        media_type=payload.content_type,
        headers={
            "Cache-Control": _CACHE_CONTROL,
            "X-Avatar-Cache": "HIT" if payload.cache_hit else "MISS",
            # Reduce chance of access_token query leaking via Referer on navigations.
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/users/{user_id}")
async def get_user_avatar(
    user_id: int,
    current_user: User = Depends(get_avatar_viewer),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    """Proxy avatar for a TCRT user (Lark upstream when linked)."""
    del current_user  # auth gate only
    service = get_avatar_proxy_service()

    async def _load(session: AsyncSession) -> tuple[Optional[str], Optional[str], str]:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        display_name = user.full_name or user.username or str(user_id)
        upstream: Optional[str] = None
        if user.lark_user_id:
            lark_user = await session.get(LarkUser, user.lark_user_id)
            if lark_user:
                upstream = lark_user.avatar_240 or lark_user.avatar_640 or lark_user.avatar_origin
                display_name = lark_user.name or display_name
        return upstream, display_name, str(user_id)

    try:
        upstream, display_name, seed = await main_boundary.run_read(_load)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed loading user avatar context for %s: %s", user_id, exc)
        payload = service.placeholder_svg(name=str(user_id), seed=str(user_id))
        return _avatar_response(payload)

    payload = await service.resolve(
        cache_key=f"user:{user_id}",
        upstream_url=upstream,
        display_name=display_name,
        seed=seed,
    )
    return _avatar_response(payload)


@router.get("/lark/{lark_user_id}")
async def get_lark_avatar(
    lark_user_id: str,
    current_user: User = Depends(get_avatar_viewer),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    """Proxy avatar for a Lark org user id."""
    del current_user
    service = get_avatar_proxy_service()
    normalized = (lark_user_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="lark_user_id required")

    async def _load(session: AsyncSession) -> tuple[Optional[str], Optional[str]]:
        lark_user = await session.get(LarkUser, normalized)
        if not lark_user:
            return None, normalized
        upstream = lark_user.avatar_240 or lark_user.avatar_640 or lark_user.avatar_origin
        return upstream, lark_user.name or normalized

    try:
        upstream, display_name = await main_boundary.run_read(_load)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed loading lark avatar context for %s: %s", normalized, exc)
        payload = service.placeholder_svg(name=normalized, seed=normalized)
        return _avatar_response(payload)

    payload = await service.resolve(
        cache_key=f"lark:{normalized}",
        upstream_url=upstream,
        display_name=display_name,
        seed=normalized,
    )
    return _avatar_response(payload)
