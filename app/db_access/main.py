from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session

from .core import BoundaryContract, DatabaseTarget, ManagedAccessBoundary, SessionProvider


@asynccontextmanager
async def _main_session_provider() -> AsyncIterator[AsyncSession]:
    async with get_async_session() as session:
        yield session


class MainAccessBoundary(ManagedAccessBoundary):
    def __init__(
        self,
        *,
        session_provider: SessionProvider | None = None,
        session_provider_name: str = "app.database.get_async_session",
    ) -> None:
        super().__init__(
            contract=BoundaryContract(
                target=DatabaseTarget.MAIN,
                session_provider=session_provider_name,
            ),
            session_provider=session_provider or _main_session_provider,
        )


def get_main_access_boundary() -> MainAccessBoundary:
    return MainAccessBoundary()


def create_main_access_boundary_for_session(session: AsyncSession) -> MainAccessBoundary:
    @asynccontextmanager
    async def _provided_session_provider() -> AsyncIterator[AsyncSession]:
        yield session

    return MainAccessBoundary(
        session_provider=_provided_session_provider,
        session_provider_name="provided_async_session",
    )
