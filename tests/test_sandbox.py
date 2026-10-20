import pytest

from mtl_analyst.sandbox import QueryBudget, QueryBudgetExceededError, SandboxRejectedError, SqlSandbox
from mtl_analyst.scope import Scope

PLATEAU = "Le Plateau-Mont-Royal"


def sandbox(con, scope=None, **budget):
    return SqlSandbox(con, scope or Scope(), QueryBudget(**budget))


@pytest.mark.parametrize(
    "sql",
    [
        "delete from trips",
        "insert into stations values ('x','y',0,0,0)",
        "create table t as select 1",
        "select * from trips; select * from stations",
        "select * from read_parquet('data/stations.parquet')",
        "select getenv('HOME')",
        "select * from information_schema.tables",
        "select * from memory.main.trips",
        "pragma database_list",
        "copy trips to '/tmp/x.csv'",
        "attach ':memory:' as other",
    ],
)
def test_anything_but_a_catalog_select_is_rejected(con, sql):
    with pytest.raises(SandboxRejectedError):
        sandbox(con).rewrite(sql)


def test_scope_is_injected_at_the_table_not_the_query(con):
    rewritten = sandbox(con, Scope(PLATEAU)).rewrite("select count(*) as n from trips")

    assert "start_borough = 'Le Plateau-Mont-Royal'" in rewritten
    assert rewritten.startswith("SELECT COUNT(*) AS n FROM (SELECT * FROM trips WHERE")


def test_scoped_query_cannot_see_other_boroughs_even_when_it_asks(con):
    result = sandbox(con, Scope(PLATEAU)).run(
        "select distinct start_borough from trips where start_borough <> 'Le Plateau-Mont-Royal'"
    )

    assert result.rows == []


def test_scope_applies_to_every_table_and_through_ctes(con):
    result = sandbox(con, Scope(PLATEAU)).run(
        "with d as (select borough, sum(trips) as t from daily_borough group by 1) "
        "select d.borough, s.borough from d join stations s on s.borough = d.borough"
    )

    assert {row[0] for row in result.rows} == {PLATEAU}
    assert {row[1] for row in result.rows} == {PLATEAU}


def test_city_scope_sees_everything(con):
    result = sandbox(con).run("select count(distinct borough) from daily_borough")

    assert result.rows[0][0] > 10


def test_row_limit_is_added_and_reported(con):
    result = sandbox(con, max_rows=5).run("select * from stations")

    assert len(result.rows) == 5
    assert result.truncated
    assert "LIMIT 6" in result.sql_executed


def test_query_count_budget(con):
    box = sandbox(con, max_queries=2)
    box.run("select 1")
    box.run("select 2")
    with pytest.raises(QueryBudgetExceededError):
        box.run("select 3")


def test_timeout_budget(con):
    box = sandbox(con, timeout_s=0.05)
    with pytest.raises(QueryBudgetExceededError):
        box.run("select count(*) from trips a, trips b, trips c")


def test_exact_counts_match_the_published_aggregate(con):
    result = sandbox(con).run("select sum(trips) from daily_borough")

    assert result.rows[0][0] == 14193509
