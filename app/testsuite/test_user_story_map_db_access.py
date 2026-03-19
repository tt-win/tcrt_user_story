from json import JSONDecodeError
from types import SimpleNamespace

import pytest

from app.api.user_story_maps import _get_usm_map, _get_usm_node, _load_team_record


class _FakeScalarResult:
    def __init__(self, value=None, error=None):
        self._value = value
        self._error = error

    def scalar_one_or_none(self):
        if self._error is not None:
            raise self._error
        return self._value


class _FakeSession:
    def __init__(self, results):
        self._results = list(results)
        self._index = 0
        self.commit_calls = 0
        self.flush_calls = 0

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        result = self._results[self._index]
        self._index += 1
        return result

    async def commit(self):
        self.commit_calls += 1

    async def flush(self):
        self.flush_calls += 1


class _FakeMainBoundary:
    def __init__(self, team):
        self._team = team

    async def run_read(self, operation):
        session = _FakeSession([_FakeScalarResult(self._team)])
        return await operation(session)


class _FakeCoordinator:
    def __init__(self, team):
        self.main = _FakeMainBoundary(team)


@pytest.mark.asyncio
async def test_load_team_record_returns_team_payload():
    coordinator = _FakeCoordinator(SimpleNamespace(id=7, name="Platform"))

    team_record = await _load_team_record(coordinator, 7)

    assert team_record == {"id": 7, "name": "Platform"}


@pytest.mark.asyncio
async def test_load_team_record_returns_none_when_team_missing():
    coordinator = _FakeCoordinator(None)

    team_record = await _load_team_record(coordinator, 7)

    assert team_record is None


@pytest.mark.asyncio
async def test_get_usm_map_repair_uses_flush_when_persist_repair_false():
    repaired_map = SimpleNamespace(id=11, team_id=5)
    session = _FakeSession(
        [
            _FakeScalarResult(error=JSONDecodeError("broken", "{}", 0)),
            _FakeScalarResult(),
            _FakeScalarResult(repaired_map),
        ]
    )

    result = await _get_usm_map(session, 11, persist_repair=False)

    assert result is repaired_map
    assert session.flush_calls == 1
    assert session.commit_calls == 0


@pytest.mark.asyncio
async def test_get_usm_node_repair_uses_flush_when_persist_repair_false():
    repaired_node = SimpleNamespace(map_id=11, node_id="node-1")
    session = _FakeSession(
        [
            _FakeScalarResult(error=JSONDecodeError("broken", "{}", 0)),
            _FakeScalarResult(),
            _FakeScalarResult(repaired_node),
        ]
    )

    result = await _get_usm_node(session, 11, "node-1", persist_repair=False)

    assert result is repaired_node
    assert session.flush_calls == 1
    assert session.commit_calls == 0
