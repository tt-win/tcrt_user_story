from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_story_map_db import USMAsyncSessionLocal

from .core import (
    BoundaryContract,
    DatabaseTarget,
    ManagedAccessBoundary,
    SessionProvider,
)


@asynccontextmanager
async def _usm_session_provider() -> AsyncIterator[AsyncSession]:
    async with USMAsyncSessionLocal() as session:
        yield session


class UsmAccessBoundary(ManagedAccessBoundary):
    def __init__(
        self,
        *,
        session_provider: SessionProvider | None = None,
        session_provider_name: str = "app.models.user_story_map_db.USMAsyncSessionLocal",
    ) -> None:
        super().__init__(
            contract=BoundaryContract(
                target=DatabaseTarget.USM,
                session_provider=session_provider_name,
            ),
            session_provider=session_provider or _usm_session_provider,
        )


def get_usm_access_boundary() -> UsmAccessBoundary:
    return UsmAccessBoundary()


def create_usm_access_boundary_for_session(session: AsyncSession) -> UsmAccessBoundary:
    @asynccontextmanager
    async def _provided_session_provider() -> AsyncIterator[AsyncSession]:
        yield session

    return UsmAccessBoundary(
        session_provider=_provided_session_provider,
        session_provider_name="provided_async_session",
    )
