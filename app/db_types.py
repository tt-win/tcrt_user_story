from __future__ import annotations

from sqlalchemy.dialects import mysql
from sqlalchemy.sql import sqltypes
from sqlalchemy.types import TypeDecorator


class MediumText(TypeDecorator):
    """跨資料庫文字型別；MySQL 預設使用 MEDIUMTEXT。"""

    impl = sqltypes.Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "mysql":
            return dialect.type_descriptor(mysql.MEDIUMTEXT())
        return dialect.type_descriptor(sqltypes.Text())


def medium_text_type() -> MediumText:
    return MediumText()
