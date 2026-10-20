# Data

Source: BIXI Montréal open data, 2025 yearly export
(https://bixi.com/en/open-data/, file `DonneesOuvertes2025_…zip`, 2.8 GB
unzipped, 14,249,363 rows). Three derived files are checked in, built by
`scripts/build_data.py`:

| File | Rows | What |
|---|---:|---|
| `daily_borough.parquet` | one per day and start borough | Exact counts and durations over every completed trip (14,193,509) |
| `stations.parquet` | one per start station | Borough, coordinates, 2025 departures |
| `trips_sample.parquet` | 200,000 | Reservoir sample of completed trips, seed 42 |

A trip is "completed" when it has an end station, ends after it starts and
lasts under 24 hours. Timestamps are UTC. Exact questions go to
`daily_borough`; distribution questions go to the sample, and the catalog
says so to the model.
