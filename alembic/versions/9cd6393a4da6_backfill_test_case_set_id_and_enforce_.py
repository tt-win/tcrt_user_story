"""backfill_test_case_set_id_and_enforce_not_null

`test_cases.test_case_set_id` 一直都在 model 與初始 migration 中宣告為 `nullable=False`，
但透過 `--adopt-legacy-main-db` 納入版控的既有資料庫只會被標記版本號，不會真的重跑
`CREATE TABLE`，因此實際物理欄位可能仍是 nullable 且存在 NULL 資料（這也是
`scripts/db_cross_migrate.py` 過去需要 `_repair_test_cases_payload` 在搬遷當下即時回填的
原因）。本遷移把同一套回填規則搬到 schema 遷移本身，讓「回填＋強制 NOT NULL」成為資料庫
本身的保證，之後 `db_cross_migrate.py` 不再需要對此欄位的正確性負責。

回填規則（與 `_repair_test_cases_payload` 相同）：
1. 若有 `test_case_section_id`，用該 section 所屬的 `test_case_set_id`。
2. 否則用該列 `team_id` 對應的 default test case set（`test_case_sets.is_default`）。
3. 兩者皆無法決定時，直接中止遷移（`RuntimeError`），需要人工先行修正資料，不做靜默猜測。
   Change A 的開機備份／失敗回退機制會在此情況下接手，不會讓資料庫卡在半遷移狀態。

對已經滿足 NOT NULL（例如全新建立的資料庫）的情況，本遷移的回填迴圈找不到任何列，
`alter_column(nullable=False)` 也是安全的 no-op。

Revision ID: 9cd6393a4da6
Revises: 21a93e84da75
Create Date: 2026-07-14 09:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9cd6393a4da6"
down_revision: Union[str, Sequence[str], None] = "21a93e84da75"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    test_case_sections = sa.Table("test_case_sections", metadata, autoload_with=bind)
    test_case_sets = sa.Table("test_case_sets", metadata, autoload_with=bind)
    test_cases = sa.Table("test_cases", metadata, autoload_with=bind)

    section_to_set: dict[int, int] = {
        row.id: row.test_case_set_id
        for row in bind.execute(
            sa.select(test_case_sections.c.id, test_case_sections.c.test_case_set_id)
        )
    }
    default_set_by_team: dict[int, int] = {
        row.team_id: row.id
        for row in bind.execute(
            sa.select(test_case_sets.c.team_id, test_case_sets.c.id).where(
                test_case_sets.c.is_default.is_(True)
            )
        )
    }

    missing_rows = bind.execute(
        sa.select(
            test_cases.c.id,
            test_cases.c.team_id,
            test_cases.c.test_case_section_id,
        ).where(test_cases.c.test_case_set_id.is_(None))
    ).fetchall()

    for row in missing_rows:
        derived_set_id = None
        if row.test_case_section_id is not None:
            derived_set_id = section_to_set.get(row.test_case_section_id)
            if derived_set_id is None:
                raise RuntimeError(
                    f"test_cases.id={row.id} 的 test_case_section_id={row.test_case_section_id} "
                    "找不到對應的 test_case_set，無法自動回填 test_case_set_id，請先手動修正資料。"
                )
        else:
            derived_set_id = default_set_by_team.get(row.team_id)
            if derived_set_id is None:
                raise RuntimeError(
                    f"test_cases.id={row.id} 的 team_id={row.team_id} 沒有 default test case set，"
                    "無法自動回填 test_case_set_id，請先手動修正資料。"
                )

        op.execute(
            test_cases.update()
            .where(test_cases.c.id == row.id)
            .values(test_case_set_id=derived_set_id)
        )

    with op.batch_alter_table("test_cases") as batch_op:
        batch_op.alter_column(
            "test_case_set_id",
            existing_type=sa.Integer(),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("test_cases") as batch_op:
        batch_op.alter_column(
            "test_case_set_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
