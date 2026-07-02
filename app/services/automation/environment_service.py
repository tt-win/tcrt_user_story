"""Automation environment config management (TCRT-managed, team-scoped).

Three layers (see manage-automation-environment-configs):
- environment catalog: `automation_environments` (user-defined per team)
- environment shared params: `automation_environment_params`
- per-script override values: `automation_script_env_vars`

A (script, env, key) effective value = per-script override if present, else the
environment shared value. Secret values are AES-256-GCM encrypted at rest and
NEVER returned in plaintext through the response builders here.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import yaml
from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.automation_environment import (
    EnvParamResponse,
    EnvironmentResponse,
    ScriptEnvVarCell,
    ScriptEnvVarsResponse,
)
from app.services.automation.marker_parse import _find_var_usage_sites
from app.models.database_models import (
    AutomationEnvironment,
    AutomationEnvironmentParam,
    AutomationScript,
    AutomationScriptEnvVar,
    TestRunSet,
)
from app.services.automation.provider_credential_service import (
    decrypt_value,
    encrypt_value,
    encrypted_value_fingerprint,
)


def _utcnow() -> datetime:
    return datetime.utcnow()


def _http_404(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": code, "message": message})


class EnvironmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------- value storage helpers ----------

    @staticmethod
    def _store_value(obj: Any, value: str | None, is_secret: bool) -> None:
        """Write value onto a param/override ORM object with correct column.

        For secrets, a None/blank value leaves the existing encrypted value
        untouched (so masked edit forms can omit it)."""
        obj.is_secret = is_secret
        if is_secret:
            if value:  # only overwrite when a real new secret is supplied
                obj.value_encrypted = encrypt_value(value)
                obj.value_plaintext = None
        else:
            obj.value_plaintext = value or ""
            obj.value_encrypted = None

    @staticmethod
    def _is_set(obj: Any) -> bool:
        if obj is None:
            return False
        if obj.is_secret:
            return bool(obj.value_encrypted)
        return obj.value_plaintext is not None

    @classmethod
    def _decrypted(cls, obj: Any) -> str | None:
        if obj is None or not cls._is_set(obj):
            return None
        return decrypt_value(obj.value_encrypted) if obj.is_secret else obj.value_plaintext

    @classmethod
    def _param_to_response(cls, obj: Any) -> EnvParamResponse:
        return EnvParamResponse(
            key=obj.key,
            is_secret=obj.is_secret,
            is_set=cls._is_set(obj),
            value=None if obj.is_secret else obj.value_plaintext,
            fingerprint=encrypted_value_fingerprint(obj.value_encrypted) if obj.is_secret else None,
        )

    def _env_to_response(self, env: AutomationEnvironment) -> EnvironmentResponse:
        return EnvironmentResponse(
            id=env.id,
            team_id=env.team_id,
            name=env.name,
            is_default=env.is_default,
            params=[self._param_to_response(p) for p in sorted(env.params, key=lambda p: p.key)],
            created_by=env.created_by,
            updated_by=env.updated_by,
            created_at=env.created_at,
            updated_at=env.updated_at,
        )

    # ---------- environment catalog ----------

    async def list_environments(self, team_id: int) -> list[EnvironmentResponse]:
        result = await self.session.execute(
            select(AutomationEnvironment)
            .where(AutomationEnvironment.team_id == team_id)
            .options(selectinload(AutomationEnvironment.params))
            .order_by(AutomationEnvironment.name)
        )
        return [self._env_to_response(env) for env in result.scalars().all()]

    async def list_declared_variables(self, *, team_id: int) -> list[dict[str, Any]]:
        """Aggregate variable names declared (via TCRT_VARS) across the team's
        scanned scripts, so the env-param editor can suggest them instead of
        making the user retype names. Distinct by name; ``secret`` / ``required``
        are True if ANY declaring script marks them so."""
        result = await self.session.execute(
            select(AutomationScript.ref_path, AutomationScript.declared_vars_json)
            .where(AutomationScript.team_id == team_id)
        )
        agg: dict[str, dict[str, Any]] = {}
        for ref_path, dv_json in result.all():
            try:
                declared = json.loads(dv_json or "[]")
            except (json.JSONDecodeError, TypeError):
                declared = []
            if not isinstance(declared, list):
                continue
            for dv in declared:
                name = dv.get("name") if isinstance(dv, dict) else None
                if not name:
                    continue
                entry = agg.setdefault(
                    name, {"name": name, "secret": False, "required": False, "scripts": set()}
                )
                entry["secret"] = entry["secret"] or bool(dv.get("secret"))
                entry["required"] = entry["required"] or bool(dv.get("required", True))
                if ref_path:
                    entry["scripts"].add(ref_path)
        return [
            {
                "name": e["name"],
                "secret": e["secret"],
                "required": e["required"],
                "scripts": sorted(e["scripts"]),
            }
            for e in sorted(agg.values(), key=lambda x: x["name"])
        ]

    async def _get_env(self, team_id: int, env_id: int) -> AutomationEnvironment:
        result = await self.session.execute(
            select(AutomationEnvironment)
            .where(AutomationEnvironment.id == env_id, AutomationEnvironment.team_id == team_id)
            .options(selectinload(AutomationEnvironment.params))
        )
        env = result.scalar_one_or_none()
        if env is None:
            raise _http_404("ENVIRONMENT_NOT_FOUND", f"Environment {env_id} not found")
        return env

    async def get_environment(self, team_id: int, env_id: int) -> EnvironmentResponse:
        return self._env_to_response(await self._get_env(team_id, env_id))

    async def create_environment(
        self,
        *,
        team_id: int,
        name: str,
        is_default: bool,
        params: list[Any],
        actor: str | None,
    ) -> EnvironmentResponse:
        now = _utcnow()
        env = AutomationEnvironment(
            team_id=team_id,
            name=name,
            is_default=False,
            created_by=actor,
            updated_by=actor,
            created_at=now,
            updated_at=now,
        )
        self.session.add(env)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "DUPLICATE_ENVIRONMENT", "message": f"Environment '{name}' already exists"},
            ) from exc

        for p in params:
            param = AutomationEnvironmentParam(
                environment_id=env.id, key=p.key, created_by=actor, updated_by=actor,
                created_at=now, updated_at=now,
            )
            self._store_value(param, p.value, p.is_secret)
            self.session.add(param)

        if is_default:
            await self._set_default_unsafe(team_id, env.id, actor)
        await self.session.flush()
        return await self.get_environment(team_id, env.id)

    async def update_environment(
        self, *, team_id: int, env_id: int, name: Any, is_default: Any, actor: str | None
    ) -> EnvironmentResponse:
        env = await self._get_env(team_id, env_id)
        if name is not None and name != env.name:
            old_name = env.name
            env.name = name
            try:
                await self.session.flush()
            except IntegrityError as exc:
                await self.session.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "DUPLICATE_ENVIRONMENT", "message": f"Environment '{name}' already exists"},
                ) from exc
            # Test run sets reference the environment by name (not id), so keep
            # their stored default in sync — a rename must not orphan them.
            await self.session.execute(
                update(TestRunSet)
                .where(
                    TestRunSet.team_id == team_id,
                    TestRunSet.default_automation_environment == old_name,
                )
                .values(default_automation_environment=name)
            )
        env.updated_by = actor
        env.updated_at = _utcnow()
        if is_default is True:
            await self._set_default_unsafe(team_id, env_id, actor)
        await self.session.flush()
        return await self.get_environment(team_id, env_id)

    async def delete_environment(self, *, team_id: int, env_id: int) -> str:
        env = await self._get_env(team_id, env_id)
        name = env.name
        await self.session.delete(env)
        await self.session.flush()
        return name

    async def _set_default_unsafe(self, team_id: int, env_id: int, actor: str | None) -> None:
        result = await self.session.execute(
            select(AutomationEnvironment).where(AutomationEnvironment.team_id == team_id)
        )
        for env in result.scalars().all():
            env.is_default = env.id == env_id
            env.updated_by = actor

    async def set_default(self, *, team_id: int, env_id: int, actor: str | None) -> EnvironmentResponse:
        await self._get_env(team_id, env_id)
        await self._set_default_unsafe(team_id, env_id, actor)
        await self.session.flush()
        return await self.get_environment(team_id, env_id)

    # ---------- environment shared params ----------

    async def set_param(
        self, *, team_id: int, env_id: int, key: str, value: str | None, is_secret: bool, actor: str | None
    ) -> EnvParamResponse:
        await self._get_env(team_id, env_id)
        result = await self.session.execute(
            select(AutomationEnvironmentParam).where(
                AutomationEnvironmentParam.environment_id == env_id,
                AutomationEnvironmentParam.key == key,
            )
        )
        param = result.scalar_one_or_none()
        now = _utcnow()
        if param is None:
            param = AutomationEnvironmentParam(
                environment_id=env_id, key=key, created_by=actor, updated_by=actor,
                created_at=now, updated_at=now,
            )
            self.session.add(param)
        else:
            param.updated_by = actor
            param.updated_at = now
        self._store_value(param, value, is_secret)
        await self.session.flush()
        return self._param_to_response(param)

    async def delete_param(self, *, team_id: int, env_id: int, key: str) -> None:
        await self._get_env(team_id, env_id)
        result = await self.session.execute(
            select(AutomationEnvironmentParam).where(
                AutomationEnvironmentParam.environment_id == env_id,
                AutomationEnvironmentParam.key == key,
            )
        )
        param = result.scalar_one_or_none()
        if param is not None:
            await self.session.delete(param)
            await self.session.flush()

    # ---------- per-script overrides ----------

    async def _get_script(self, team_id: int, script_id: int) -> AutomationScript:
        result = await self.session.execute(
            select(AutomationScript).where(
                AutomationScript.id == script_id, AutomationScript.team_id == team_id
            )
        )
        script = result.scalar_one_or_none()
        if script is None:
            raise _http_404("SCRIPT_NOT_FOUND", f"Script {script_id} not found")
        return script

    async def set_script_override(
        self, *, team_id: int, script_id: int, env_id: int, key: str,
        value: str | None, is_secret: bool, actor: str | None,
    ) -> ScriptEnvVarCell:
        script = await self._get_script(team_id, script_id)
        env = await self._get_env(team_id, env_id)
        result = await self.session.execute(
            select(AutomationScriptEnvVar).where(
                AutomationScriptEnvVar.automation_script_id == script_id,
                AutomationScriptEnvVar.environment_id == env_id,
                AutomationScriptEnvVar.key == key,
            )
        )
        override = result.scalar_one_or_none()
        now = _utcnow()
        if override is None:
            override = AutomationScriptEnvVar(
                team_id=team_id, automation_script_id=script_id, script_ref_path=script.ref_path,
                environment_id=env_id, key=key, created_by=actor, updated_by=actor,
                created_at=now, updated_at=now,
            )
            self.session.add(override)
        else:
            override.script_ref_path = script.ref_path
            override.updated_by = actor
            override.updated_at = now
        self._store_value(override, value, is_secret)
        await self.session.flush()
        return ScriptEnvVarCell(
            environment_id=env_id, environment_name=env.name, key=key,
            is_secret=override.is_secret, is_set=self._is_set(override), source="override",
            value=None if override.is_secret else override.value_plaintext,
            fingerprint=encrypted_value_fingerprint(override.value_encrypted) if override.is_secret else None,
        )

    async def delete_script_override(self, *, team_id: int, script_id: int, env_id: int, key: str) -> None:
        result = await self.session.execute(
            select(AutomationScriptEnvVar).where(
                AutomationScriptEnvVar.automation_script_id == script_id,
                AutomationScriptEnvVar.environment_id == env_id,
                AutomationScriptEnvVar.key == key,
            )
        )
        override = result.scalar_one_or_none()
        if override is not None:
            await self.session.delete(override)
            await self.session.flush()

    # ---------- effective resolution (shared ⊕ override) ----------

    async def _shared_params(self, env_id: int) -> dict[str, AutomationEnvironmentParam]:
        result = await self.session.execute(
            select(AutomationEnvironmentParam).where(AutomationEnvironmentParam.environment_id == env_id)
        )
        return {p.key: p for p in result.scalars().all()}

    async def _script_overrides(self, script_id: int, env_id: int) -> dict[str, AutomationScriptEnvVar]:
        result = await self.session.execute(
            select(AutomationScriptEnvVar).where(
                AutomationScriptEnvVar.automation_script_id == script_id,
                AutomationScriptEnvVar.environment_id == env_id,
            )
        )
        return {o.key: o for o in result.scalars().all()}

    @staticmethod
    def _declared_vars(script: AutomationScript) -> list[dict[str, Any]]:
        try:
            data = json.loads(script.declared_vars_json or "[]")
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    async def get_script_env_vars(self, *, team_id: int, script_id: int) -> ScriptEnvVarsResponse:
        script = await self._get_script(team_id, script_id)
        declared = self._declared_vars(script)
        usage_by_name = _find_var_usage_sites(
            script.cached_content or "", [dv["name"] for dv in declared if dv.get("name")]
        )
        for dv in declared:
            dv["usage"] = usage_by_name.get(dv.get("name") or "", {"sites": [], "truncated": False})
        envs_result = await self.session.execute(
            select(AutomationEnvironment).where(AutomationEnvironment.team_id == team_id).order_by(AutomationEnvironment.name)
        )
        envs = list(envs_result.scalars().all())
        cells: list[ScriptEnvVarCell] = []
        coverage: dict[str, Any] = {}
        for env in envs:
            shared = await self._shared_params(env.id)
            overrides = await self._script_overrides(script_id, env.id)
            missing_required: list[str] = []
            for dv in declared:
                key = dv.get("name")
                if not key:
                    continue
                ov = overrides.get(key)
                sh = shared.get(key)
                effective = ov if ov is not None else sh
                source = "override" if ov is not None else ("shared" if sh is not None else "unset")
                is_set = self._is_set(effective)
                is_secret = effective.is_secret if effective is not None else bool(dv.get("secret"))
                cells.append(ScriptEnvVarCell(
                    environment_id=env.id, environment_name=env.name, key=key,
                    is_secret=is_secret, is_set=is_set, source=source,
                    value=None if (is_secret or effective is None) else effective.value_plaintext,
                    fingerprint=(encrypted_value_fingerprint(effective.value_encrypted)
                                 if (effective is not None and effective.is_secret) else None),
                ))
                if dv.get("required", True) and not is_set:
                    missing_required.append(key)
            coverage[env.name] = {"missing_required": missing_required}
        return ScriptEnvVarsResponse(
            script_id=script.id, ref_path=script.ref_path, declared_vars=declared,
            environments=[{"id": e.id, "name": e.name, "is_default": e.is_default} for e in envs],
            cells=cells, coverage=coverage,
        )

    async def resolve_effective_bundle(
        self, *, team_id: int, env_id: int, scripts: list[AutomationScript]
    ) -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
        """For a suite's scripts under one environment, return:
        - bundle: {ref_path: {KEY: decrypted_value}} for the script's declared vars
        - missing: {ref_path: [required keys without an effective value]}
        Used by run-automation trigger (see test-run-management-ui)."""
        shared = await self._shared_params(env_id)
        bundle: dict[str, dict[str, str]] = {}
        missing: dict[str, list[str]] = {}
        for script in scripts:
            declared = self._declared_vars(script)
            if not declared:
                continue
            overrides = await self._script_overrides(script.id, env_id)
            resolved: dict[str, str] = {}
            miss: list[str] = []
            for dv in declared:
                key = dv.get("name")
                if not key:
                    continue
                effective = overrides.get(key) or shared.get(key)
                value = self._decrypted(effective)
                if value is not None:
                    resolved[key] = value
                elif dv.get("required", True):
                    miss.append(key)
            if resolved:
                bundle[script.ref_path] = resolved
            if miss:
                missing[script.ref_path] = miss
        return bundle, missing

    # ---------- YAML import / export ----------

    async def import_params(self, *, team_id: int, env_id: int, yaml_text: str, actor: str | None) -> int:
        await self._get_env(team_id, env_id)
        try:
            data = yaml.safe_load(yaml_text) or {}
        except yaml.YAMLError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_YAML", "message": str(exc)},
            ) from exc
        if not isinstance(data, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_YAML", "message": "Expected a flat mapping of {param: value}"},
            )
        existing = await self._shared_params(env_id)
        count = 0
        for key, value in data.items():
            if not isinstance(key, str):
                continue
            # Preserve existing secret flag; default new keys to non-secret.
            is_secret = existing[key].is_secret if key in existing else False
            await self.set_param(
                team_id=team_id, env_id=env_id, key=key,
                value=None if value is None else str(value), is_secret=is_secret, actor=actor,
            )
            count += 1
        return count

    async def export_params(self, *, team_id: int, env_id: int) -> str:
        env = await self._get_env(team_id, env_id)
        out: dict[str, Any] = {}
        for p in sorted(env.params, key=lambda p: p.key):
            out[p.key] = "***" if p.is_secret else (p.value_plaintext or "")
        return yaml.safe_dump(out, allow_unicode=True, sort_keys=True, default_flow_style=False)
