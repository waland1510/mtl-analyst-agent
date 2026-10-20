import pytest

from mtl_analyst.answer import ChartRequest
from mtl_analyst.charts import ChartRejectedError, build_vega_lite
from mtl_analyst.sandbox import SqlSandbox
from mtl_analyst.scope import Scope
from mtl_analyst.tools import AnalystToolbox, Exporter

PLATEAU = "Le Plateau-Mont-Royal"


def toolbox(con, scope=None):
    return AnalystToolbox(SqlSandbox(con.cursor(), scope or Scope()), Exporter())


def test_no_tool_exposes_scope_as_an_argument(con):
    from agent_framework import FunctionTool

    for tool in toolbox(con).tools(allow_export=True):
        ft = tool if isinstance(tool, FunctionTool) else FunctionTool(name=tool.__name__, func=tool)
        names = set((ft.parameters() or {}).get("properties", {}))
        assert not {n for n in names if "borough" in n or "scope" in n}, ft.name


def test_run_sql_stores_results_with_ids_in_order(con):
    box = toolbox(con)
    first = box.run_sql("select 1 as a")
    second = box.run_sql("select 2 as b")

    assert (first["result_id"], second["result_id"]) == ("R1", "R2")
    assert box.find("R2").rows == [[2]]


def test_scoped_toolbox_never_returns_another_borough(con):
    out = toolbox(con, Scope(PLATEAU)).run_sql(
        "select distinct borough from stations where borough <> 'Le Plateau-Mont-Royal'"
    )

    assert out["row_count"] == 0


def test_export_requires_a_known_result_and_a_bare_csv_name(con):
    box = toolbox(con)
    box.run_sql("select 1 as a")
    with pytest.raises(ValueError):
        box.export_csv("R9", "x.csv")
    with pytest.raises(ValueError):
        box.export_csv("R1", "../x.csv")
    assert box.export_csv("R1", "x.csv").startswith("export-1:")


def test_chart_is_built_from_the_result_and_rejects_unknown_columns(con):
    box = toolbox(con)
    box.run_sql("select borough, sum(trips) as trips from daily_borough group by 1 order by 2 desc limit 3")
    spec = build_vega_lite(ChartRequest(result_id="R1", kind="bar", x="borough", y="trips"), box.find("R1"))

    assert len(spec["data"]["values"]) == 3
    assert spec["encoding"]["y"]["field"] == "trips"
    with pytest.raises(ChartRejectedError):
        build_vega_lite(ChartRequest(result_id="R1", kind="bar", x="borough", y="revenue"), box.find("R1"))
