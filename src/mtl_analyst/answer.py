"""The answer contract and the critic that checks it.

The critic is code: a number the model states must exist in a result it cites.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from .tools import StoredResult

ANSWER_INSTRUCTIONS = """
You are an analyst over Montréal BIXI bike-share data for 2025. Call describe_tables once, then run_sql as needed.
Every number you state must come from a result row: compute totals, shares, averages and percentages in SQL,
never in your head. Write short sentences; after each sentence that states numbers, put the result id in brackets,
for example [R1].
If the user asks to export or download a result and export_csv is among your tools, call it with that result id
before answering; a human will approve it. If it is not among your tools, say exports are not enabled.
Respond with JSON: {"text": "...", "result_ids": ["R1"],
"chart": {"result_id": "R1", "kind": "bar", "x": "borough", "y": "trips"} or null}.
""".strip()


class ChartRequest(BaseModel):
    result_id: str
    kind: str = Field(pattern="^(bar|line)$")
    x: str
    y: str


class Answer(BaseModel):
    text: str
    result_ids: list[str] = Field(default_factory=list)
    chart: ChartRequest | None = None


@dataclass(frozen=True, slots=True)
class Sentence:
    text: str
    result_ids: tuple[str, ...]
    numbers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Verdict:
    kept: list[Sentence]
    dropped: list[tuple[Sentence, str]]

    @property
    def passed(self) -> bool:
        return not self.dropped


_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:[ ,\xa0]\d{3})+|\d+)(?:[.,]\d+)?%?")
_REF = re.compile(r"\[(R\d+)\]")
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý\d])")


def _normalize(token: str) -> str:
    token = token.replace("\xa0", "").replace(" ", "").replace("%", "")
    if token.count(",") == 1 and "." not in token and len(token.split(",")[1]) != 3:
        token = token.replace(",", ".")
    else:
        token = token.replace(",", "")
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token


def _cell_forms(value: object) -> set[str]:
    forms: set[str] = set()
    if isinstance(value, bool) or value is None:
        return forms
    if isinstance(value, int | float):
        forms.add(_normalize(str(value)))
        for digits in (0, 1, 2):
            forms.add(_normalize(f"{value:.{digits}f}"))
            forms.add(_normalize(f"{round(value, digits):,}"))
        if isinstance(value, float) and value < 1:
            for digits in (0, 1, 2):
                forms.add(_normalize(f"{value * 100:.{digits}f}"))
    elif isinstance(value, str):
        for match in _NUMBER.finditer(value):
            forms.add(_normalize(match.group(0)))
    return forms


def split_sentences(text: str) -> list[Sentence]:
    sentences: list[Sentence] = []
    for raw in _SPLIT.split(text.strip()):
        raw = raw.strip()
        if not raw:
            continue
        refs = tuple(dict.fromkeys(_REF.findall(raw)))
        body = _REF.sub("", raw)
        numbers = tuple(_normalize(m.group(0)) for m in _NUMBER.finditer(body))
        sentences.append(Sentence(raw, refs, numbers))
    return sentences


def verify(answer: Answer, results: list[StoredResult], allowed_free_numbers: set[str] | None = None) -> Verdict:
    """A sentence with numbers must cite a result containing every one of them.

    Free numbers are allowed: the data year, any number in the question, and any number the model itself wrote
    into a cited query (a LIMIT or a filter is a choice, not a claim about the data).
    """
    allowed = {"2025"} | {_normalize(n) for n in (allowed_free_numbers or set())}
    by_id = {r.id: r for r in results}
    kept: list[Sentence] = []
    dropped: list[tuple[Sentence, str]] = []
    for sentence in split_sentences(answer.text):
        unexplained = [n for n in sentence.numbers if n not in allowed]
        if not unexplained:
            kept.append(sentence)
            continue
        cited = [by_id[r] for r in sentence.result_ids if r in by_id]
        if not cited:
            dropped.append((sentence, "states numbers but cites no result"))
            continue
        forms: set[str] = set()
        for result in cited:
            forms |= {_normalize(m.group(0)) for m in _NUMBER.finditer(result.sql_requested)}
            for row in result.rows:
                for cell in row:
                    forms |= _cell_forms(cell)
        missing = [n for n in unexplained if n not in forms]
        if missing:
            dropped.append((sentence, f"{', '.join(missing)} not in cited result(s) {', '.join(r.id for r in cited)}"))
        else:
            kept.append(sentence)
    return Verdict(kept, dropped)
