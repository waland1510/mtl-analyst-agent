"""A deterministic model so every boundary can be tested offline.

It picks a golden query by keywords and narrates the first row.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from agent_framework import (
    BaseChatClient,
    ChatMiddlewareLayer,
    ChatResponse,
    Content,
    FunctionInvocationLayer,
    Message,
    UsageDetails,
)

GOLDEN: list[tuple[tuple[str, ...], str, str]] = [
    (
        ("busiest", "most trips", "borough", "arrondissement"),
        "select borough, sum(trips) as trips from daily_borough group by 1 order by 2 desc limit 5",
        "The busiest borough was {borough} with {trips} trips [R1].",
    ),
    (
        ("month", "mois", "season"),
        "select strftime(day, '%Y-%m') as month, sum(trips) as trips from daily_borough group by 1 order by 1",
        "The first month listed is {month} with {trips} trips [R1].",
    ),
    (
        ("median", "duration", "durée", "how long"),
        "select round(quantile_cont(duration_s, 0.5)) as median_s, round(avg(duration_s)) as mean_s from trips",
        "The median trip lasts {median_s} seconds and the mean is {mean_s} seconds [R1].",
    ),
    (
        ("station", "stations"),
        "select station, departures_2025 from stations order by 2 desc limit 5",
        "The busiest station is {station} with {departures_2025} departures [R1].",
    ),
    (
        ("total", "how many trips", "trips in 2025", "count"),
        "select sum(trips) as trips from daily_borough",
        "There were {trips} trips in 2025 [R1].",
    ),
]

Script = Callable[[str, list[dict[str, Any]]], str | None]


class ScriptedChatClient(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
    def __init__(
        self, *, final_json: Script | None = None, sql_override: str | None = None, export: bool = False, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.final_json = final_json
        self.sql_override = sql_override
        self.export = export

    async def _inner_get_response(
        self, *, messages: Sequence[Message], stream: bool, options: dict[str, Any], **kwargs: Any
    ) -> ChatResponse:
        question = next((m.text for m in reversed(messages) if m.role == "user" and m.text), "")
        tool_results = [c for m in messages for c in m.contents if c.type == "function_result"]
        tools = {getattr(t, "name", ""): t for t in options.get("tools") or []}
        results = [self._parse(c) for c in tool_results]
        sql_done = any(r.get("result_id") for r in results)

        if tools and not sql_done:
            keywords_sql, _ = self._golden(question)
            sql = self.sql_override or keywords_sql
            reply = Message("assistant", [Content.from_function_call("call-sql", "run_sql", arguments={"sql": sql})])
            return self._response(reply, messages, "tool_calls")

        export_attempted = any(c.call_id == "call-export" for c in tool_results)
        wants_export = self.export or "export" in question.lower()
        if wants_export and "export_csv" in tools and not export_attempted:
            first = next(r["result_id"] for r in results if r.get("result_id"))
            reply = Message(
                "assistant",
                [
                    Content.from_function_call(
                        "call-export", "export_csv", arguments={"result_id": first, "filename": "answer.csv"}
                    )
                ],
            )
            return self._response(reply, messages, "tool_calls")

        text = self.final_json(question, results) if self.final_json else None
        if text is None:
            text = self._narrate(question, results, tool_results)
        return self._response(Message("assistant", [Content.from_text(text)]), messages, "stop")

    @staticmethod
    def _parse(content: Content) -> dict[str, Any]:
        raw = content.result
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except (TypeError, ValueError):
            return {"value": raw}

    @staticmethod
    def _golden(question: str) -> tuple[str, str]:
        q = question.lower()
        for keywords, sql, template in GOLDEN:
            if any(k in q for k in keywords):
                return sql, template
        return GOLDEN[-1][1], GOLDEN[-1][2]

    def _narrate(self, question: str, results: list[dict[str, Any]], tool_results: list[Content]) -> str:
        first = next((r for r in results if r.get("result_id")), None)
        exported = next((str(r.get("value")) for r in results if "export-" in str(r.get("value"))), None)
        refused = any(c.call_id == "call-export" for c in tool_results) and exported is None
        if first is None or not first.get("rows"):
            return json.dumps({"text": "The data does not answer this question.", "result_ids": [], "chart": None})
        _, template = self._golden(question)
        row = dict(zip(first["columns"], first["rows"][0], strict=False))
        try:
            text = template.format(**row)
        except KeyError:
            text = f"The first row is {row} [{first['result_id']}]."
        if exported:
            text += f" The result was exported ({exported})."
        elif refused:
            text += " The export was not approved, so nothing was written."
        chart = None
        if len(first["columns"]) >= 2 and len(first["rows"]) > 1 and isinstance(first["rows"][0][1], int | float):
            chart = {"result_id": first["result_id"], "kind": "bar", "x": first["columns"][0], "y": first["columns"][1]}
        return json.dumps({"text": text, "result_ids": [first["result_id"]], "chart": chart})

    @staticmethod
    def _response(reply: Message, messages: Sequence[Message], finish: str) -> ChatResponse:
        inp = sum(len(m.text or "") for m in messages) // 4
        out = len(reply.text or "") // 4 + 8
        return ChatResponse(
            messages=[reply],
            finish_reason=finish,
            usage_details=UsageDetails(input_token_count=inp, output_token_count=out),
            model="scripted-fake",
        )
