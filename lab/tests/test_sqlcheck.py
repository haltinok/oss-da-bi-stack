"""What the lab accepts before it sends a statement to Cube."""
import pytest

import sqlcheck
from sqlcheck import SqlRefused, check


def test_a_select_or_a_with_is_accepted_and_a_trailing_semicolon_is_dropped():
    assert check("select 1") == "select 1"
    assert check("  SELECT category, MEASURE(revenue) FROM internet_sales GROUP BY 1;  ") == "SELECT category, MEASURE(revenue) FROM internet_sales GROUP BY 1"
    assert check("with t as (select 1) select * from t").startswith("with t")
    assert check("-- revenue by category\nselect 1").endswith("select 1")
    assert check("/* note */ select 1") == "/* note */ select 1"


@pytest.mark.parametrize("sql", ["", "   ", "delete from internet_sales", "insert into x values (1)", "drop table x", "update x set a = 1", "create table x(a int)", "explain select 1", "show tables", "set role admin", "call f()", "-- only a comment"])
def test_anything_that_is_not_a_select_is_refused(sql):
    with pytest.raises(SqlRefused):
        check(sql)


@pytest.mark.parametrize("sql", ["select 1; select 2", "select 1; drop table x", "select 1;;", "select 1; -- done\nselect 2"])
def test_a_second_statement_is_refused(sql):
    with pytest.raises(SqlRefused) as e:
        check(sql)
    assert "one statement" in str(e.value)


def test_a_semicolon_inside_a_string_a_quoted_name_or_a_comment_is_not_a_second_statement():
    assert check("select 'a;b' as x") == "select 'a;b' as x"
    assert check("select 'it''s; fine'") == "select 'it''s; fine'"
    assert check('select "odd;name" from t') == 'select "odd;name" from t'
    assert check("select 1 -- a; b\n") == "select 1 -- a; b"
    assert check("select /* ; */ 1") == "select /* ; */ 1"
    assert sqlcheck.semicolons_outside_quotes("select 'x;' ; select 2") == [12]


def test_too_long_or_odd_input_is_refused():
    with pytest.raises(SqlRefused):
        check("select " + "1," * sqlcheck.MAX_SQL + "1")
    with pytest.raises(SqlRefused):
        check("select 1\x00")
    with pytest.raises(SqlRefused):
        check(None)
