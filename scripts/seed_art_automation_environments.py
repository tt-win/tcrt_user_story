#!/usr/bin/env python3
"""Seed automation environments (SIT, Prod) and script variables for team ART.

Sets up:
- Environments for team ART:
  - SIT (is_default=True, shared BASE_URL='http://localhost:8000')
  - Prod (is_default=False, shared BASE_URL='https://art.example.com')
- Per-script variable configurations (overrides/defaults) for all ART scripts.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy import select

from app.db_migrations import resolve_database_url
from app.db_url import normalize_async_database_url
from app.models.database_models import Team, AutomationScript
from app.services.automation.environment_service import EnvironmentService


async def seed_art_automation_environments():
    url = resolve_database_url("main")
    async_url = normalize_async_database_url(url)
    engine = create_async_engine(async_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        service = EnvironmentService(session)

        # 1. Locate Team ART
        team_result = await session.execute(
            select(Team).where(Team.name == "ART")
        )
        team = team_result.scalar_one_or_none()
        if not team:
            print("Error: Team 'ART' not found.")
            await engine.dispose()
            return

        team_id = team.id
        print(f"Found Team 'ART' (ID: {team_id})")

        # 2. Get existing environments
        existing_envs = await service.list_environments(team_id)
        env_map = {env.name: env for env in existing_envs}

        # Create SIT environment if not exists
        if "SIT" not in env_map:
            sit_env = await service.create_environment(
                team_id=team_id,
                name="SIT",
                is_default=True,
                params=[],
                actor="seed_script",
            )
            print(f"Created environment 'SIT' (ID: {sit_env.id})")
        else:
            sit_env = env_map["SIT"]
            if not sit_env.is_default:
                await service.set_default(team_id=team_id, env_id=sit_env.id, actor="seed_script")
            print(f"Environment 'SIT' already exists (ID: {sit_env.id})")

        # Create Prod environment if not exists
        if "Prod" not in env_map:
            prod_env = await service.create_environment(
                team_id=team_id,
                name="Prod",
                is_default=False,
                params=[],
                actor="seed_script",
            )
            print(f"Created environment 'Prod' (ID: {prod_env.id})")
        else:
            prod_env = env_map["Prod"]
            print(f"Environment 'Prod' already exists (ID: {prod_env.id})")

        # Re-fetch env details
        existing_envs = await service.list_environments(team_id)
        env_map = {env.name: env for env in existing_envs}
        sit_id = env_map["SIT"].id
        prod_id = env_map["Prod"].id

        # 3. Set shared params for SIT and Prod
        await service.set_param(
            team_id=team_id,
            env_id=sit_id,
            key="BASE_URL",
            value="http://localhost:8000",
            is_secret=False,
            actor="seed_script",
        )
        print("Set SIT shared param BASE_URL = 'http://localhost:8000'")

        await service.set_param(
            team_id=team_id,
            env_id=prod_id,
            key="BASE_URL",
            value="https://art.example.com",
            is_secret=False,
            actor="seed_script",
        )
        print("Set Prod shared param BASE_URL = 'https://art.example.com'")

        # 4. Configure script variables for all ART scripts
        scripts_res = await session.execute(
            select(AutomationScript).where(AutomationScript.team_id == team_id)
        )
        scripts = scripts_res.scalars().all()
        print(f"\nConfiguring script variables for {len(scripts)} scripts...")

        # Variable definitions per script:
        # {script_name: {var_key: {SIT_val, Prod_val}}}
        script_var_configs = {
            "test_case_batch_operations.py": {
                "BATCH_SIZE": ("10", "50"),
            },
            "test_case_editor.py": {
                "SAMPLE_CASE_TITLE": ("Sample Login Case (SIT)", "Sample Login Case (Prod)"),
            },
            "test_case_search.py": {
                "SEARCH_KEYWORD": ("TCG", "TCG"),
            },
            "test_landing_and_language.py": {
                "DEFAULT_LOCALE": ("en-US", "en-US"),
            },
            "test_run_management.py": {
                "RUN_CONFIG_NAME": ("Nightly Regression", "Prod Regression Config"),
            },
            "test_team_management.py": {
                "SEED_TEAM_NAME": ("QA Sample Team (SIT)", "QA Sample Team (Prod)"),
            },
            "test_user_story_map.py": {
                "USM_ROOT_NODE": ("Root Story (SIT)", "Root Story (Prod)"),
            },
        }

        for script in scripts:
            var_cfg = script_var_configs.get(script.name, {})
            for var_key, (sit_val, prod_val) in var_cfg.items():
                # Set SIT override
                await service.set_script_override(
                    team_id=team_id,
                    script_id=script.id,
                    env_id=sit_id,
                    key=var_key,
                    value=sit_val,
                    is_secret=False,
                    actor="seed_script",
                )
                # Set Prod override
                await service.set_script_override(
                    team_id=team_id,
                    script_id=script.id,
                    env_id=prod_id,
                    key=var_key,
                    value=prod_val,
                    is_secret=False,
                    actor="seed_script",
                )
                print(f"  [{script.name}] {var_key}: SIT='{sit_val}', Prod='{prod_val}'")

        await session.commit()
        print("\nSuccessfully committed automation environments and script variables for Team ART.")

        # 5. Verification: Check script env vars for all scripts
        print("\n--- Verification Summary ---")
        for script in scripts:
            env_vars_resp = await service.get_script_env_vars(team_id=team_id, script_id=script.id)
            print(f"Script: {script.name} (ID: {script.id})")
            print(f"  Coverage: {env_vars_resp.coverage}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_art_automation_environments())
