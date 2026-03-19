from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.database import get_audit_session

from .core import (
    BoundaryContract,
    DatabaseTarget,
    ManagedAccessBoundary,
    SessionProvider,
)


@asynccontextmanager
async def _audit_session_provider() -> AsyncIterator[AsyncSession]:
    async with get_audit_session() as session:
        yield session


class AuditAccessBoundary(ManagedAccessBoundary):
    def __init__(
        self,
        *,
        session_provider: SessionProvider | None = None,
        session_provider_name: str = "app.audit.database.get_audit_session",
    ) -> None:
        super().__init__(
            contract=BoundaryContract(
                target=DatabaseTarget.AUDIT,
                session_provider=session_provider_name,
            ),
            session_provider=session_provider or _audit_session_provider,
        )


def get_audit_access_boundary() -> AuditAccessBoundary:
    return AuditAccessBoundary()


def create_audit_access_boundary_for_session(
    session: AsyncSession,
) -> AuditAccessBoundary:
    @asynccontextmanager
    async def _provided_session_provider() -> AsyncIterator[AsyncSession]:
        yield session

    return AuditAccessBoundary(
        session_provider=_provided_session_provider,
        session_provider_name="provided_async_session",
    )
