from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


_KEY_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"


class EnvParamInput(BaseModel):
    """Set/upsert a single parameter value (env shared or per-script override).

    For secret params, omit ``value`` (None) to keep the existing stored value
    untouched. For non-secret params, ``value`` is stored verbatim.
    """

    key: str = Field(..., min_length=1, max_length=120, pattern=_KEY_PATTERN)
    value: Optional[str] = None
    is_secret: bool = False


class EnvParamResponse(BaseModel):
    """Masked parameter readout — never returns a secret's plaintext."""

    key: str
    is_secret: bool
    is_set: bool
    value: Optional[str] = None       # plaintext for non-secret; None for secret
    fingerprint: Optional[str] = None  # ***wxyz for a set secret


def _clean_name(value: Optional[str]) -> Optional[str]:
    """Free-form environment name: trim surrounding whitespace; reject blank."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Name must not be blank")
    return cleaned


class EnvironmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    is_default: bool = False
    params: list[EnvParamInput] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _clean_name(value)


class EnvironmentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=60)
    is_default: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: Optional[str]) -> Optional[str]:
        return _clean_name(value)


class EnvironmentResponse(BaseModel):
    id: int
    team_id: int
    name: str
    is_default: bool
    params: list[EnvParamResponse] = Field(default_factory=list)
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ScriptEnvVarCell(BaseModel):
    """Effective value of one declared variable in one environment for a script."""

    environment_id: int
    environment_name: str
    key: str
    is_secret: bool
    is_set: bool
    source: Literal["shared", "override", "unset"]
    value: Optional[str] = None       # plaintext for non-secret; None for secret
    fingerprint: Optional[str] = None


class ScriptEnvVarsResponse(BaseModel):
    """The Script view variable modal payload: declared vars × environments."""

    script_id: int
    ref_path: str
    declared_vars: list[dict[str, Any]] = Field(default_factory=list)
    environments: list[dict[str, Any]] = Field(default_factory=list)
    cells: list[ScriptEnvVarCell] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)


class ScriptEnvVarInput(BaseModel):
    value: Optional[str] = None
    is_secret: bool = False


class EnvYamlImport(BaseModel):
    yaml: str = Field(..., description="Flat YAML mapping of {param_name: value}")
