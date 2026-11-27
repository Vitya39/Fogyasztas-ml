"""
.xls fájlok beolvasása - beolvassa a Power.xls és Energy Usage.xls
fájlokat, normalizálja az adatokat, és `LoadedSheet` objektumokat hoz
létre, ami továbbítható az `EnergyDatabase` osztálynak a rekordok
betöltéséhez.

tesztparancs (létrehozza az adatbázist és betölti az adatokat):
py -c "from src.data_loader import load_raw_exports; from src.database import EnergyDatabase; db = EnergyDatabase(); db.initialize(); sheets = load_raw_exports(); print(db.upsert_loaded_sheets(sheets))"
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class LoadedSheet:
    table_name: str
    value_column: str
    records: list[tuple[str, int | float]]
    source_file: Path
    sheet_name: str


@dataclass(frozen=True)
class _SheetMapping:
    sheet_name: str
    table_name: str
    value_column: str
    caster: Callable[[Any], int | float]


def _cast_int_power(value: Any) -> int:

    return int(round(float(value)))


def _cast_float_energy(value: Any) -> float:

    return float(value)


POWER_SHEET_MAPPINGS: tuple[_SheetMapping, ...] = (
    _SheetMapping(
        sheet_name="Day",
        table_name="power_5min",
        value_column="power_w",
        caster=_cast_int_power,
    ),
    _SheetMapping(
        sheet_name="Week",
        table_name="power_hourly",
        value_column="power_w",
        caster=_cast_int_power,
    ),
)

ENERGY_SHEET_MAPPINGS: tuple[_SheetMapping, ...] = (
    _SheetMapping(
        sheet_name="Day",
        table_name="energy_hourly",
        value_column="energy_kwh",
        caster=_cast_float_energy,
    ),
    _SheetMapping(
        sheet_name="Month",
        table_name="energy_daily",
        value_column="energy_kwh",
        caster=_cast_float_energy,
    ),
    _SheetMapping(
        sheet_name="Year",
        table_name="energy_monthly",
        value_column="energy_kwh",
        caster=_cast_float_energy,
    ),
)


class ExcelLoader:
    def __init__(self, engine: str = "xlrd") -> None:

        self.engine = engine

    def _read_raw_sheet(self, file_path: Path, sheet_name: str) -> pd.DataFrame:

        if not file_path.exists():
            raise FileNotFoundError(
                f"A bemeneti `.xls` fájl nem található: {file_path}"
            )

        try:
            df = pd.read_excel(file_path, sheet_name=sheet_name, engine=self.engine)
        except ValueError as exc:
            raise ValueError(
                f"A '{sheet_name}' munkalap nem érhető el a '{file_path}' fájlban."
            ) from exc

        return df

    def normalize_sheet(
        self,
        df: pd.DataFrame,
        value_column: str,
        caster: Callable[[Any], int | float],
    ) -> list[tuple[str, int | float]]:

        if df.shape[1] < 2:
            raise ValueError(
                f"Legalább 2 oszlopra van szükség (időintervallum és érték), "
                f"de csak {df.shape[1]} található."
            )

        work_df = df.iloc[:, :2].copy()
        work_df.columns = ["timestamp", value_column]

        work_df["timestamp"] = pd.to_datetime(work_df["timestamp"], errors="coerce")
        work_df[value_column] = pd.to_numeric(work_df[value_column], errors="coerce")

        valid_df = work_df.dropna(subset=["timestamp", value_column])

        records: list[tuple[str, int | float]] = []
        for ts, raw_val in zip(valid_df["timestamp"], valid_df[value_column]):
            iso_ts = pd.Timestamp(ts).isoformat()
            records.append((iso_ts, caster(raw_val)))

        return records

    def load_workbook_sheets(
        self,
        file_path: str | Path,
        mappings: tuple[_SheetMapping, ...],
    ) -> dict[str, LoadedSheet]:

        resolved_path = Path(file_path)
        loaded: dict[str, LoadedSheet] = {}

        for mapping in mappings:
            raw_df = self._read_raw_sheet(resolved_path, mapping.sheet_name)
            records = self.normalize_sheet(
                df=raw_df,
                value_column=mapping.value_column,
                caster=mapping.caster,
            )
            loaded[mapping.table_name] = LoadedSheet(
                table_name=mapping.table_name,
                value_column=mapping.value_column,
                records=records,
                source_file=resolved_path,
                sheet_name=mapping.sheet_name,
            )

        return loaded


def load_power_xls(
    file_path: str | Path = Path("data/raw/Power.xls"),
    loader: ExcelLoader | None = None,
) -> dict[str, LoadedSheet]:

    active_loader = loader if loader is not None else ExcelLoader()
    return active_loader.load_workbook_sheets(file_path, POWER_SHEET_MAPPINGS)


def load_energy_usage_xls(
    file_path: str | Path = Path("data/raw/Energy Usage.xls"),
    loader: ExcelLoader | None = None,
) -> dict[str, LoadedSheet]:

    active_loader = loader if loader is not None else ExcelLoader()
    return active_loader.load_workbook_sheets(file_path, ENERGY_SHEET_MAPPINGS)


def load_raw_exports(
    raw_dir: str | Path = Path("data/raw"),
    power_filename: str = "Power.xls",
    energy_filename: str = "Energy Usage.xls",
) -> dict[str, LoadedSheet]:

    base_dir = Path(raw_dir)
    loader = ExcelLoader()

    combined: dict[str, LoadedSheet] = {}
    combined.update(load_power_xls(base_dir / power_filename, loader=loader))
    combined.update(load_energy_usage_xls(base_dir / energy_filename, loader=loader))
    return combined
