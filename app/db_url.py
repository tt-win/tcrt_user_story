from __future__ import annotations

from typing import Tuple

SQLITE_ASYNC_SCHEME = "sqlite+aiosqlite://"
SQLITE_SYNC_SCHEME = "sqlite://"
MYSQL_ASYNC_SCHEME = "mysql+asyncmy://"
MYSQL_SYNC_SCHEME = "mysql+pymysql://"
POSTGRES_ASYNC_SCHEME = "postgresql+asyncpg://"
POSTGRES_SYNC_SCHEME = "postgresql+psycopg://"

MYSQL_REQUIRED_DRIVERS: Tuple[str, ...] = ("asyncmy", "PyMySQL")
POSTGRES_REQUIRED_DRIVERS: Tuple[str, ...] = ("asyncpg", "psycopg")
DRIVER_PACKAGE_IMPORT_MAP = {
    "asyncmy": "asyncmy",
    "PyMySQL": "pymysql",
    "asyncpg": "asyncpg",
    "psycopg": "psycopg",
}


def normalize_async_database_url(url: str) -> str:
    if url.startswith(SQLITE_ASYNC_SCHEME) or url.startswith(MYSQL_ASYNC_SCHEME) or url.startswith(POSTGRES_ASYNC_SCHEME):
        return url
    if url.startswith(SQLITE_SYNC_SCHEME):
        return url.replace(SQLITE_SYNC_SCHEME, SQLITE_ASYNC_SCHEME, 1)
    if url.startswith(MYSQL_SYNC_SCHEME) or url.startswith("mysql+aiomysql://") or url.startswith("mysql://"):
        prefix = url.split("://", 1)[0] + "://"
        return url.replace(prefix, MYSQL_ASYNC_SCHEME, 1)
    if url.startswith(POSTGRES_SYNC_SCHEME) or url.startswith("postgresql+psycopg2://") or url.startswith("postgresql://"):
        prefix = url.split("://", 1)[0] + "://"
        return url.replace(prefix, POSTGRES_ASYNC_SCHEME, 1)
    return url


def normalize_sync_database_url(url: str) -> str:
    if url.startswith(SQLITE_SYNC_SCHEME) or url.startswith(MYSQL_SYNC_SCHEME) or url.startswith(POSTGRES_SYNC_SCHEME):
        return url
    if url.startswith(SQLITE_ASYNC_SCHEME):
        return url.replace(SQLITE_ASYNC_SCHEME, SQLITE_SYNC_SCHEME, 1)
    if url.startswith(MYSQL_ASYNC_SCHEME) or url.startswith("mysql+aiomysql://") or url.startswith("mysql://"):
        prefix = url.split("://", 1)[0] + "://"
        return url.replace(prefix, MYSQL_SYNC_SCHEME, 1)
    if url.startswith(POSTGRES_ASYNC_SCHEME) or url.startswith("postgresql+psycopg2://") or url.startswith("postgresql://"):
        prefix = url.split("://", 1)[0] + "://"
        return url.replace(prefix, POSTGRES_SYNC_SCHEME, 1)
    return url


def required_driver_packages_for_url(url: str) -> Tuple[str, ...]:
    normalized_async = normalize_async_database_url(url)
    if normalized_async.startswith(MYSQL_ASYNC_SCHEME):
        return MYSQL_REQUIRED_DRIVERS
    if normalized_async.startswith(POSTGRES_ASYNC_SCHEME):
        return POSTGRES_REQUIRED_DRIVERS
    return ()


def required_driver_specs_for_url(url: str) -> Tuple[Tuple[str, str], ...]:
    return tuple(
        (package_name, DRIVER_PACKAGE_IMPORT_MAP[package_name])
        for package_name in required_driver_packages_for_url(url)
    )


def is_sqlite_url(url: str) -> bool:
    normalized_sync = normalize_sync_database_url(url)
    return normalized_sync.startswith(SQLITE_SYNC_SCHEME)
