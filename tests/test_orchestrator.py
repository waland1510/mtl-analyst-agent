import json

import pytest

from mtl_analyst.fakes import ScriptedChatClient
from mtl_analyst.orchestrator import Orchestrator, RunStore
from mtl_analyst.runtime import RunBudget
from mtl_analyst.scope import Scope
from mtl_analyst.tools import Exporter

PLATEAU = "Le Plateau-Mont-Royal"


def make(tmp_path, client=None, **kw):
    return Orchestrator(client or ScriptedChatClient(), RunStore(tmp_path / "runs"), **kw)


async def test_a_question_runs_sql_and_narrates_verified_numbers(tmp_path):
    run = await make(tmp_path).start(Scope(), "Which borough was the busiest?")

    assert run.status == "Completed"
    assert [e.name for e in run.events if e.kind == "tool"] == ["run_sql"]
    assert run.results[0].columns == ["borough", "trips"]
    assert run.kept and not run.dropped
    assert "4,643,362" in run.kept[0] or "4643362" in run.kept[0]
    assert run.chart and run.chart["mark"] == "bar"
    assert run.events[-1].kind == "critic"


async def test_a_borough_scope_only_sees_itself(tmp_path):
    run = await make(tmp_path).start(Scope(PLATEAU), "Which borough was the busiest?")

    assert run.status == "Completed"
    assert {row[0] for row in run.results[0].rows} == {PLATEAU}
    assert "start_borough = 'Le Plateau-Mont-Royal'" not in run.results[0].sql_requested
    assert "borough = 'Le Plateau-Mont-Royal'" in run.results[0].sql_executed


async def test_a_wrong_number_is_dropped_not_shown(tmp_path):
    def lie(question, results):
        return json.dumps(
            {
                "text": "The busiest borough had 9,999,999 trips [R1]. Ville-Marie came second [R1].",
                "result_ids": ["R1"],
                "chart": None,
            }
        )

    run = await make(tmp_path, ScriptedChatClient(final_json=lie)).start(Scope(), "Which borough was the busiest?")

    assert run.kept == ["Ville-Marie came second [R1]."]
    assert "9999999" in run.dropped[0]["reason"]


async def test_sandbox_rejection_fails_the_run_closed(tmp_path):
    run = await make(tmp_path, ScriptedChatClient(sql_override="delete from trips")).start(Scope(), "total trips")

    assert run.status == "Failed"
    assert "Only SELECT" in run.error or "not allowed" in run.error
    assert run.results == []


async def test_tool_budget_fails_closed(tmp_path):
    class Looping(ScriptedChatClient):
        async def _inner_get_response(self, *, messages, stream, options, **kwargs):
            from agent_framework import ChatResponse, Content, Message, UsageDetails

            reply = Message(
                "assistant", [Content.from_function_call(f"c{len(messages)}", "run_sql", arguments={"sql": "select 1"})]
            )
            return ChatResponse(
                messages=[reply],
                finish_reason="tool_calls",
                usage_details=UsageDetails(input_token_count=5, output_token_count=5),
            )

    run = await make(tmp_path, Looping(), budget=RunBudget(max_tool_calls=3, max_model_calls=50)).start(Scope(), "loop")

    assert run.status == "Failed"
    assert "tool calls" in run.error
    assert sum(1 for e in run.events if e.kind == "tool") <= 3


async def test_export_pauses_for_approval_and_a_fresh_process_resumes_it(tmp_path):
    exporter = Exporter()
    paused = await make(tmp_path, ScriptedChatClient(export=True), exporter=exporter).start(
        Scope(), "total trips, then export it", allow_export=True
    )

    assert paused.status == "AwaitingApproval"
    approval = paused.approvals[0]
    assert approval.tool == "export_csv" and approval.approved is None
    assert exporter.exported == []
    assert paused.paused_session is not None

    resumed = await make(tmp_path, ScriptedChatClient(export=True), exporter=exporter).decide(
        paused.id, approval.id, True, "buyer"
    )

    assert resumed.status == "Completed"
    assert exporter.exported == [("R1", "answer.csv", 1)]
    assert "exported" in " ".join(resumed.kept) or "exported" in resumed.answer.text
    assert any(e.kind == "tool" and e.name == "export_csv" for e in resumed.events)


async def test_a_rejected_export_sends_nothing(tmp_path):
    exporter = Exporter()
    paused = await make(tmp_path, ScriptedChatClient(export=True), exporter=exporter).start(
        Scope(), "total trips, then export it", allow_export=True
    )

    resumed = await make(tmp_path, ScriptedChatClient(export=True), exporter=exporter).decide(
        paused.id, paused.approvals[0].id, False, "buyer"
    )

    assert resumed.status == "Rejected"
    assert exporter.exported == []
    with pytest.raises(ValueError):
        await make(tmp_path, exporter=exporter).decide(paused.id, paused.approvals[0].id, True, "buyer")


async def test_without_export_permission_the_tool_does_not_exist(tmp_path):
    run = await make(tmp_path, ScriptedChatClient(export=True)).start(Scope(), "total trips, then export it")

    assert run.status == "Completed"
    assert not any(e.name == "export_csv" for e in run.events)
