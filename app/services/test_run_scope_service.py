import json
from typing import Dict, Iterable, List, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..models.database_models import (
    TestCaseLocal as TestCaseLocalDB,
    TestCaseSet as TestCaseSetDB,
    TestRunConfig as TestRunConfigDB,
    TestRunItem as TestRunItemDB,
)


class TestRunScopeService:
    @staticmethod
    def normalize_scope_ids(scope_ids: Optional[Iterable[int]]) -> List[int]:
        normalized: List[int] = []
        seen = set()
        for raw in scope_ids or []:
            try:
                set_id = int(raw)
            except (TypeError, ValueError):
                continue
            if set_id <= 0 or set_id in seen:
                continue
            seen.add(set_id)
            normalized.append(set_id)
        return normalized

    @classmethod
    def parse_scope_ids_json(cls, raw_json: Optional[str]) -> List[int]:
        if not raw_json:
            return []
        try:
            parsed = json.loads(raw_json)
        except (TypeError, ValueError):
            return []
        if isinstance(parsed, list):
            return cls.normalize_scope_ids(parsed)
        return cls.normalize_scope_ids([parsed])

    @classmethod
    def dump_scope_ids_json(cls, scope_ids: Optional[Iterable[int]]) -> Optional[str]:
        normalized = cls.normalize_scope_ids(scope_ids)
        if not normalized:
            return None
        return json.dumps(normalized, ensure_ascii=False)

    @classmethod
    def derive_scope_ids_from_items(
        cls,
        db: Session,
        team_id: int,
        config_id: int,
    ) -> List[int]:
        rows = (
            db.query(TestCaseLocalDB.test_case_set_id)
            .join(
                TestRunItemDB,
                and_(
                    TestRunItemDB.team_id == TestCaseLocalDB.team_id,
                    TestRunItemDB.test_case_number == TestCaseLocalDB.test_case_number,
                ),
            )
            .filter(
                TestRunItemDB.team_id == team_id,
                TestRunItemDB.config_id == config_id,
            )
            .distinct()
            .all()
        )
        return cls.normalize_scope_ids([row[0] for row in rows if row and row[0] is not None])

    @classmethod
    def get_config_scope_ids(
        cls,
        db: Session,
        config: TestRunConfigDB,
        allow_fallback: bool = True,
        persist_fallback: bool = False,
    ) -> List[int]:
        explicit_scope = cls.parse_scope_ids_json(getattr(config, "test_case_set_ids_json", None))
        if explicit_scope:
            return explicit_scope
        if not allow_fallback:
            return []

        fallback_scope = cls.derive_scope_ids_from_items(db, config.team_id, config.id)
        if fallback_scope and persist_fallback:
            config.test_case_set_ids_json = cls.dump_scope_ids_json(fallback_scope)
        return fallback_scope

    @classmethod
    def set_config_scope_ids(cls, config: TestRunConfigDB, scope_ids: Iterable[int]) -> None:
        config.test_case_set_ids_json = cls.dump_scope_ids_json(scope_ids)

    @classmethod
    def validate_scope_ids(
        cls,
        db: Session,
        team_id: int,
        scope_ids: Optional[Iterable[int]],
        allow_empty: bool = False,
    ) -> List[int]:
        normalized = cls.normalize_scope_ids(scope_ids)
        if not normalized and not allow_empty:
            raise ValueError("至少需要選擇一個 Test Case Set")

        if not normalized:
            return []

        valid_rows = (
            db.query(TestCaseSetDB.id)
            .filter(
                TestCaseSetDB.team_id == team_id,
                TestCaseSetDB.id.in_(normalized),
            )
            .all()
        )
        valid_ids = {row[0] for row in valid_rows}
        missing_ids = [sid for sid in normalized if sid not in valid_ids]
        if missing_ids:
            raise ValueError(f"以下 Test Case Set 不存在或不屬於團隊 {team_id}: {missing_ids}")
        return normalized

    @classmethod
    def _summarize_impact_rows(cls, rows: List[dict]) -> dict:
        impacted_map: Dict[int, dict] = {}
        impacted_item_ids: List[int] = []
        for row in rows:
            item_id = int(row["item_id"])
            config_id = int(row["config_id"])
            config_name = row.get("config_name") or f"Test Run #{config_id}"
            impacted_item_ids.append(item_id)

            info = impacted_map.get(config_id)
            if info is None:
                impacted_map[config_id] = {
                    "config_id": config_id,
                    "config_name": config_name,
                    "removed_item_count": 1,
                }
            else:
                info["removed_item_count"] += 1

        impacted_runs = sorted(
            impacted_map.values(),
            key=lambda item: (-item["removed_item_count"], item["config_id"]),
        )
        return {
            "impacted_item_ids": impacted_item_ids,
            "impacted_test_runs": impacted_runs,
            "removed_item_count": len(impacted_item_ids),
        }

    @classmethod
    def _build_rows_for_removed_sets(
        cls,
        db: Session,
        team_id: int,
        removed_set_ids: List[int],
        config_id: Optional[int] = None,
    ) -> List[dict]:
        if not removed_set_ids:
            return []
        query = (
            db.query(
                TestRunItemDB.id.label("item_id"),
                TestRunItemDB.config_id.label("config_id"),
                TestRunConfigDB.name.label("config_name"),
            )
            .join(TestRunConfigDB, TestRunConfigDB.id == TestRunItemDB.config_id)
            .join(
                TestCaseLocalDB,
                and_(
                    TestCaseLocalDB.team_id == TestRunItemDB.team_id,
                    TestCaseLocalDB.test_case_number == TestRunItemDB.test_case_number,
                ),
            )
            .filter(
                TestRunItemDB.team_id == team_id,
                TestCaseLocalDB.test_case_set_id.in_(removed_set_ids),
            )
        )
        if config_id is not None:
            query = query.filter(TestRunItemDB.config_id == config_id)
        rows = query.all()
        return [
            {
                "item_id": row.item_id,
                "config_id": row.config_id,
                "config_name": row.config_name,
            }
            for row in rows
        ]

    @classmethod
    def _derive_scope_ids_for_configs(
        cls,
        db: Session,
        team_id: int,
        config_ids: List[int],
    ) -> Dict[int, List[int]]:
        if not config_ids:
            return {}
        rows = (
            db.query(
                TestRunItemDB.config_id,
                TestCaseLocalDB.test_case_set_id,
            )
            .join(
                TestCaseLocalDB,
                and_(
                    TestCaseLocalDB.team_id == TestRunItemDB.team_id,
                    TestCaseLocalDB.test_case_number == TestRunItemDB.test_case_number,
                ),
            )
            .filter(
                TestRunItemDB.team_id == team_id,
                TestRunItemDB.config_id.in_(config_ids),
            )
            .distinct()
            .all()
        )
        grouped: Dict[int, List[int]] = {}
        for config_id, set_id in rows:
            if set_id is None:
                continue
            grouped.setdefault(config_id, []).append(set_id)
        return {
            config_id: cls.normalize_scope_ids(set_ids)
            for config_id, set_ids in grouped.items()
        }

    @classmethod
    def _build_rows_for_case_move(
        cls,
        db: Session,
        team_id: int,
        case_numbers: List[str],
        target_set_id: int,
    ) -> List[dict]:
        cleaned_numbers = [num.strip() for num in case_numbers if num and str(num).strip()]
        if not cleaned_numbers:
            return []

        rows = (
            db.query(
                TestRunItemDB.id.label("item_id"),
                TestRunItemDB.config_id.label("config_id"),
                TestRunConfigDB.name.label("config_name"),
                TestRunConfigDB.test_case_set_ids_json.label("scope_json"),
            )
            .join(TestRunConfigDB, TestRunConfigDB.id == TestRunItemDB.config_id)
            .filter(
                TestRunItemDB.team_id == team_id,
                TestRunItemDB.test_case_number.in_(cleaned_numbers),
            )
            .all()
        )
        if not rows:
            return []

        scope_cache: Dict[int, List[int]] = {}
        missing_scope_config_ids: List[int] = []
        for row in rows:
            scope = cls.parse_scope_ids_json(row.scope_json)
            if scope:
                scope_cache[row.config_id] = scope
            else:
                missing_scope_config_ids.append(row.config_id)

        derived_scope_map = cls._derive_scope_ids_for_configs(
            db,
            team_id=team_id,
            config_ids=cls.normalize_scope_ids(missing_scope_config_ids),
        )

        impacted_rows: List[dict] = []
        for row in rows:
            scope = scope_cache.get(row.config_id)
            if scope is None:
                scope = derived_scope_map.get(row.config_id, [])
                scope_cache[row.config_id] = scope
            if target_set_id not in scope:
                impacted_rows.append(
                    {
                        "item_id": row.item_id,
                        "config_id": row.config_id,
                        "config_name": row.config_name,
                    }
                )
        return impacted_rows

    @classmethod
    def preview_set_deletion(
        cls,
        db: Session,
        team_id: int,
        set_id: int,
    ) -> dict:
        rows = cls._build_rows_for_removed_sets(
            db,
            team_id=team_id,
            removed_set_ids=[set_id],
        )
        summary = cls._summarize_impact_rows(rows)
        return {
            "impacted_item_count": summary["removed_item_count"],
            "impacted_test_runs": summary["impacted_test_runs"],
            "trigger": "delete_test_case_set",
            "source_test_case_set_id": set_id,
        }

    @classmethod
    def preview_case_move(
        cls,
        db: Session,
        team_id: int,
        case_numbers: List[str],
        target_set_id: int,
    ) -> dict:
        rows = cls._build_rows_for_case_move(
            db,
            team_id=team_id,
            case_numbers=case_numbers,
            target_set_id=target_set_id,
        )
        summary = cls._summarize_impact_rows(rows)
        return {
            "impacted_item_count": summary["removed_item_count"],
            "impacted_test_runs": summary["impacted_test_runs"],
            "trigger": "move_test_case_set",
            "target_test_case_set_id": target_set_id,
        }

    @classmethod
    def cleanup_scope_reduction(
        cls,
        db: Session,
        team_id: int,
        config_id: int,
        removed_set_ids: List[int],
    ) -> dict:
        rows = cls._build_rows_for_removed_sets(
            db,
            team_id=team_id,
            removed_set_ids=removed_set_ids,
            config_id=config_id,
        )
        summary = cls._summarize_impact_rows(rows)
        if summary["impacted_item_ids"]:
            db.query(TestRunItemDB).filter(
                TestRunItemDB.id.in_(summary["impacted_item_ids"])
            ).delete(synchronize_session=False)
        return {
            "removed_item_count": summary["removed_item_count"],
            "impacted_test_runs": summary["impacted_test_runs"],
            "trigger": "reduce_test_case_set_scope",
            "affected_test_case_set_ids": cls.normalize_scope_ids(removed_set_ids),
        }

    @classmethod
    def cleanup_set_deletion(
        cls,
        db: Session,
        team_id: int,
        set_id: int,
    ) -> dict:
        rows = cls._build_rows_for_removed_sets(
            db,
            team_id=team_id,
            removed_set_ids=[set_id],
        )
        summary = cls._summarize_impact_rows(rows)
        if summary["impacted_item_ids"]:
            db.query(TestRunItemDB).filter(
                TestRunItemDB.id.in_(summary["impacted_item_ids"])
            ).delete(synchronize_session=False)
        return {
            "removed_item_count": summary["removed_item_count"],
            "impacted_test_runs": summary["impacted_test_runs"],
            "trigger": "delete_test_case_set",
            "affected_test_case_set_ids": [set_id],
            "source_test_case_set_id": set_id,
        }

    @classmethod
    def cleanup_case_move(
        cls,
        db: Session,
        team_id: int,
        case_numbers: List[str],
        target_set_id: int,
    ) -> dict:
        rows = cls._build_rows_for_case_move(
            db,
            team_id=team_id,
            case_numbers=case_numbers,
            target_set_id=target_set_id,
        )
        summary = cls._summarize_impact_rows(rows)
        if summary["impacted_item_ids"]:
            db.query(TestRunItemDB).filter(
                TestRunItemDB.id.in_(summary["impacted_item_ids"])
            ).delete(synchronize_session=False)
        return {
            "removed_item_count": summary["removed_item_count"],
            "impacted_test_runs": summary["impacted_test_runs"],
            "trigger": "move_test_case_set",
            "target_test_case_set_id": target_set_id,
        }

    @classmethod
    def remove_set_from_all_scopes(
        cls,
        db: Session,
        team_id: int,
        set_id: int,
    ) -> Dict[int, List[int]]:
        updates: Dict[int, List[int]] = {}
        configs = db.query(TestRunConfigDB).filter(TestRunConfigDB.team_id == team_id).all()
        for config in configs:
            current_scope = cls.get_config_scope_ids(db, config, allow_fallback=True)
            if set_id not in current_scope:
                continue
            next_scope = [sid for sid in current_scope if sid != set_id]
            cls.set_config_scope_ids(config, next_scope)
            updates[config.id] = next_scope
        return updates
