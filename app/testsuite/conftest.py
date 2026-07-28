"""Shared pytest configuration for the TCRT test suite.

Prevents cross-file aiosqlite thread leaks that cause segmentation faults
when many test files create and dispose async engines sequentially.
"""

from __future__ import annotations

import gc
import threading

import pytest


@pytest.fixture(autouse=True)
def _join_leaked_aiosqlite_threads():
    """Join leaked aiosqlite worker threads after each test.

    Each async test engine uses aiosqlite background threads.  If a thread
    survives engine disposal (e.g. the connection was created in a different
    event loop than the disposal call), it can segfault the interpreter when
    the next test file runs Alembic migrations.  This safety net joins any
    surviving threads between tests.
    """
    yield
    for thread in list(threading.enumerate()):
        if "aiosqlite" in getattr(thread, "name", ""):
            thread.join(timeout=3)
    gc.collect()


def pytest_collection_modifyitems(items):
    """Suppress PytestCollectionWarning for ORM/Enum classes whose names
    start with 'Test' but are not test classes."""
    for item in items:
        # These are legitimate production classes, not test classes.
        item.add_marker(pytest.mark.filterwarnings("ignore::pytest.PytestCollectionWarning"))
