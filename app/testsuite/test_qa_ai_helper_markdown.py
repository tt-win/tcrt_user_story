from pydantic import ValidationError

from app.models.qa_ai_helper import QAAIHelperTicketReparseRequest
from app.services.qa_ai_helper_service import (
    _build_ticket_markdown,
    _jira_wiki_to_markdown,
    _markdown_to_jira_wiki,
)


def test_jira_wiki_conversion_emits_canonical_markdown_tables_and_inline_tokens() -> None:
    source = (
        "h1. Ticket details\n"
        " * *Bold* and {_}italic{_} {{code}} [Link|https://example.test]\n"
        "||Column 1||Column 2||\n"
        "|Value A|Value B|"
    )

    assert _jira_wiki_to_markdown(source) == (
        "# Ticket details\n"
        "- **Bold** and *italic* `code` [Link](https://example.test)\n"
        "| Column 1 | Column 2 |\n"
        "| --- | --- |\n"
        "| Value A | Value B |"
    )


def test_jira_wiki_tables_preserve_links_escaped_pipes_and_code_pipes() -> None:
    source = (
        "||Column 1||Column 2||\n"
        "|[Label|https://example.test]|{{a|b}}|\n"
        r"|escaped\|pipe|plain|"
    )

    assert _jira_wiki_to_markdown(source) == (
        "| Column 1 | Column 2 |\n"
        "| --- | --- |\n"
        "| [Label](https://example.test) | `a|b` |\n"
        r"| escaped\|pipe | plain |"
    )


def test_markdown_tables_require_header_separator_and_preserve_inline_pipes() -> None:
    markdown = (
        "| Name | Value |\n"
        "| --- | --- |\n"
        "| [Label](https://example.test) | `a|b` |\n"
        r"| escaped\|pipe | plain |"
    )

    assert _markdown_to_jira_wiki(markdown) == (
        "||Name||Value||\n"
        "|[Label|https://example.test]|{{a|b}}|\n"
        r"|escaped\|pipe|plain|"
    )
    literal = "| literal | pipe |"
    assert _markdown_to_jira_wiki(literal) == literal


def test_jira_wiki_conversion_preserves_unknown_tokens() -> None:
    source = "h1. Details\n{custom-token:keep}unrecognised{custom-token}"

    converted = _jira_wiki_to_markdown(source)

    assert "{custom-token:keep}unrecognised{custom-token}" in converted


def test_markdown_to_jira_wiki_round_trip_converts_tables_for_reparse() -> None:
    markdown = (
        "## Acceptance Criteria\n"
        "| Name | Value |\n"
        "| --- | --- |\n"
        "| First | **enabled** |\n"
        "{custom-token:keep}unrecognised{custom-token}"
    )

    converted = _markdown_to_jira_wiki(markdown)

    assert converted == (
        "h2. Acceptance Criteria\n"
        "||Name||Value||\n"
        "|First|*enabled*|\n"
        "{custom-token:keep}unrecognised{custom-token}"
    )


def test_build_ticket_markdown_keeps_canonical_source_deterministic() -> None:
    description = "h1. Details\n||Name||Value||\n|First|Second|"

    assert _build_ticket_markdown(
        ticket_key="ABC-1",
        summary="Summary",
        description=description,
    ) == (
        "# ABC-1 Summary\n\n"
        "# Details\n"
        "| Name | Value |\n"
        "| --- | --- |\n"
        "| First | Second |"
    )


def test_reparse_request_rejects_blank_but_preserves_meaningful_whitespace() -> None:
    for blank in ("", "   ", "\n\n"):
        try:
            QAAIHelperTicketReparseRequest(raw_ticket_markdown=blank)
        except ValidationError:
            pass
        else:
            raise AssertionError("blank Markdown must be rejected")

    raw_markdown = "# Ticket\n\nbody\n"
    request = QAAIHelperTicketReparseRequest(raw_ticket_markdown=raw_markdown)
    assert request.raw_ticket_markdown == raw_markdown
