"""Tests for the AllureConfig / AutomationProviderConfig env+yaml plumbing.

These cover the org-level Allure settings introduced for Jenkins suite-job
rendering — config.yaml is the source of truth, env vars override, and the
absence of either disables the integration (empty base_url).
"""
from __future__ import annotations

import pytest

from app.config import AllureConfig, AutomationProviderConfig


def test_allure_config_defaults():
    cfg = AllureConfig()
    # Empty base_url signals "disabled"; the project_id template ships with a
    # per-script/per-suite default (each in its own Allure project) so users
    # only have to set base_url to opt in.
    assert cfg.base_url == ""
    assert cfg.api_token == ""
    assert cfg.project_id_template == "tcrt-team-{team_slug}-{suite_slug}-{suite_id}"


def test_allure_config_from_env_uses_yaml_fallback(monkeypatch):
    monkeypatch.delenv("ALLURE_BASE_URL", raising=False)
    monkeypatch.delenv("ALLURE_API_TOKEN", raising=False)
    monkeypatch.delenv("ALLURE_PROJECT_ID_TEMPLATE", raising=False)

    yaml_loaded = AllureConfig(
        base_url="http://allure.internal:5050",
        api_token="yaml-token",
        project_id_template="tcrt-suite-{suite_id}",
    )
    resolved = AllureConfig.from_env(yaml_loaded)

    assert resolved.base_url == "http://allure.internal:5050"
    assert resolved.api_token == "yaml-token"
    assert resolved.project_id_template == "tcrt-suite-{suite_id}"


def test_allure_config_env_overrides_yaml(monkeypatch):
    monkeypatch.setenv("ALLURE_BASE_URL", "http://override:5050")
    monkeypatch.setenv("ALLURE_API_TOKEN", "env-token")
    monkeypatch.setenv("ALLURE_PROJECT_ID_TEMPLATE", "tcrt-org")

    yaml_loaded = AllureConfig(
        base_url="http://yaml:5050",
        api_token="yaml-token",
        project_id_template="tcrt-team-{team_slug}",
    )
    resolved = AllureConfig.from_env(yaml_loaded)

    assert resolved.base_url == "http://override:5050"
    assert resolved.api_token == "env-token"
    assert resolved.project_id_template == "tcrt-org"


def test_automation_provider_config_chains_allure(monkeypatch):
    # AUTOMATION_PROVIDER_ENCRYPTION_KEY is commonly set in the dev shell
    # so callers can decrypt provider credentials. Clear it here so the test
    # observes the yaml fallback path rather than the developer's real key.
    monkeypatch.delenv("AUTOMATION_PROVIDER_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("ALLURE_BASE_URL", "http://from-env:5050")

    yaml_loaded = AutomationProviderConfig(
        encryption_key="key-from-yaml",
        allure=AllureConfig(base_url="http://from-yaml:5050"),
    )
    resolved = AutomationProviderConfig.from_env(yaml_loaded)

    assert resolved.encryption_key == "key-from-yaml"
    assert resolved.allure.base_url == "http://from-env:5050"
