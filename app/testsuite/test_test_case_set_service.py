from sqlalchemy import select
from sqlalchemy.dialects import mysql

from app.models.database_models import TestCaseSection as CaseSectionModel
from app.services.test_case_set_service import _section_order_clauses


def test_section_order_clauses_compile_without_nulls_first_for_mysql():
    statement = select(CaseSectionModel.id).order_by(*_section_order_clauses())

    compiled_sql = str(
        statement.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    normalized_sql = compiled_sql.upper()
    assert "NULLS FIRST" not in normalized_sql
    assert "CASE WHEN" in normalized_sql
    assert "TEST_CASE_SECTIONS.PARENT_SECTION_ID" in normalized_sql
