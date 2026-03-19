from __future__ import annotations

from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import AsyncIterator, Awaitable, Callable, Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

T = TypeVar("T")

AsyncOperation = Callable[[AsyncSession], Awaitable[T]]
SyncOperation = Callable[[Session], T]
SessionProvider = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class DatabaseTarget(StrEnum):
    MAIN = "main"
    AUDIT = "audit"
    USM = "usm"


@dataclass(frozen=True)
class BoundaryContract:
    target: DatabaseTarget
    session_provider: str
    transaction_owner: str = "boundary"
    caller_contract: str = (
        "Callers must pass read/write operations into the boundary and must not "
        "open sessions, commit, or rollback directly."
    )


class ManagedAccessBoundary(Generic[T]):
    def __init__(self, contract: BoundaryContract, session_provider: SessionProvider):
        self.contract = contract
        self._session_provider = session_provider

    @property
    def target(self) -> DatabaseTarget:
        return self.contract.target

    @asynccontextmanager
    async def session_scope(self) -> AsyncIterator[AsyncSession]:
        async with self._session_provider() as session:
            yield session

    async def run_read(self, operation: AsyncOperation[T]) -> T:
        async with self.session_scope() as session:
            return await operation(session)

    async def run_write(self, operation: AsyncOperation[T]) -> T:
        async with self.session_scope() as session:
            try:
                result = await operation(session)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

    async def run_sync_read(self, operation: SyncOperation[T]) -> T:
        async with self.session_scope() as session:
            return await session.run_sync(operation)

    async def run_sync_write(self, operation: SyncOperation[T]) -> T:
        async with self.session_scope() as session:
            try:
                result = await session.run_sync(operation)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
