"""DuckDB over the checked-in parquet files.

Every table the model may name is listed here; nothing else is reachable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb


@dataclass(frozen=True, slots=True)
class TableInfo:
    name: str
    scope_column: str | None
    description: str
    columns: dict[str, str]


TABLES: dict[str, TableInfo] = {
    "trips": TableInfo(
        "trips",
        "start_borough",
        "A 200,000-row reservoir sample of the 14.2 million completed BIXI trips of 2025. Use it for distributions, "
        "durations and station pairs; use daily_borough for exact counts.",
        {
            "start_station": "text",
            "start_borough": "text",
            "end_station": "text",
            "end_borough": "text",
            "started_at": "timestamp (UTC)",
            "ended_at": "timestamp (UTC)",
            "duration_s": "integer seconds",
        },
    ),
    "daily_borough": TableInfo(
        "daily_borough",
        "borough",
        "Exact daily trip counts per start borough for all of 2025, computed from every completed trip.",
        {
            "day": "date",
            "borough": "text",
            "trips": "integer",
            "avg_duration_s": "integer seconds",
            "median_duration_s": "integer seconds",
        },
    ),
    "stations": TableInfo(
        "stations",
        "borough",
        "One row per start station with its borough, coordinates and total 2025 departures.",
        {"station": "text", "borough": "text", "lat": "double", "lon": "double", "departures_2025": "integer"},
    ),
}


def find_data_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for parent in [here, *here.parents]:
        candidate = parent / "data" / "stations.parquet"
        if candidate.exists():
            return candidate.parent
    raise FileNotFoundError("data/stations.parquet not found above the package")


def connect(data_root: Path | None = None) -> duckdb.DuckDBPyConnection:
    root = data_root or find_data_root()
    con = duckdb.connect(database=":memory:")
    for name in TABLES:
        path = (root / f"{'trips_sample' if name == 'trips' else name}.parquet").as_posix()
        con.execute(f"create table {name} as select * from read_parquet('{path}')")
    con.execute("set enable_external_access = false")
    return con


def boroughs(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [row[0] for row in con.execute("select distinct borough from stations order by 1").fetchall()]


def schema_text() -> str:
    lines: list[str] = []
    for table in TABLES.values():
        lines.append(f"table {table.name}: {table.description}")
        for column, kind in table.columns.items():
            lines.append(f"  {column} {kind}")
    return "\n".join(lines)
