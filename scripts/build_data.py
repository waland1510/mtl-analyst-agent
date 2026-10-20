"""Rebuilds data/*.parquet from the BIXI yearly export.

Run with the path to the unzipped CSV; the full file is 2.8 GB and is not checked in.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb


def main(csv: str, out: Path) -> None:
    con = duckdb.connect()
    con.execute(
        f"""
        create view raw as select
          STARTSTATIONNAME as start_station, STARTSTATIONARRONDISSEMENT as start_borough,
          STARTSTATIONLATITUDE as start_lat, STARTSTATIONLONGITUDE as start_lon,
          ENDSTATIONNAME as end_station, ENDSTATIONARRONDISSEMENT as end_borough,
          to_timestamp(STARTTIMEMS/1000) at time zone 'UTC' as started_at,
          to_timestamp(ENDTIMEMS/1000) at time zone 'UTC' as ended_at
        from read_csv('{csv}', header=true, sample_size=-1)
        """
    )
    con.execute(
        """
        create table trips as select *, date_diff('second', started_at, ended_at) as duration_s from raw
        where ended_at is not null and end_station is not null and ended_at > started_at
          and date_diff('second', started_at, ended_at) < 24*3600
        """
    )
    out.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"""copy (select start_station, start_borough, end_station, end_borough, started_at, ended_at, duration_s
            from trips using sample reservoir(200000 rows) repeatable (42) order by started_at)
            to '{out / "trips_sample.parquet"}' (format parquet, compression zstd)"""
    )
    con.execute(
        f"""copy (select cast(started_at as date) as day, start_borough as borough, count(*) as trips,
            round(avg(duration_s)) as avg_duration_s, round(quantile_cont(duration_s, 0.5)) as median_duration_s
            from trips group by 1,2 order by 1,2)
            to '{out / "daily_borough.parquet"}' (format parquet, compression zstd)"""
    )
    con.execute(
        f"""copy (select start_station as station, any_value(start_borough) as borough,
            round(any_value(start_lat),5) as lat, round(any_value(start_lon),5) as lon, count(*) as departures_2025
            from trips group by 1 order by 1) to '{out / "stations.parquet"}' (format parquet, compression zstd)"""
    )
    print(con.execute("select count(*) from trips").fetchone())


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2] if len(sys.argv) > 2 else "data"))
