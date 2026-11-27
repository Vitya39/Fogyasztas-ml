"""
SQLite adatbázis-kezelő az okoskonnektor teljesítmény és fogyasztás
idősoraihoz. Ez a modul az 5 cél-SQLite tábla sémaleírását és a
`EnergyDatabase` osztályt tartalmazza, amely az adatbázis
inicializálásáért, rekordok beszúrásáért és lekérdezéséért felelős.

energy.db legenerálásra teszt parancs:
py -c "from src.database import EnergyDatabase; db = EnergyDatabase(); db.initialize(); print('Kész:', db.db_path.resolve())"
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TableSpec:
    name: str
    value_column: str
    sql_type: str


TABLE_SPECS: dict[str, TableSpec] = {
    "power_5min": TableSpec(
        name="power_5min",
        value_column="power_w",
        sql_type="INTEGER",
    ),
    "power_hourly": TableSpec(
        name="power_hourly",
        value_column="power_w",
        sql_type="INTEGER",
    ),
    "energy_hourly": TableSpec(
        name="energy_hourly",
        value_column="energy_kwh",
        sql_type="REAL",
    ),
    "energy_daily": TableSpec(
        name="energy_daily",
        value_column="energy_kwh",
        sql_type="REAL",
    ),
    "energy_monthly": TableSpec(
        name="energy_monthly",
        value_column="energy_kwh",
        sql_type="REAL",
    ),
}


class EnergyDatabase:
    def __init__(self, db_path: str | Path = Path("data/energy.db")) -> None:

        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:

        with self._connect() as conn:
            for spec in TABLE_SPECS.values():
                conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {spec.name} (
                        timestamp TEXT PRIMARY KEY,
                        {spec.value_column} {spec.sql_type} NOT NULL
                    )
                    """
                )
            conn.commit()

    def _get_spec(self, table_name: str) -> TableSpec:

        if table_name not in TABLE_SPECS:
            allowed = ", ".join(sorted(TABLE_SPECS.keys()))
            raise ValueError(
                f"Ismeretlen vagy nem engedélyezett táblanév: '{table_name}'. "
                f"Engedélyezett táblák: {allowed}"
            )
        return TABLE_SPECS[table_name]

    def _normalize_rows(
        self,
        spec: TableSpec,
        rows: Sequence[tuple[str, int | float]] | Sequence[Mapping[str, Any]],
    ) -> list[tuple[str, int | float]]:

        normalized: list[tuple[str, int | float]] = []
        for row in rows:
            if isinstance(row, Mapping):
                ts = row["timestamp"]
                val = row[spec.value_column]
            else:
                ts, val = row[0], row[1]

            if not isinstance(ts, str) or not ts:
                raise ValueError(f"Érvénytelen timestamp érték: {ts!r}")
            if (
                val is None
                or isinstance(val, bool)
                or not isinstance(val, (int, float))
            ):
                raise ValueError(
                    f"Érvénytelen mérési érték a '{spec.value_column}' oszlophoz: {val!r}"
                )

            normalized.append((ts, val))
        return normalized

    def upsert_records(
        self,
        table_name: str,
        rows: Sequence[tuple[str, int | float]] | Sequence[Mapping[str, Any]],
    ) -> int:

        spec = self._get_spec(table_name)
        prepared = self._normalize_rows(spec, rows)
        if not prepared:
            return 0

        sql = (
            f"INSERT OR REPLACE INTO {spec.name} (timestamp, {spec.value_column}) "
            "VALUES (?, ?)"
        )
        with self._connect() as conn:
            conn.executemany(sql, prepared)
            conn.commit()

        return len(prepared)

    def upsert_loaded_sheets(self, sheets: Mapping[str, Any]) -> dict[str, int]:

        results: dict[str, int] = {}
        for table_name, sheet in sheets.items():
            records = getattr(sheet, "records", sheet)
            results[table_name] = self.upsert_records(table_name, records)
        return results

    def query_range(
        self,
        table_name: str,
        start_ts: str | None = None,
        end_ts: str | None = None,
    ) -> list[dict[str, Any]]:

        spec = self._get_spec(table_name)
        clauses: list[str] = []
        params: list[Any] = []

        if start_ts is not None:
            clauses.append("timestamp >= ?")
            params.append(start_ts)
        if end_ts is not None:
            clauses.append("timestamp <= ?")
            params.append(end_ts)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT timestamp, {spec.value_column} "
            f"FROM {spec.name} {where_sql} ORDER BY timestamp ASC"
        )

        with self._connect() as conn:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
