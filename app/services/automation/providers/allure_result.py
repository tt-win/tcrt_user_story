from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from app.services.automation.providers.base import HealthStatus


class AllureResultConfig(BaseModel):
    base_url: str = Field(
        description=(
            "Allure service root, e.g. http://allure.internal:5050 for "
            "allure-docker-service. Must be reachable from the user's browser."
        ),
    )
    run_url_template: str | None = Field(
        default=None,
        description=(
            "Optional URL template for backfilling report_url when CI does not "
            "post one. Leave empty when using allure-docker-service — there is "
            "no reliable mapping from CI run id to Allure report id, so CI must "
            "POST the real report_url via the run-status webhook. Available "
            "placeholders: {base_url}, {project}, {ci_external_run_id}."
        ),
    )
    embed_mode: Literal["link", "iframe"] = "link"
    project: str | None = Field(
        default=None,
        description="Allure project id (allure-docker-service multi-project setups).",
    )
    dashboard_url: str | None = None


class AllureResultCredentials(BaseModel):
    api_token: str | None = None


class AllureResultProvider:
    display_name = "Allure Report"

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self.config = AllureResultConfig.model_validate(config)
        self.credentials = AllureResultCredentials.model_validate(credentials)

    @classmethod
    def config_schema(cls) -> type[BaseModel]:
        return AllureResultConfig

    @classmethod
    def credential_schema(cls) -> type[BaseModel]:
        return AllureResultCredentials

    async def get_run_report_url(self, ci_external_run_id: str) -> str | None:
        if not ci_external_run_id:
            return None
        template = self.config.run_url_template
        if not template:
            return None
        return template.format(
            base_url=self.config.base_url.rstrip("/"),
            ci_external_run_id=ci_external_run_id,
            project=self.config.project or "",
        )

    async def get_dashboard_url(self) -> str | None:
        return self.config.dashboard_url

    async def health_check(self) -> HealthStatus:
        headers = {}
        if self.credentials.api_token:
            headers["Authorization"] = f"Bearer {self.credentials.api_token}"
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(self.config.base_url, headers=headers)
                response.raise_for_status()
            return HealthStatus(status="OK", message=f"Allure endpoint returned {response.status_code}")
        except Exception as exc:
            return HealthStatus(status="FAILED", message=str(exc))
