"""App token principal and scope constants for external API authentication."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


APP_TOKEN_PREFIX = "tcrt_app_"
APP_TOKEN_RANDOM_BYTES = 32
APP_TOKEN_PREFIX_DISPLAY_LEN = 16
APP_TOKEN_DEFAULT_EXPIRY_DAYS = 90
APP_TOKEN_LAST_USED_THROTTLE_SECONDS = 60


SCOPE_TEST_CASE_READ = "test_case:read"
SCOPE_TEST_CASE_WRITE = "test_case:write"
SCOPE_TEST_CASE_ADMIN = "test_case:admin"
SCOPE_TEST_RUN_READ = "test_run:read"
SCOPE_TEST_RUN_WRITE = "test_run:write"
SCOPE_TEST_RUN_EXECUTE = "test_run:execute"
SCOPE_TEST_RUN_ADMIN = "test_run:admin"
SCOPE_AUTOMATION_EXECUTE = "automation:execute"

ALL_APP_TOKEN_SCOPES = frozenset(
    {
        SCOPE_TEST_CASE_READ,
        SCOPE_TEST_CASE_WRITE,
        SCOPE_TEST_CASE_ADMIN,
        SCOPE_TEST_RUN_READ,
        SCOPE_TEST_RUN_WRITE,
        SCOPE_TEST_RUN_EXECUTE,
        SCOPE_TEST_RUN_ADMIN,
        SCOPE_AUTOMATION_EXECUTE,
    }
)

READ_SCOPES = frozenset(
    {
        SCOPE_TEST_CASE_READ,
        SCOPE_TEST_RUN_READ,
    }
)


class AppTokenPrincipal(BaseModel):
    """App token principal resolved from a valid app token or legacy machine credential."""

    credential_id: int
    credential_name: str
    owner_team_id: Optional[int] = None
    scopes: List[str] = Field(default_factory=list)
    allow_all_teams: bool = False
    team_scope_ids: List[int] = Field(default_factory=list)
    is_legacy: bool = False
    legacy_permission: Optional[str] = None

    def can_access_team(self, team_id: int) -> bool:
        if self.allow_all_teams:
            return True
        if self.owner_team_id is not None and team_id == self.owner_team_id:
            return True
        return team_id in self.team_scope_ids

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def has_any_scope(self, *scopes: str) -> bool:
        scope_set = set(self.scopes)
        return any(s in scope_set for s in scopes)

    @property
    def audit_actor(self) -> str:
        return f"app-token:{self.credential_name}"
