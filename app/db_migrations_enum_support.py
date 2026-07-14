"""共用邏輯：Enum 欄位在 name-based 具名型別／value-based 可攜字串之間轉換。

供 Alembic 資料遷移呼叫（`app/models/database_models.py` 與 `app/audit/database.py`
的 enum 欄位改用 `values_callable` + `native_enum=False` 後，既有資料與型別都需要對應轉換）。
三引擎處理方式：

- SQLite：欄位本質為 VARCHAR，無原生型別限制，僅需資料轉換，`target_native` 對此分支無影響。
- MySQL：欄位為 inline `ENUM(...)`，需先放寬為 VARCHAR（讓新舊值並存）→ 轉換資料 →
  `target_native=True` 時收斂回 `ENUM(...)`（downgrade 用，還原 rollback 前的具名型別），
  `target_native=False` 時保留 VARCHAR（upgrade 用——這是「新增 enum 值不需要
  `MODIFY COLUMN`」得以成立的原因）。
- PostgreSQL：欄位使用具名 TYPE，且可能被多個 table/column 共用同一個 TYPE
  （SQLAlchemy 對同一個 Python enum class 預設共用同名 PG type）。需先讓所有使用該
  type 的欄位改用 TEXT → drop 舊 type → 轉換所有相關欄位的資料 →
  `target_native=True` 時 create 新 TYPE 並讓所有欄位改回該 TYPE（downgrade 用），
  `target_native=False` 時保留 TEXT（upgrade 用——不再需要 `ALTER TYPE` 即可新增 enum 值）。
"""

from __future__ import annotations

from dataclasses import dataclass

from alembic import op
import sqlalchemy as sa


@dataclass(frozen=True)
class EnumColumnRef:
    table_name: str
    column_name: str
    nullable: bool


def _existing_column_length(bind, table_name: str, column_name: str) -> int:
    inspector = sa.inspect(bind)
    for column in inspector.get_columns(table_name):
        if column["name"] == column_name:
            length = getattr(column["type"], "length", None)
            return int(length) if length else 64
    return 64


def _update_enum_values(table_name: str, column_name: str, mapping: dict[str, str]) -> None:
    tbl = sa.table(table_name, sa.column(column_name))
    for old_value, new_value in mapping.items():
        if old_value == new_value:
            continue
        op.execute(tbl.update().where(tbl.c[column_name] == old_value).values(**{column_name: new_value}))


def _migrate_column_mysql(
    bind,
    ref: EnumColumnRef,
    mapping: dict[str, str],
    new_labels: list[str],
    target_native: bool,
) -> None:
    existing_length = _existing_column_length(bind, ref.table_name, ref.column_name)
    widen_length = max(existing_length, max((len(v) for v in new_labels), default=8), 64)

    op.alter_column(
        ref.table_name,
        ref.column_name,
        existing_type=sa.String(length=existing_length),
        type_=sa.String(length=widen_length),
        existing_nullable=ref.nullable,
    )
    _update_enum_values(ref.table_name, ref.column_name, mapping)
    if target_native:
        op.alter_column(
            ref.table_name,
            ref.column_name,
            existing_type=sa.String(length=widen_length),
            type_=sa.dialects.mysql.ENUM(*new_labels),
            existing_nullable=ref.nullable,
        )
    # target_native=False：保留 VARCHAR(widen_length) 即是最終可攜狀態，不需再收斂回 ENUM。


def migrate_enum_storage(
    bind,
    *,
    mapping: dict[str, str],
    columns: list[EnumColumnRef],
    pg_type_name: str,
    target_native: bool = False,
) -> None:
    """把 `columns` 內每個欄位的 enum 儲存表示法依 `mapping`（舊值→新值）轉換。

    `mapping` 的 key 是目前實際儲存的字串、value 是轉換後要儲存的字串；
    呼叫端負責決定方向（upgrade 傳 name→value，downgrade 傳 value→name）。
    `pg_type_name` 是 PostgreSQL 具名 enum type 的名稱（SQLAlchemy 預設為
    Python 類名小寫），僅 PostgreSQL 分支使用。

    `target_native` 決定 MySQL/PostgreSQL 轉換完成後的最終型別：
    - `False`（upgrade 方向）：留在可攜的 VARCHAR/TEXT，不建立原生 ENUM/named TYPE。
    - `True`（downgrade 方向）：轉換回原生 ENUM（MySQL）/ named TYPE（PostgreSQL），
      還原成這支 migration 執行前的具名型別狀態。
    SQLite 沒有原生 enum 型別可言，此參數對 SQLite 分支無影響。
    """
    dialect = bind.dialect.name
    new_labels = sorted(set(mapping.values()))

    if dialect == "mysql":
        for ref in columns:
            _migrate_column_mysql(bind, ref, mapping, new_labels, target_native)
        return

    if dialect == "postgresql":
        # 1) 全部欄位暫時改為 TEXT，脫離具名 type 的引用。
        for ref in columns:
            op.execute(
                sa.text(
                    f'ALTER TABLE "{ref.table_name}" ALTER COLUMN "{ref.column_name}" TYPE TEXT '
                    f'USING "{ref.column_name}"::text'
                )
            )
        # 2) 舊 type 已無欄位引用，可安全 drop。
        op.execute(sa.text(f'DROP TYPE IF EXISTS "{pg_type_name}"'))
        # 3) 轉換資料（此時欄位是 TEXT，任意字串皆可寫入）。
        for ref in columns:
            _update_enum_values(ref.table_name, ref.column_name, mapping)
        if target_native:
            # 4) 建立新 type（value-based 標籤）並讓欄位改回該 type。
            quoted_labels = ", ".join(f"'{label}'" for label in new_labels)
            op.execute(sa.text(f'CREATE TYPE "{pg_type_name}" AS ENUM ({quoted_labels})'))
            for ref in columns:
                op.execute(
                    sa.text(
                        f'ALTER TABLE "{ref.table_name}" ALTER COLUMN "{ref.column_name}" TYPE "{pg_type_name}" '
                        f'USING "{ref.column_name}"::"{pg_type_name}"'
                    )
                )
        # target_native=False：保留 TEXT 即是最終可攜狀態，不建立新 named type。
        return

    # SQLite（及其他無原生 enum 限制的引擎）：純資料轉換。
    for ref in columns:
        _update_enum_values(ref.table_name, ref.column_name, mapping)
