"""A chart is built by code from a stored result; the model only names the result and the columns."""

from __future__ import annotations

from typing import Any

from .answer import ChartRequest
from .tools import StoredResult


class ChartRejectedError(ValueError):
    pass


def build_vega_lite(request: ChartRequest, result: StoredResult, max_points: int = 200) -> dict[str, Any]:
    for column in (request.x, request.y):
        if column not in result.columns:
            raise ChartRejectedError(f"Column {column} is not in {result.id} ({', '.join(result.columns)}).")
    xi, yi = result.columns.index(request.x), result.columns.index(request.y)
    values = [{request.x: row[xi], request.y: row[yi]} for row in result.rows[:max_points]]
    if not values:
        raise ChartRejectedError(f"{result.id} has no rows to chart.")
    if not all(isinstance(v[request.y], int | float) for v in values):
        raise ChartRejectedError(f"Column {request.y} is not numeric.")
    x_type = "temporal" if request.kind == "line" else "nominal"
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": f"{request.y} by {request.x} from {result.id}",
        "data": {"values": values},
        "mark": request.kind,
        "encoding": {
            "x": {"field": request.x, "type": x_type, "sort": "-y" if request.kind == "bar" else None},
            "y": {"field": request.y, "type": "quantitative"},
        },
        "width": "container",
        "height": 260,
    }
