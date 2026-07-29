"""USM text parser must not invent node coordinates — canvas layout decides display."""

from app.services.usm_text_parser import USMParser, convert_usm_nodes_to_db_format


SAMPLE = """\
[@root] root: Root Feature
  [@login] feature: Login
    [@login_story] story: As a user I want to log in
      as_a: user
      i_want: log in
      so_that: access the system
  [@dash] feature: Dashboard
    [@dash_story] story: View dashboard
"""


def test_parser_positions_are_zero():
    parser = USMParser()
    nodes = parser.parse(SAMPLE)
    assert nodes, "expected parsed nodes"
    for node in nodes:
        assert node.position_x == 0.0
        assert node.position_y == 0.0


def test_convert_usm_nodes_to_db_format_positions_are_zero():
    parser = USMParser()
    nodes = parser.parse(SAMPLE)
    db_nodes = convert_usm_nodes_to_db_format(nodes, map_id=1)
    assert db_nodes
    for node in db_nodes:
        assert node["position_x"] == 0.0
        assert node["position_y"] == 0.0
