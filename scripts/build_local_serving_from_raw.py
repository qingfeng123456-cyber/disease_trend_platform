from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# On some Windows/VM setups joblib cannot detect physical cores and prints a
# distracting traceback. One worker is sufficient for this teaching pipeline.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

from src.common.config import get_setting, load_settings
from src.common.paths import project_path, safe_relative
from src.models.metrics import regression_metrics


COVID_DISEASE = "COVID-19"
COVID_HOSPITAL_DISEASE = "COVID-19 Hospital Admissions"
INFLUENZA_DISEASE = "Influenza"
RSV_DISEASE = "RSV"
TUBERCULOSIS_DISEASE = "Tuberculosis"
DISEASE_ORDER = [
    COVID_DISEASE,
    INFLUENZA_DISEASE,
    RSV_DISEASE,
    TUBERCULOSIS_DISEASE,
    COVID_HOSPITAL_DISEASE,
]

MODEL_NAME = "local_sklearn_gbdt"
LSTM_MODEL_NAME = "local_pytorch_lstm"
MOVING_AVERAGE_MODEL = "moving_average"
BASELINE_MODEL = MOVING_AVERAGE_MODEL
MODEL_OPTIONS = ["naive_last_value", MOVING_AVERAGE_MODEL, MODEL_NAME]
ISO3_PATTERN = re.compile(r"^[A-Z]{3}$")

warnings.filterwarnings("ignore", message="Could not find the number of physical cores.*", category=UserWarning)


class PipelineProgress:
    def __init__(self, total: int, *, enabled: bool = True) -> None:
        self.total = total
        self.enabled = enabled
        self.step = 0
        self.started_at = time.perf_counter()
        self.step_started_at = self.started_at

    def start(self, title: str) -> None:
        self.step += 1
        self.step_started_at = time.perf_counter()
        if not self.enabled:
            return
        width = 24
        done = int(width * (self.step - 1) / max(self.total, 1))
        bar = "=" * done + "." * (width - done)
        percent = int((self.step - 1) / max(self.total, 1) * 100)
        print(f"\n[{bar}] {self.step}/{self.total} {percent:3d}% {title}", flush=True)

    def done(self, detail: str = "") -> None:
        if not self.enabled:
            return
        elapsed = time.perf_counter() - self.step_started_at
        suffix = f" | {detail}" if detail else ""
        print(f"  OK {elapsed:.1f}s{suffix}", flush=True)

    def finish(self, detail: str = "") -> None:
        if not self.enabled:
            return
        elapsed = time.perf_counter() - self.started_at
        suffix = f" | {detail}" if detail else ""
        print(f"\n[{'=' * 24}] {self.total}/{self.total} 100% DONE in {elapsed:.1f}s{suffix}", flush=True)


def text_progress_bar(current: int, total: int, width: int = 24) -> str:
    total = max(total, 1)
    done = min(width, int(width * current / total))
    return "=" * done + "." * (width - done)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if math.isnan(float(value)) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def resolve_latest_csv(path: Path, pattern: str = "*.csv") -> Path:
    if path.is_file():
        return path
    files = sorted(path.rglob(pattern), key=lambda item: (item.stat().st_mtime, item.name))
    if not files:
        raise FileNotFoundError(f"No CSV matching {pattern} under {path}")
    return files[-1]


def iso_date(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()


def numeric_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def read_country_mapping() -> dict[str, dict[str, str]]:
    path = project_path("config", "country_name_mapping.csv")
    mapping = pd.read_csv(path, dtype=str).fillna("")
    mapping = mapping[mapping["enabled"].str.lower().eq("true")]
    result: dict[str, dict[str, str]] = {}
    for row in mapping.to_dict("records"):
        epidemic_name = row["epidemic_name"].strip()
        if epidemic_name:
            result[epidemic_name] = {
                "location": row["standard_name"].strip() or row["population_name"].strip() or epidemic_name,
                "location_code": row["location_code"].strip().upper(),
            }
    return result


def read_location_catalog(path: Path) -> pd.DataFrame:
    catalog = pd.read_csv(path)
    catalog["location_code"] = catalog["location_code"].astype(str).str.upper().str.strip()
    enabled = catalog.get("enabled", pd.Series(True, index=catalog.index)).astype(str).str.lower().isin({"1", "true", "yes", "y"})
    catalog = catalog[enabled].copy()
    for column in ["latitude", "longitude"]:
        catalog[column] = pd.to_numeric(catalog[column], errors="coerce")
    return catalog[["location_code", "location", "representative_city", "latitude", "longitude"]].drop_duplicates("location_code")


def clean_owid(
    owid_path: Path,
    selected_codes: set[str],
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    available = pd.read_csv(owid_path, nrows=0).columns.tolist()
    wanted = [
        "country",
        "date",
        "code",
        "total_cases",
        "new_cases",
        "new_cases_smoothed",
        "total_deaths",
        "new_deaths",
        "population",
        "population_density",
        "gdp_per_capita",
        "stringency_index",
        "reproduction_rate",
        "people_vaccinated_per_hundred",
        "people_fully_vaccinated_per_hundred",
        "hospital_beds_per_thousand",
    ]
    raw = pd.read_csv(owid_path, usecols=[column for column in wanted if column in available], low_memory=False)
    input_rows = len(raw)
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw["location_code"] = raw["code"].astype("string").str.upper().str.strip()
    raw = raw[
        raw["location_code"].str.fullmatch(r"[A-Z]{3}", na=False)
        & raw["location_code"].isin(selected_codes)
        & raw["date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))
    ].copy()
    numeric_columns = [column for column in wanted if column not in {"country", "date", "code"} and column in raw.columns]
    for column in numeric_columns:
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    raw = raw.sort_values(["location_code", "date"]).drop_duplicates(["location_code", "date"], keep="last")

    derived_new_cases = raw.groupby("location_code")["total_cases"].diff() if "total_cases" in raw else pd.Series(np.nan, index=raw.index)
    published_new_cases = raw.get("new_cases", pd.Series(np.nan, index=raw.index))
    raw["new_cases_raw"] = published_new_cases.fillna(derived_new_cases)
    raw["new_cases_clean"] = raw["new_cases_raw"].clip(lower=0)
    raw["is_negative_case_correction"] = raw["new_cases_raw"].lt(0).fillna(False)
    raw["new_deaths"] = raw.get("new_deaths", pd.Series(np.nan, index=raw.index)).clip(lower=0)
    raw["is_negative_death_correction"] = raw.get("new_deaths", pd.Series(np.nan, index=raw.index)).lt(0).fillna(False)
    raw["published_smoothed"] = raw.get("new_cases_smoothed", pd.Series(np.nan, index=raw.index))
    raw["location"] = raw["country"].astype(str).str.strip()
    raw["disease"] = COVID_DISEASE
    raw["frequency"] = "daily"
    raw["period_days"] = 1
    raw["metric"] = "new_cases"
    raw["metric_label"] = "日新增病例"
    raw["value"] = raw["new_cases_clean"]
    raw["source"] = "Our World in Data COVID compact"
    raw["quality_flag"] = np.where(raw["is_negative_case_correction"], "negative_revision_clipped", "ok")
    raw["year"] = raw["date"].dt.year
    raw["source_population"] = raw.get("population", pd.Series(np.nan, index=raw.index))
    raw["source_density_per_km2"] = raw.get("population_density", pd.Series(np.nan, index=raw.index))
    raw["source_gdp_per_capita"] = raw.get("gdp_per_capita", pd.Series(np.nan, index=raw.index))

    quality = {
        "input_path": safe_relative(owid_path),
        "input_rows": input_rows,
        "output_rows": len(raw),
        "country_count": int(raw["location_code"].nunique()),
        "date_min": iso_date(raw["date"].min()),
        "date_max": iso_date(raw["date"].max()),
        "duplicate_country_date_count": int(raw.duplicated(["location_code", "date"]).sum()),
        "negative_case_correction_count": int(raw["is_negative_case_correction"].sum()),
        "missing_new_cases_rate": round(float(raw["value"].isna().mean()), 6),
        "role": "primary COVID-19 daily epidemic table",
    }
    return raw, quality


def clean_kaggle_covid_validation(
    epidemic_path: Path,
    mapping: dict[str, dict[str, str]],
    selected_codes: set[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = pd.read_csv(epidemic_path)
    input_rows = len(raw)
    raw = raw.rename(
        columns={
            "ObservationDate": "date_raw",
            "Province/State": "province",
            "Country/Region": "country_region",
            "Last Update": "last_update_raw",
        }
    )
    raw["date"] = pd.to_datetime(raw["date_raw"], format="%m/%d/%Y", errors="coerce")
    raw["province"] = raw["province"].astype("string").str.strip().replace({"": pd.NA})
    raw["country_region"] = raw["country_region"].astype("string").str.strip()
    raw["last_update_ts"] = pd.to_datetime(raw["last_update_raw"], errors="coerce")
    for column in ["Confirmed", "Deaths", "Recovered"]:
        raw[column] = pd.to_numeric(raw[column], errors="coerce").fillna(0.0)
    raw["location_code"] = raw["country_region"].map(
        lambda value: (mapping.get(str(value)) or {}).get("location_code") or pd.NA
    )
    raw = raw.dropna(subset=["date", "country_region", "location_code"])
    raw = raw[raw["location_code"].isin(selected_codes)].copy()
    duplicate_keys = int(raw.duplicated(["country_region", "province", "date"], keep=False).sum())
    raw = (
        raw.sort_values(["country_region", "province", "date", "last_update_ts", "SNo"])
        .drop_duplicates(["country_region", "province", "date"], keep="last")
        .copy()
    )
    group_keys = ["date", "country_region"]
    raw["group_has_province"] = raw.groupby(group_keys, dropna=False)["province"].transform(lambda series: series.notna().any())
    selected = raw[(raw["group_has_province"] & raw["province"].notna()) | (~raw["group_has_province"] & raw["province"].isna())]
    country_day = (
        selected.groupby(["date", "location_code"], as_index=False)
        .agg(total_cases=("Confirmed", "sum"), total_deaths=("Deaths", "sum"), total_recovered=("Recovered", "sum"))
        .sort_values(["location_code", "date"])
    )
    quality = {
        "input_path": safe_relative(epidemic_path),
        "input_rows": input_rows,
        "output_rows": len(country_day),
        "country_count": int(country_day["location_code"].nunique()),
        "date_min": iso_date(country_day["date"].min()),
        "date_max": iso_date(country_day["date"].max()),
        "duplicate_country_province_date_key_count": duplicate_keys,
        "role": "validation only; not appended to OWID COVID rows",
    }
    return country_day, quality


def compare_covid_sources(owid: pd.DataFrame, kaggle: pd.DataFrame) -> dict[str, Any]:
    overlap = owid[["date", "location_code", "total_cases"]].merge(
        kaggle[["date", "location_code", "total_cases"]],
        on=["date", "location_code"],
        how="inner",
        suffixes=("_owid", "_kaggle"),
    )
    comparable = overlap[(overlap["total_cases_owid"] > 0) & (overlap["total_cases_kaggle"] > 0)].copy()
    if comparable.empty:
        return {"overlap_rows": 0, "median_relative_difference": None, "within_5_percent_share": None}
    denominator = comparable[["total_cases_owid", "total_cases_kaggle"]].max(axis=1).clip(lower=1)
    relative = (comparable["total_cases_owid"] - comparable["total_cases_kaggle"]).abs() / denominator
    return {
        "overlap_rows": int(len(comparable)),
        "date_min": iso_date(comparable["date"].min()),
        "date_max": iso_date(comparable["date"].max()),
        "median_relative_difference": round(float(relative.median()), 6),
        "within_5_percent_share": round(float(relative.le(0.05).mean()), 6),
        "note": "Sources are compared for quality control and are never summed together.",
    }


def clean_tuberculosis(
    root: Path,
    selected_codes: set[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    files = {path.name.split("-", 1)[0].strip(): path for path in root.glob("*.csv")}
    required = files.get("1")
    if required is None:
        raise FileNotFoundError(f"Tuberculosis incidence CSV not found under {root}")

    incidence = pd.read_csv(required).rename(
        columns={
            "Entity": "location",
            "Code": "location_code",
            "Year": "year",
            "Estimated incidence of all forms of tuberculosis": "incidence_per_100k",
        }
    )
    incidence["location_code"] = incidence["location_code"].astype("string").str.upper().str.strip()
    incidence = incidence[incidence["location_code"].isin(selected_codes)].copy()
    incidence["year"] = pd.to_numeric(incidence["year"], errors="coerce").astype("Int64")
    incidence["incidence_per_100k"] = pd.to_numeric(incidence["incidence_per_100k"], errors="coerce")

    file_rows = {required.name: int(len(pd.read_csv(required, usecols=[0])))}
    deaths_path = files.get("2")
    if deaths_path:
        deaths = pd.read_csv(deaths_path)
        file_rows[deaths_path.name] = len(deaths)
        value_columns = deaths.columns[3:]
        deaths["tb_deaths_all_ages"] = deaths[value_columns].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)
        deaths = deaths.rename(columns={"Code": "location_code", "Year": "year"})
        incidence = incidence.merge(deaths[["location_code", "year", "tb_deaths_all_ages"]], on=["location_code", "year"], how="left")

    detection_path = files.get("3")
    if detection_path:
        detection = pd.read_csv(detection_path).rename(
            columns={"Code": "location_code", "Year": "year", "Case detection rate (all forms)": "case_detection_rate"}
        )
        file_rows[detection_path.name] = len(detection)
        incidence = incidence.merge(detection[["location_code", "year", "case_detection_rate"]], on=["location_code", "year"], how="left")

    treatment_path = files.get("4")
    if treatment_path:
        treatment = pd.read_csv(treatment_path).rename(columns={"Code": "location_code", "Year": "year"})
        file_rows[treatment_path.name] = len(treatment)
        treatment_columns = [column for column in treatment.columns if column not in {"Entity", "location_code", "year"}]
        rename_map = {
            treatment_columns[0]: "treatment_success_new_tb" if len(treatment_columns) > 0 else "",
            treatment_columns[1]: "treatment_success_mdr_tb" if len(treatment_columns) > 1 else "",
            treatment_columns[2]: "treatment_success_xdr_tb" if len(treatment_columns) > 2 else "",
        }
        rename_map = {key: value for key, value in rename_map.items() if key and value}
        treatment = treatment.rename(columns=rename_map)
        incidence = incidence.merge(treatment[["location_code", "year", *rename_map.values()]], on=["location_code", "year"], how="left")

    hiv_path = files.get("5")
    if hiv_path:
        hiv = pd.read_csv(hiv_path).rename(
            columns={"Code": "location_code", "Year": "year", "Estimated HIV in incident tuberculosis": "tb_incident_hiv_share"}
        )
        file_rows[hiv_path.name] = len(hiv)
        incidence = incidence.merge(hiv[["location_code", "year", "tb_incident_hiv_share"]], on=["location_code", "year"], how="left")

    under_five_path = files.get("6")
    if under_five_path:
        under_five = pd.read_csv(under_five_path).rename(columns={"Code": "location_code", "Year": "year"})
        file_rows[under_five_path.name] = len(under_five)
        value_column = next(column for column in under_five.columns if column not in {"Entity", "location_code", "year"})
        under_five = under_five.rename(columns={value_column: "tb_deaths_under_five"})
        incidence = incidence.merge(under_five[["location_code", "year", "tb_deaths_under_five"]], on=["location_code", "year"], how="left")

    for column in incidence.columns:
        if column not in {"location", "location_code"}:
            incidence[column] = pd.to_numeric(incidence[column], errors="coerce")
    incidence = incidence.dropna(subset=["year", "incidence_per_100k"]).copy()
    incidence["year"] = incidence["year"].astype(int)
    incidence["date"] = pd.to_datetime(incidence["year"].astype(str) + "-12-31")
    incidence["disease"] = TUBERCULOSIS_DISEASE
    incidence["frequency"] = "annual"
    incidence["period_days"] = 365
    incidence["metric"] = "incidence_per_100k"
    incidence["metric_label"] = "估计发病率（每10万人）"
    incidence["value"] = incidence["incidence_per_100k"]
    incidence["new_cases_clean"] = incidence["value"]
    incidence["published_smoothed"] = np.nan
    incidence["total_cases"] = np.nan
    incidence["total_deaths"] = incidence.get("tb_deaths_all_ages", pd.Series(np.nan, index=incidence.index))
    incidence["new_deaths"] = incidence["total_deaths"]
    incidence["is_negative_case_correction"] = False
    incidence["is_negative_death_correction"] = False
    incidence["source_population"] = np.nan
    incidence["source_density_per_km2"] = np.nan
    incidence["source_gdp_per_capita"] = np.nan
    incidence["source"] = "Kaggle Tuberculosis / Our World in Data indicators"
    incidence["quality_flag"] = "ok"

    auxiliary_columns = [
        column
        for column in [
            "tb_deaths_all_ages",
            "case_detection_rate",
            "treatment_success_new_tb",
            "treatment_success_mdr_tb",
            "treatment_success_xdr_tb",
            "tb_incident_hiv_share",
            "tb_deaths_under_five",
        ]
        if column in incidence
    ]
    quality = {
        "input_root": safe_relative(root),
        "input_files": {name: rows for name, rows in file_rows.items()},
        "output_rows": len(incidence),
        "country_count": int(incidence["location_code"].nunique()),
        "year_min": int(incidence["year"].min()),
        "year_max": int(incidence["year"].max()),
        "metric": "estimated incidence per 100,000 people",
        "auxiliary_non_missing_rate": {
            column: round(float(incidence[column].notna().mean()), 6) for column in auxiliary_columns
        },
    }
    return incidence.sort_values(["location_code", "date"]), quality


def normalize_percent(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.where(numeric > 1, numeric * 100)


def clean_respiratory(
    respiratory_path: Path,
    selected_codes: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    available = pd.read_csv(respiratory_path, nrows=0).columns.tolist()
    wanted = [
        "Week Ending Date",
        "Geographic aggregation",
        "Total Patients Hospitalized with COVID-19",
        "Total Patients Hospitalized with Influenza",
        "Total Patients Hospitalized with RSV",
        "Total COVID-19 Admissions",
        "Total Influenza Admissions",
        "Total RSV Admissions",
        "Percent Inpatient Beds Occupied",
        "Percent Inpatient Beds Occupied by COVID-19 Patients",
        "Percent Inpatient Beds Occupied by Influenza Patients",
        "Percent Inpatient Beds Occupied by RSV Patients",
        "Number Hospitals Reporting COVID-19 Admissions",
        "Number Hospitals Reporting Influenza Admissions",
        "Number Hospitals Reporting RSV Admissions",
    ]
    raw = pd.read_csv(respiratory_path, usecols=[column for column in wanted if column in available], low_memory=False)
    input_rows = len(raw)
    raw["date"] = pd.to_datetime(raw["Week Ending Date"], errors="coerce")
    national = raw[raw["Geographic aggregation"].eq("USA")].sort_values("date").drop_duplicates("date", keep="last").copy()
    if "USA" not in selected_codes:
        national = national.iloc[0:0].copy()
    percent_columns = [column for column in national.columns if column.startswith("Percent ")]
    for column in percent_columns:
        national[column] = normalize_percent(national[column])

    definitions = [
        (COVID_HOSPITAL_DISEASE, "Total COVID-19 Admissions", "Total Patients Hospitalized with COVID-19"),
        (INFLUENZA_DISEASE, "Total Influenza Admissions", "Total Patients Hospitalized with Influenza"),
        (RSV_DISEASE, "Total RSV Admissions", "Total Patients Hospitalized with RSV"),
    ]
    observations: list[pd.DataFrame] = []
    for disease, admissions_column, hospitalized_column in definitions:
        if admissions_column not in national:
            continue
        frame = national.copy()
        frame["value"] = pd.to_numeric(frame[admissions_column], errors="coerce")
        frame["hospitalized_patients"] = pd.to_numeric(
            frame.get(hospitalized_column, pd.Series(np.nan, index=frame.index)), errors="coerce"
        )
        frame = frame.dropna(subset=["date", "value"])
        frame["is_negative_case_correction"] = frame["value"].lt(0)
        frame["value"] = frame["value"].clip(lower=0)
        frame["location_code"] = "USA"
        frame["location"] = "United States"
        frame["disease"] = disease
        frame["frequency"] = "weekly"
        frame["period_days"] = 7
        frame["metric"] = "hospital_admissions"
        frame["metric_label"] = "每周新增住院入院人数"
        frame["new_cases_clean"] = frame["value"]
        frame["published_smoothed"] = np.nan
        frame["total_cases"] = np.nan
        frame["total_deaths"] = np.nan
        frame["new_deaths"] = np.nan
        frame["is_negative_death_correction"] = False
        frame["source_population"] = np.nan
        frame["source_density_per_km2"] = np.nan
        frame["source_gdp_per_capita"] = np.nan
        frame["source"] = "Kaggle Weekly Hospital Respiratory Data and Metrics"
        frame["quality_flag"] = np.where(frame["is_negative_case_correction"], "negative_revision_clipped", "ok")
        frame["year"] = frame["date"].dt.year
        observations.append(frame)

    combined = pd.concat(observations, ignore_index=True, sort=False) if observations else pd.DataFrame()
    metric_counts = combined.groupby("disease").size().to_dict() if not combined.empty else {}
    quality = {
        "input_path": safe_relative(respiratory_path),
        "input_rows": input_rows,
        "national_week_rows": len(national),
        "output_rows": len(combined),
        "date_min": iso_date(national["date"].min()) if not national.empty else None,
        "date_max": iso_date(national["date"].max()) if not national.empty else None,
        "disease_rows": metric_counts,
        "geographic_rule": "Use the provided USA national aggregation row; state rows are not summed again.",
        "percent_unit_rule": "Values from 0 to 1 are converted to percent units from 0 to 100.",
    }
    return combined, national, quality


def clean_population(
    kaggle_population_path: Path,
    world_bank_path: Path | None,
    selected_codes: set[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    kaggle_raw = pd.read_csv(kaggle_population_path)
    population_columns = [column for column in kaggle_raw if re.fullmatch(r"\d{4} Population", column)]
    kaggle_long = kaggle_raw.melt(
        id_vars=["CCA3", "Country/Territory", "Density (per km²)", "Growth Rate"],
        value_vars=population_columns,
        var_name="population_year",
        value_name="population",
    ).rename(
        columns={
            "CCA3": "location_code",
            "Country/Territory": "location",
            "Density (per km²)": "density_per_km2",
            "Growth Rate": "growth_rate",
        }
    )
    kaggle_long["year"] = kaggle_long["population_year"].str.extract(r"(\d{4})").astype(int)
    kaggle_long["urban_population_ratio"] = np.nan
    kaggle_long["gdp_per_capita"] = np.nan
    kaggle_long["source"] = "Kaggle World Population"
    kaggle_long["source_priority"] = 0

    frames = [kaggle_long]
    world_bank_rows = 0
    if world_bank_path and world_bank_path.exists():
        world_bank = pd.read_csv(world_bank_path)
        world_bank_rows = len(world_bank)
        world_bank["density_per_km2"] = np.nan
        world_bank["growth_rate"] = np.nan
        world_bank["source_priority"] = 1
        frames.append(
            world_bank[
                [
                    "location_code",
                    "location",
                    "year",
                    "population",
                    "urban_population_ratio",
                    "gdp_per_capita",
                    "density_per_km2",
                    "growth_rate",
                    "source",
                    "source_priority",
                ]
            ]
        )

    population = pd.concat(frames, ignore_index=True, sort=False)
    population["location_code"] = population["location_code"].astype(str).str.upper().str.strip()
    population = population[population["location_code"].isin(selected_codes)].copy()
    for column in ["year", "population", "urban_population_ratio", "gdp_per_capita", "density_per_km2", "growth_rate"]:
        population[column] = pd.to_numeric(population[column], errors="coerce")
    population = (
        population.sort_values(["location_code", "year", "source_priority"])
        .drop_duplicates(["location_code", "year"], keep="last")
        .copy()
    )

    yearly_frames: list[pd.DataFrame] = []
    for code, group in population.groupby("location_code"):
        group = group.sort_values("year").copy()
        min_year = int(min(1990, group["year"].min()))
        max_year = int(max(2025, group["year"].max()))
        grid = pd.DataFrame({"year": range(min_year, max_year + 1)})
        grid["location_code"] = code
        merged = grid.merge(group, on=["location_code", "year"], how="left")
        exact_population = merged["population"].notna()
        merged["population"] = merged["population"].interpolate(method="linear", limit_area="inside")
        merged["population_is_interpolated"] = ~exact_population & merged["population"].notna()
        merged["location"] = merged["location"].ffill().bfill()
        for column in ["density_per_km2", "growth_rate"]:
            merged[column] = merged[column].ffill().bfill()
        merged["source"] = merged["source"].where(
            exact_population,
            "Interpolated between Kaggle/World Bank population years",
        )
        yearly_frames.append(merged)
    cleaned = pd.concat(yearly_frames, ignore_index=True, sort=False) if yearly_frames else population
    cleaned = cleaned.dropna(subset=["location_code", "year", "population"]).copy()
    cleaned["year"] = cleaned["year"].astype(int)
    columns = [
        "location_code",
        "location",
        "year",
        "population",
        "population_is_interpolated",
        "urban_population_ratio",
        "gdp_per_capita",
        "density_per_km2",
        "growth_rate",
        "source",
    ]
    cleaned = cleaned[columns]
    quality = {
        "kaggle_input_path": safe_relative(kaggle_population_path),
        "kaggle_input_rows": len(kaggle_raw),
        "world_bank_input_path": safe_relative(world_bank_path) if world_bank_path else None,
        "world_bank_input_rows": world_bank_rows,
        "output_rows": len(cleaned),
        "country_count": int(cleaned["location_code"].nunique()),
        "year_min": int(cleaned["year"].min()),
        "year_max": int(cleaned["year"].max()),
        "interpolated_population_rows": int(cleaned["population_is_interpolated"].sum()),
        "missing_gdp_rate": round(float(cleaned["gdp_per_capita"].isna().mean()), 6),
    }
    return cleaned, quality


def clean_weather(weather_root: Path, selected_codes: set[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    files = sorted(weather_root.glob("*/*.csv"))
    if not files:
        raise FileNotFoundError(f"Open-Meteo CSV not found under {weather_root}")
    frames = [pd.read_csv(path) for path in files]
    raw = pd.concat(frames, ignore_index=True)
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw["location_code"] = raw["location_code"].astype(str).str.upper().str.strip()
    raw = raw[raw["location_code"].isin(selected_codes)].copy()
    numeric_columns = [
        "latitude",
        "longitude",
        "temperature_mean",
        "temperature_max",
        "temperature_min",
        "precipitation_sum",
        "relative_humidity_mean",
        "wind_speed_max",
    ]
    for column in numeric_columns:
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    cleaned = (
        raw.dropna(subset=["date", "location_code"])
        .sort_values(["location_code", "date", "downloaded_at"])
        .drop_duplicates(["location_code", "date"], keep="last")
        .copy()
    )
    cleaned["year"] = cleaned["date"].dt.year
    quality = {
        "input_root": safe_relative(weather_root),
        "input_files": [safe_relative(path) for path in files],
        "input_rows": len(raw),
        "output_rows": len(cleaned),
        "country_count": int(cleaned["location_code"].nunique()),
        "date_min": iso_date(cleaned["date"].min()),
        "date_max": iso_date(cleaned["date"].max()),
        "rows_by_country": cleaned.groupby("location_code").size().to_dict(),
        "temperature_unit": "Celsius",
        "humidity_unit": "percent",
        "representative_city_notice": "One representative city is used as a country-level teaching proxy.",
    }
    return cleaned, quality


WEATHER_VALUE_COLUMNS = [
    "temperature_mean",
    "temperature_max",
    "temperature_min",
    "precipitation_sum",
    "relative_humidity_mean",
    "wind_speed_max",
]


def aggregate_weather(weather: pd.DataFrame, frequency: str) -> pd.DataFrame:
    frame = weather.copy()
    if frequency == "weekly":
        days_to_saturday = (5 - frame["date"].dt.dayofweek) % 7
        frame["join_date"] = frame["date"] + pd.to_timedelta(days_to_saturday, unit="D")
        grouped = frame.groupby(["location_code", "join_date"], as_index=False)[WEATHER_VALUE_COLUMNS].mean()
        grouped["weather_match_level"] = "weekly_mean_to_saturday"
        return grouped
    if frequency == "annual":
        frame["year"] = frame["date"].dt.year
        grouped = frame.groupby(["location_code", "year"], as_index=False)[WEATHER_VALUE_COLUMNS].mean()
        grouped["join_date"] = pd.to_datetime(grouped["year"].astype(str) + "-12-31")
        grouped = grouped.drop(columns="year")
        grouped["weather_match_level"] = "annual_mean"
        return grouped
    frame = frame.rename(columns={"date": "join_date"})
    frame["weather_match_level"] = "exact_day"
    return frame[["location_code", "join_date", *WEATHER_VALUE_COLUMNS, "weather_match_level"]]


def add_time_features(group: pd.DataFrame) -> pd.DataFrame:
    group = group.sort_values("date").copy()
    frequency = str(group["frequency"].iloc[0])
    if frequency == "daily":
        rolling_window, growth_steps, horizon_steps = 7, 7, 7
        rolling_label, horizon_label = "7日移动平均", "未来7日"
    elif frequency == "weekly":
        rolling_window, growth_steps, horizon_steps = 4, 1, 1
        rolling_label, horizon_label = "4周移动平均", "下一周"
    else:
        rolling_window, growth_steps, horizon_steps = 3, 1, 1
        rolling_label, horizon_label = "3年移动平均", "下一年"

    calculated_smoothed = group["value"].rolling(rolling_window, min_periods=1).mean()
    group["new_cases_smoothed"] = group["published_smoothed"].combine_first(calculated_smoothed)
    group["rolling_mean_7"] = calculated_smoothed
    group["rolling_label"] = rolling_label
    group["forecast_horizon_label"] = horizon_label
    group["horizon_steps"] = horizon_steps
    group["lag_1"] = group["new_cases_smoothed"].shift(1)
    group["lag_3"] = group["new_cases_smoothed"].shift(3)
    group["lag_7"] = group["new_cases_smoothed"].shift(7)
    group["lag_14"] = group["new_cases_smoothed"].shift(14)
    group["rolling_mean_3"] = group["value"].rolling(3, min_periods=1).mean()
    group["rolling_mean_14"] = group["value"].rolling(max(rolling_window * 2, 3), min_periods=1).mean()
    group["rolling_std_7"] = group["value"].rolling(rolling_window, min_periods=2).std(ddof=0)
    group["rolling_std_14"] = group["value"].rolling(max(rolling_window * 2, 3), min_periods=2).std(ddof=0)
    prior = group["new_cases_smoothed"].shift(growth_steps)
    group["growth_rate_1"] = (group["new_cases_smoothed"] - group["lag_1"]) / group["lag_1"].abs().clip(lower=1.0)
    group["growth_rate_7"] = (group["new_cases_smoothed"] - prior) / prior.abs().clip(lower=1.0)
    group["target_t_plus_7"] = group["new_cases_smoothed"].shift(-horizon_steps)
    return group


def build_features(
    observations: pd.DataFrame,
    weather: pd.DataFrame,
    population: pd.DataFrame,
    location_catalog: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    observations = observations.dropna(subset=["date", "location_code", "disease", "value"]).copy()
    observations["date"] = pd.to_datetime(observations["date"])
    observations["year"] = observations["date"].dt.year
    # OWID context fields are retained as explicit fallbacks. Remove their raw
    # names before joining the canonical yearly socioeconomic table.
    observations = observations.drop(
        columns=[
            column
            for column in ["population", "population_density", "gdp_per_capita", "density_per_km2", "growth_rate"]
            if column in observations.columns
        ]
    )

    enriched_parts: list[pd.DataFrame] = []
    for frequency, subset in observations.groupby("frequency", sort=False):
        weather_for_frequency = aggregate_weather(weather, frequency)
        part = subset.merge(
            weather_for_frequency,
            left_on=["location_code", "date"],
            right_on=["location_code", "join_date"],
            how="left",
        ).drop(columns=["join_date"])
        enriched_parts.append(part)
    joined = pd.concat(enriched_parts, ignore_index=True, sort=False)

    population_columns = [
        "location_code",
        "year",
        "population",
        "population_is_interpolated",
        "urban_population_ratio",
        "gdp_per_capita",
        "density_per_km2",
        "growth_rate",
    ]
    joined = joined.merge(population[population_columns], on=["location_code", "year"], how="left")
    joined["population"] = joined["population"].fillna(joined["source_population"])
    joined["density_per_km2"] = joined["density_per_km2"].fillna(joined["source_density_per_km2"])
    joined["gdp_per_capita"] = joined["gdp_per_capita"].fillna(joined["source_gdp_per_capita"])

    catalog = location_catalog.rename(
        columns={
            "location": "catalog_location",
            "representative_city": "catalog_representative_city",
            "latitude": "catalog_latitude",
            "longitude": "catalog_longitude",
        }
    )
    joined = joined.merge(catalog, on="location_code", how="left")
    joined["location"] = joined["location"].fillna(joined["catalog_location"])
    joined["representative_city"] = joined.get("representative_city", pd.Series(np.nan, index=joined.index)).fillna(
        joined["catalog_representative_city"]
    )
    joined["latitude"] = joined["catalog_latitude"]
    joined["longitude"] = joined["catalog_longitude"]
    joined["has_weather"] = joined["temperature_mean"].notna() & joined["relative_humidity_mean"].notna()
    joined["weather_match_level"] = joined["weather_match_level"].fillna("unmatched")

    joined = pd.concat(
        [add_time_features(group) for _, group in joined.groupby(["location_code", "disease"], sort=False)],
        ignore_index=True,
        sort=False,
    )
    joined["cases_per_million"] = np.where(
        joined["metric"].eq("incidence_per_100k"),
        joined["value"] * 10.0,
        joined["value"] / joined["population"].replace(0, np.nan) * 1_000_000.0,
    )
    joined["deaths_per_million"] = joined["new_deaths"] / joined["population"].replace(0, np.nan) * 1_000_000.0
    joined["month"] = joined["date"].dt.month
    joined["day_of_week"] = joined["date"].dt.dayofweek + 1
    joined["is_weekend"] = joined["day_of_week"].isin([6, 7]).astype(int)
    joined["data_mode"] = "real_local_multi_source"
    joined["model_eligible"] = joined["disease"].eq(COVID_DISEASE) & joined["frequency"].eq("daily")

    quality = {
        "feature_rows": len(joined),
        "location_count": int(joined["location_code"].nunique()),
        "disease_count": int(joined["disease"].nunique()),
        "date_min": iso_date(joined["date"].min()),
        "date_max": iso_date(joined["date"].max()),
        "rows_by_disease": joined.groupby("disease").size().to_dict(),
        "rows_by_frequency": joined.groupby("frequency").size().to_dict(),
        "weather_matched_rows": int(joined["has_weather"].sum()),
        "weather_unmatched_rows": int((~joined["has_weather"]).sum()),
        "weather_match_rate": round(float(joined["has_weather"].mean()), 6),
        "population_unmatched_rows": int(joined["population"].isna().sum()),
        "important_rule": "Epidemic rows are retained when weather is unavailable; weather is optional enrichment.",
    }
    return joined.sort_values(["location_code", "disease", "date"]), quality


FEATURE_COLUMNS = [
    "new_cases_smoothed",
    "lag_1",
    "lag_3",
    "lag_7",
    "lag_14",
    "rolling_mean_3",
    "rolling_mean_7",
    "rolling_mean_14",
    "rolling_std_7",
    "rolling_std_14",
    "growth_rate_1",
    "growth_rate_7",
    "cases_per_million",
    "deaths_per_million",
    "temperature_mean",
    "temperature_max",
    "temperature_min",
    "precipitation_sum",
    "relative_humidity_mean",
    "wind_speed_max",
    "has_weather",
    "population",
    "density_per_km2",
    "urban_population_ratio",
    "gdp_per_capita",
    "month",
    "day_of_week",
    "is_weekend",
]


def baseline_metrics_payload(trainable: pd.DataFrame, test_mask: pd.Series) -> dict[str, float]:
    actual = trainable.loc[test_mask, "target_t_plus_7"].astype(float).tolist()
    baseline = trainable.loc[test_mask, "rolling_mean_7"].astype(float).tolist()
    if not actual:
        return {"mae": 0.0, "rmse": 0.0, "r2": 0.0, "mape": 0.0, "smape": 0.0}
    return regression_metrics(actual, baseline)


def fit_predict(
    features: pd.DataFrame,
    seed: int,
    *,
    model_dir: Path,
    show_progress: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    data = features.copy()
    data["prediction_naive_last_value"] = data["new_cases_smoothed"].fillna(0.0)
    data["prediction_moving_average"] = data["rolling_mean_7"].fillna(data["new_cases_smoothed"]).fillna(0.0)
    data["prediction_local_sklearn_gbdt"] = data["prediction_moving_average"]
    data["prediction_t_plus_7"] = data["prediction_moving_average"]
    scope = data[data["model_eligible"]].copy()
    trainable = scope.dropna(subset=["target_t_plus_7", "lag_1", "lag_7", "rolling_mean_7", "population"]).copy()
    if trainable.empty:
        metrics = {
            "model": BASELINE_MODEL,
            "data_mode": "real_local_multi_source",
            "mae": 0.0,
            "rmse": 0.0,
            "r2": 0.0,
            "mape": 0.0,
            "smape": 0.0,
            "baseline_mae": 0.0,
            "beats_baseline": False,
            "feature_list": FEATURE_COLUMNS,
            "scope": "COVID-19 daily cases only",
            "note": "Not enough eligible daily rows; moving-average baseline is used.",
        }
        comparison = {"data_mode": "real_local_multi_source", "best_model": BASELINE_MODEL, "items": [metrics]}
        return data, metrics, comparison

    min_date = trainable["date"].min()
    max_date = trainable["date"].max()
    total_days = max((max_date - min_date).days, 1)
    train_cut = min_date + pd.Timedelta(days=int(total_days * 0.70))
    valid_cut = min_date + pd.Timedelta(days=int(total_days * 0.85))
    train_mask = trainable["date"] <= train_cut
    test_mask = trainable["date"] > valid_cut
    base_metrics = baseline_metrics_payload(trainable, test_mask)

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Could not find the number of physical cores.*")
            from sklearn.ensemble import HistGradientBoostingRegressor
    except Exception:
        metrics = {
            "model": BASELINE_MODEL,
            "data_mode": "real_local_multi_source",
            "train_rows": int(train_mask.sum()),
            "test_rows": int(test_mask.sum()),
            **base_metrics,
            "baseline_mae": base_metrics["mae"],
            "beats_baseline": False,
            "feature_list": FEATURE_COLUMNS,
            "scope": "COVID-19 daily cases only",
            "note": "scikit-learn is unavailable; moving-average baseline is used.",
        }
        comparison = {"data_mode": "real_local_multi_source", "best_model": BASELINE_MODEL, "items": [metrics]}
        return data, metrics, comparison

    model_columns = [column for column in FEATURE_COLUMNS if column in scope.columns]
    numeric = scope[model_columns].copy()
    numeric["has_weather"] = numeric["has_weather"].astype(float)
    categorical = pd.get_dummies(scope[["location_code"]], prefix=["loc"], dummy_na=False)
    x_all = pd.concat([numeric, categorical], axis=1)
    train_index = trainable.index[train_mask]
    test_index = trainable.index[test_mask]
    medians = x_all.loc[train_index].median(numeric_only=True).fillna(0.0)
    x_all = x_all.fillna(medians).fillna(0.0)
    y_train = data.loc[train_index, "target_t_plus_7"].astype(float)

    total_iterations = 120
    iteration_chunk = 20
    model = HistGradientBoostingRegressor(
        max_iter=iteration_chunk,
        learning_rate=0.06,
        max_leaf_nodes=31,
        random_state=seed,
        warm_start=True,
    )
    training_started = time.perf_counter()
    if show_progress:
        print(
            f"[GBDT] Training rows={len(train_index):,}, test rows={len(test_index):,}, "
            f"features={x_all.shape[1]}, iterations={total_iterations}",
            flush=True,
        )
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Could not find the number of physical cores.*")
        for completed_iterations in range(iteration_chunk, total_iterations + 1, iteration_chunk):
            model.set_params(max_iter=completed_iterations)
            model.fit(x_all.loc[train_index], y_train)
            if show_progress:
                percent = int(completed_iterations / total_iterations * 100)
                print(
                    f"  [{text_progress_bar(completed_iterations, total_iterations)}] "
                    f"GBDT {completed_iterations:03d}/{total_iterations:03d} {percent:3d}% "
                    f"elapsed={time.perf_counter() - training_started:.1f}s",
                    flush=True,
                )
        gbdt_prediction = np.maximum(model.predict(x_all), 0.0)
        data.loc[scope.index, "prediction_local_sklearn_gbdt"] = gbdt_prediction
        data.loc[scope.index, "prediction_t_plus_7"] = gbdt_prediction

    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "local_sklearn_gbdt.joblib"
    try:
        import joblib

        joblib.dump(
            {
                "model": model,
                "feature_columns": x_all.columns.tolist(),
                "medians": medians.to_dict(),
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "forecast_horizon_days": 7,
            },
            model_path,
        )
    except Exception as exc:
        if show_progress:
            print(f"[GBDT] Warning: model artifact could not be saved: {exc}", flush=True)

    actual = data.loc[test_index, "target_t_plus_7"].astype(float).tolist()
    predicted = data.loc[test_index, "prediction_local_sklearn_gbdt"].astype(float).tolist()
    naive_last = data.loc[test_index, "new_cases_smoothed"].astype(float).tolist()
    model_metrics = regression_metrics(actual, predicted) if actual else base_metrics
    naive_metrics = regression_metrics(actual, naive_last) if actual else base_metrics
    metrics = {
        "model": MODEL_NAME,
        "data_mode": "real_local_multi_source",
        "forecast_horizon": 7,
        "train_start": iso_date(min_date),
        "train_end": iso_date(train_cut),
        "validation_start": iso_date(train_cut + pd.Timedelta(days=1)),
        "validation_end": iso_date(valid_cut),
        "test_start": iso_date(valid_cut + pd.Timedelta(days=1)),
        "test_end": iso_date(max_date),
        "train_rows": int(train_mask.sum()),
        "validation_rows": int(((trainable["date"] > train_cut) & (trainable["date"] <= valid_cut)).sum()),
        "test_rows": int(test_mask.sum()),
        **model_metrics,
        "baseline_mae": base_metrics["mae"],
        "beats_baseline": model_metrics["mae"] <= base_metrics["mae"],
        "feature_list": model_columns,
        "model_path": safe_relative(model_path),
        "scope": "COVID-19 daily new cases; heterogeneous weekly/annual targets are excluded from this model",
        "note": "Weather is optional. Missing weather does not remove epidemic rows and is represented by has_weather.",
    }
    comparison = {
        "data_mode": "real_local_multi_source",
        "best_model": MODEL_NAME if metrics["beats_baseline"] else BASELINE_MODEL,
        "items": [
            {"model": "naive_last_value", **naive_metrics},
            {"model": BASELINE_MODEL, **base_metrics},
            {"model": MODEL_NAME, **model_metrics},
        ],
    }
    return data, metrics, comparison


def complete_model_training(
    features: pd.DataFrame,
    gbdt_metrics: dict[str, Any],
    comparison: dict[str, Any],
    *,
    enable_lstm: bool,
    model_dir: Path,
    gold_dir: Path,
    lstm_window: int,
    lstm_epochs: int,
    lstm_batch_size: int,
    lstm_hidden_size: int,
    lstm_patience: int,
    seed: int,
    show_progress: bool,
    show_lstm_batch_progress: bool,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any], list[str]]:
    data = features.copy()
    model_details: dict[str, dict[str, Any]] = {MODEL_NAME: gbdt_metrics}
    available_models = ["naive_last_value", MOVING_AVERAGE_MODEL, MODEL_NAME]

    if enable_lstm:
        from src.models.lstm_optional import (
            MODEL_NAME as PYTORCH_LSTM_MODEL_NAME,
            PYTORCH_INSTALL_COMMAND,
            pytorch_available,
            train_lstm_forecaster,
        )

        if not pytorch_available():
            raise RuntimeError(
                "LSTM training was requested, but PyTorch is not installed in the intership environment.\n"
                f"Run this command first:\n  {PYTORCH_INSTALL_COMMAND}"
            )
        lstm_prediction, lstm_metrics, lstm_rows = train_lstm_forecaster(
            data,
            model_output=model_dir / "local_pytorch_lstm.pt",
            window=lstm_window,
            epochs=lstm_epochs,
            batch_size=lstm_batch_size,
            hidden_size=lstm_hidden_size,
            patience=lstm_patience,
            seed=seed,
            show_batch_progress=show_lstm_batch_progress,
        )
        data["prediction_local_pytorch_lstm"] = lstm_prediction
        model_details[PYTORCH_LSTM_MODEL_NAME] = lstm_metrics
        available_models.append(PYTORCH_LSTM_MODEL_NAME)
        comparison["items"].append(
            {
                "model": PYTORCH_LSTM_MODEL_NAME,
                **{
                    key: lstm_metrics.get(key)
                    for key in ["mae", "rmse", "r2", "mape", "smape"]
                },
            }
        )
        gold_dir.mkdir(parents=True, exist_ok=True)
        lstm_rows.to_csv(gold_dir / "lstm_predictions.csv", index=False, encoding="utf-8-sig")

    valid_items = [
        item
        for item in comparison.get("items", [])
        if isinstance(item.get("mae"), (int, float)) and math.isfinite(float(item["mae"]))
    ]
    best_item = min(valid_items, key=lambda item: float(item["mae"])) if valid_items else {"model": MOVING_AVERAGE_MODEL, "mae": 0.0}
    best_model = str(best_item["model"])
    comparison["best_model"] = best_model

    best_prediction_column = f"prediction_{best_model}"
    if best_prediction_column in data.columns:
        data["prediction_t_plus_7"] = data[best_prediction_column].fillna(data["prediction_moving_average"])
    else:
        data["prediction_t_plus_7"] = data["prediction_moving_average"]

    baseline_details = {
        "model": best_model,
        "data_mode": "real_local_multi_source",
        **{key: best_item.get(key) for key in ["mae", "rmse", "r2", "mape", "smape"]},
        "scope": "COVID-19 daily t+7 test partition",
        "note": "Selected by lowest test MAE among the trained models and baselines.",
    }
    selected_metrics = dict(model_details.get(best_model, baseline_details))
    selected_metrics.update(
        {
            "model": best_model,
            "best_model": best_model,
            "data_mode": "real_local_multi_source",
            "mae": best_item.get("mae"),
            "rmse": best_item.get("rmse"),
            "r2": best_item.get("r2"),
            "mape": best_item.get("mape"),
            "smape": best_item.get("smape"),
            "models": model_details,
            "available_models": available_models,
        }
    )
    if show_progress:
        print(
            f"[MODEL] Best test MAE: {best_model} ({float(best_item.get('mae') or 0.0):.4f}); "
            f"available={','.join(available_models)}",
            flush=True,
        )
    return data, selected_metrics, comparison, available_models


def risk_level(score: float) -> str:
    if score < 35:
        return "低风险"
    if score < 55:
        return "中风险"
    if score < 75:
        return "较高风险"
    return "高风险"


def normalize(series: pd.Series) -> pd.Series:
    values = series.fillna(0.0).astype(float)
    low, high = values.min(), values.max()
    if len(values) == 0 or math.isclose(float(low), float(high)):
        return pd.Series(np.zeros(len(values)), index=series.index)
    return (values - low) / (high - low)


def build_risk_rows(features: pd.DataFrame) -> list[dict[str, Any]]:
    latest = features.sort_values("date").groupby(["location_code", "disease"], as_index=False).tail(1).copy()
    output: list[pd.DataFrame] = []
    for _, group in latest.groupby("disease", sort=False):
        group = group.copy()
        group["recent_cases_per_million"] = group["cases_per_million"].fillna(group["value"])
        group["forecast_cases"] = group["prediction_t_plus_7"].fillna(group["rolling_mean_7"]).fillna(group["value"])
        forecast_normalized = normalize(group["forecast_cases"])
        score = 100.0 * (
            0.55 * normalize(group["recent_cases_per_million"])
            + 0.25 * normalize(group["growth_rate_7"].clip(lower=0))
            + 0.20 * forecast_normalized
        )
        group["risk_score"] = score.round(2)
        group["risk_level"] = group["risk_score"].map(risk_level)
        output.append(group)
    risk = pd.concat(output, ignore_index=True, sort=False) if output else latest
    columns = [
        "date",
        "location",
        "location_code",
        "latitude",
        "longitude",
        "disease",
        "metric",
        "metric_label",
        "risk_score",
        "risk_level",
        "recent_cases_per_million",
        "growth_rate_7",
        "forecast_cases",
        "quality_flag",
    ]
    return risk[columns].sort_values(["disease", "risk_score"], ascending=[True, False]).to_dict("records")


def series_summaries(features: pd.DataFrame) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for (code, disease), group in features.groupby(["location_code", "disease"], sort=False):
        group = group.sort_values("date")
        latest = group.iloc[-1]
        summaries.append(
            {
                "location_code": code,
                "location": latest["location"],
                "disease": disease,
                "frequency": latest["frequency"],
                "metric": latest["metric"],
                "metric_label": latest["metric_label"],
                "rolling_label": latest["rolling_label"],
                "start_date": iso_date(group["date"].min()),
                "end_date": iso_date(group["date"].max()),
                "latest_date": iso_date(latest["date"]),
                "records": int(len(group)),
                "current_value": numeric_or_none(latest["value"]),
                "current_rolling_value": numeric_or_none(latest["rolling_mean_7"]),
                "current_total_cases": numeric_or_none(latest.get("total_cases")),
                "current_total_deaths": numeric_or_none(latest.get("total_deaths")),
                "weather_points": int(group["has_weather"].sum()),
                "source": latest["source"],
            }
        )
    return summaries


def build_source_status(quality_parts: dict[str, Any], generated_at: str) -> list[dict[str, Any]]:
    cdc_path = project_path("data", "raw", "china_cdc", "page_metadata.jsonl")
    cdc_rows = 0
    if cdc_path.exists():
        with cdc_path.open("r", encoding="utf-8") as handle:
            cdc_rows = sum(1 for line in handle if line.strip())
    who_files = list(project_path("data", "raw", "who").glob("*.csv"))
    historical_weather_root = project_path("data", "raw", "kaggle", "weather")
    historical_temperature = next(historical_weather_root.rglob("temperature.csv"), None)
    historical_weather_rows = 0
    if historical_temperature:
        with historical_temperature.open("r", encoding="utf-8-sig", errors="replace") as handle:
            historical_weather_rows = max(sum(1 for _ in handle) - 1, 0)
    items = [
        {"name": "OWID COVID-19 daily (primary)", "status": "ok", "updated_at": generated_at, "rows": quality_parts["owid"]["output_rows"]},
        {"name": "Kaggle COVID-19 (cross-check)", "status": "ok", "updated_at": generated_at, "rows": quality_parts["kaggle_covid"]["output_rows"]},
        {"name": "Kaggle Tuberculosis annual indicators", "status": "ok", "updated_at": generated_at, "rows": quality_parts["tuberculosis"]["output_rows"]},
        {"name": "US weekly respiratory hospital metrics", "status": "ok", "updated_at": generated_at, "rows": quality_parts["respiratory"]["output_rows"]},
        {"name": "Open-Meteo same-period daily weather", "status": "ok", "updated_at": generated_at, "rows": quality_parts["weather"]["output_rows"]},
        {"name": "World Bank + Kaggle population", "status": "ok", "updated_at": generated_at, "rows": quality_parts["population"]["output_rows"]},
        {"name": "China CDC pages (manual review metadata)", "status": "warn", "updated_at": generated_at, "rows": cdc_rows},
        {"name": "WHO indicators (not configured)", "status": "warn", "updated_at": generated_at, "rows": len(who_files)},
        {"name": "Kaggle 2012-2017 weather (not used for COVID)", "status": "warn", "updated_at": generated_at, "rows": historical_weather_rows},
    ]
    model_labels = {
        MODEL_NAME: "Local sklearn GBDT model",
        LSTM_MODEL_NAME: "Local PyTorch LSTM model",
    }
    for model_name, details in quality_parts.get("models", {}).items():
        if model_name not in model_labels:
            continue
        rows = int(details.get("train_rows", 0)) + int(details.get("validation_rows", 0)) + int(details.get("test_rows", 0))
        items.append(
            {
                "name": model_labels[model_name],
                "status": "ok" if details.get("status", "trained") == "trained" else "warn",
                "updated_at": generated_at,
                "rows": rows,
            }
        )
    return items


def export_serving(
    features: pd.DataFrame,
    metrics: dict[str, Any],
    comparison: dict[str, Any],
    quality_parts: dict[str, Any],
    serving_dir: Path,
    available_models: list[str],
) -> None:
    serving_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    features = features.sort_values(["location_code", "disease", "date"]).copy()
    features["prediction_error"] = features["prediction_t_plus_7"] - features["target_t_plus_7"]
    for model_name in available_models:
        prediction_column = f"prediction_{model_name}"
        if prediction_column in features.columns:
            features[f"prediction_error_{model_name}"] = features[prediction_column] - features["target_t_plus_7"]
    summaries = series_summaries(features)
    risk_rows = build_risk_rows(features)

    latest_covid = features[features["disease"].eq(COVID_DISEASE)].sort_values("date").groupby("location_code", as_index=False).tail(1)
    required_columns = ["date", "location_code", "disease", "frequency", "metric", "value"]
    required_completeness = 1.0 - float(features[required_columns].isna().mean().mean())
    overview = {
        "data_mode": "real_local_multi_source",
        "demo_mode": False,
        "last_update": generated_at,
        "latest_date": iso_date(features["date"].max()),
        "start_date": iso_date(features["date"].min()),
        "end_date": iso_date(features["date"].max()),
        "regions": int(features["location_code"].nunique()),
        "diseases": int(features["disease"].nunique()),
        "valid_records": int(len(features)),
        "current_total_cases": float(latest_covid["total_cases"].sum(min_count=1)) if latest_covid["total_cases"].notna().any() else None,
        "current_total_deaths": float(latest_covid["total_deaths"].sum(min_count=1)) if latest_covid["total_deaths"].notna().any() else None,
        "current_new_cases": float(latest_covid["value"].sum(min_count=1)) if not latest_covid.empty else None,
        "high_risk_regions": int(sum(1 for row in risk_rows if row["disease"] == COVID_DISEASE and row["risk_level"] == "高风险")),
        "best_model": comparison.get("best_model"),
        "best_model_mae": metrics.get("mae"),
        "data_completeness": round(required_completeness, 4),
        "series": summaries,
        "disclaimer": "真实公开数据的课程演示结果，不构成公共卫生决策或医疗建议。不同疾病保留各自统计口径。",
    }

    trend_items: list[dict[str, Any]] = []
    for (code, disease), group in features.groupby(["location_code", "disease"], sort=False):
        group = group.sort_values("date").tail(2500)
        points = []
        for row in group.to_dict("records"):
            prediction = numeric_or_none(row.get("prediction_t_plus_7"))
            point = {
                "date": iso_date(row["date"]),
                "actual": numeric_or_none(row.get("value")),
                "rolling_7": numeric_or_none(row.get("rolling_mean_7")),
                "prediction": prediction,
                "target_t_plus_7": numeric_or_none(row.get("target_t_plus_7")),
                "lower": max(0.0, prediction * 0.85) if prediction is not None else None,
                "upper": prediction * 1.15 if prediction is not None else None,
                "growth_rate_7": numeric_or_none(row.get("growth_rate_7")),
                "temperature_mean": numeric_or_none(row.get("temperature_mean")),
                "relative_humidity_mean": numeric_or_none(row.get("relative_humidity_mean")),
                "precipitation_sum": numeric_or_none(row.get("precipitation_sum")),
                "prediction_error": numeric_or_none(row.get("prediction_error")),
            }
            for model_name in available_models:
                prediction_column = f"prediction_{model_name}"
                if prediction_column in row:
                    point[prediction_column] = numeric_or_none(row.get(prediction_column))
            points.append(point)
        first = group.iloc[0]
        trend_items.append(
            {
                "location_code": code,
                "location": first["location"],
                "disease": disease,
                "frequency": first["frequency"],
                "metric": first["metric"],
                "metric_label": first["metric_label"],
                "rolling_label": first["rolling_label"],
                "forecast_horizon_label": first["forecast_horizon_label"],
                "source": first["source"],
                "points": points,
            }
        )

    model_predictions = features[
        features["model_eligible"] & features["target_t_plus_7"].notna()
    ].sort_values("date").tail(2000).copy()
    model_predictions["actual_t_plus_7"] = model_predictions["target_t_plus_7"]
    model_predictions["prediction"] = model_predictions["prediction_t_plus_7"]
    model_predictions["error"] = model_predictions["prediction_error"]
    prediction_columns = [
        "date",
        "location_code",
        "location",
        "disease",
        "actual_t_plus_7",
        "prediction",
        "error",
    ]
    prediction_columns.extend(
        f"prediction_{model_name}"
        for model_name in available_models
        if f"prediction_{model_name}" in model_predictions.columns
    )

    required_missing_rates = {column: round(float(features[column].isna().mean()), 6) for column in required_columns}
    optional_missing_rates = {
        column: round(float(features[column].isna().mean()), 6)
        for column in ["temperature_mean", "relative_humidity_mean", "population", "gdp_per_capita", "target_t_plus_7"]
    }
    data_quality = {
        "data_mode": "real_local_multi_source",
        "total_records": int(len(features)),
        "date_range": {"start": overview["start_date"], "end": overview["end_date"]},
        "region_count": overview["regions"],
        "disease_count": overview["diseases"],
        "required_missing_rate_by_column": required_missing_rates,
        "optional_missing_rate_by_column": optional_missing_rates,
        "missing_rate_by_column": required_missing_rates,
        "duplicate_count": int(features.duplicated(["location_code", "disease", "date"]).sum()),
        "negative_correction_count": int(features["is_negative_case_correction"].sum()),
        "outlier_count": 0,
        "weather_matched_count": quality_parts["features"]["weather_matched_rows"],
        "weather_unmatched_count": quality_parts["features"]["weather_unmatched_rows"],
        "population_unmatched_count": quality_parts["features"]["population_unmatched_rows"],
        "records_by_source": features.groupby("source").size().to_dict(),
        "latest_data_date": overview["latest_date"],
        "run_time": generated_at,
        "is_demo_data": False,
        "warnings": [
            "Windows local path uses pandas instead of Spark/HDFS.",
            "Open-Meteo uses representative-city weather as a country-level proxy.",
            "Tuberculosis is annual incidence per 100,000; respiratory data is weekly hospital admissions.",
            "Kaggle historical hourly weather is excluded because 2012-2017 does not overlap these epidemic series.",
            "China CDC HTML/PDF records remain manual-review metadata until a stable table parser is available.",
        ],
    }

    locations = (
        features[["location_code", "location", "latitude", "longitude"]]
        .drop_duplicates("location_code")
        .rename(columns={"location_code": "code", "location": "name"})
        .sort_values("code")
        .to_dict("records")
    )
    location_by_code = {row["code"]: row for row in locations}
    availability: dict[str, Any] = {}
    disease_names = [name for name in DISEASE_ORDER if name in set(features["disease"])]
    disease_names.extend(sorted(set(features["disease"]) - set(disease_names)))
    for disease in disease_names:
        subset = features[features["disease"].eq(disease)]
        codes = sorted(subset["location_code"].dropna().unique().tolist())
        first = subset.iloc[0]
        models = available_models if disease == COVID_DISEASE else ["naive_last_value", MOVING_AVERAGE_MODEL]
        availability[disease] = {
            "locations": [location_by_code[code] for code in codes if code in location_by_code],
            "date_range": {"start": iso_date(subset["date"].min()), "end": iso_date(subset["date"].max())},
            "frequency": first["frequency"],
            "metric": first["metric"],
            "metric_label": first["metric_label"],
            "models": models,
        }
    options = {
        "data_mode": "real_local_multi_source",
        "locations": locations,
        "diseases": disease_names,
        "models": available_models,
        "default_model": comparison.get("best_model", MOVING_AVERAGE_MODEL),
        "date_range": {"start": overview["start_date"], "end": overview["end_date"]},
        "availability": availability,
    }

    weather_sample = features[
        features["has_weather"] & features["temperature_mean"].notna() & features["relative_humidity_mean"].notna()
    ][
        [
            "date",
            "location_code",
            "location",
            "disease",
            "frequency",
            "metric",
            "metric_label",
            "temperature_mean",
            "relative_humidity_mean",
            "precipitation_sum",
            "new_cases_smoothed",
            "weather_match_level",
        ]
    ].sort_values(["disease", "location_code", "date"])
    disease_share = (
        features.groupby("disease", as_index=False)
        .agg(
            record_count=("value", "size"),
            location_count=("location_code", "nunique"),
            start_date=("date", "min"),
            end_date=("date", "max"),
        )
        .sort_values("disease")
        .to_dict("records")
    )

    source_status = build_source_status(quality_parts, generated_at)
    write_json(serving_dir / "metadata.json", {"data_mode": "real_local_multi_source", "generated_at": generated_at, "generator": "scripts/build_local_serving_from_raw.py"})
    write_json(serving_dir / "overview.json", overview)
    write_json(serving_dir / "trend.json", {"data_mode": "real_local_multi_source", "items": trend_items})
    write_json(serving_dir / "risk_map.json", {"data_mode": "real_local_multi_source", "date": overview["latest_date"], "items": risk_rows})
    write_json(
        serving_dir / "rankings.json",
        {
            "data_mode": "real_local_multi_source",
            "risk": sorted(risk_rows, key=lambda item: item.get("risk_score") or 0, reverse=True),
            "growth": sorted(risk_rows, key=lambda item: item.get("growth_rate_7") or 0, reverse=True),
            "forecast": sorted(risk_rows, key=lambda item: item.get("forecast_cases") or 0, reverse=True),
        },
    )
    write_json(serving_dir / "model_metrics.json", metrics)
    write_json(serving_dir / "model_comparison.json", comparison)
    for model_name, model_metrics in metrics.get("models", {}).items():
        write_json(serving_dir / f"{model_name}_metrics.json", model_metrics)
    write_json(serving_dir / "predictions.json", {"data_mode": "real_local_multi_source", "items": model_predictions[prediction_columns].to_dict("records")})
    write_json(serving_dir / "data_quality_report.json", data_quality)
    write_json(serving_dir / "options.json", options)
    write_json(serving_dir / "source_status.json", {"data_mode": "real_local_multi_source", "items": source_status})
    write_json(serving_dir / "weather_correlation.json", {"data_mode": "real_local_multi_source", "items": weather_sample.to_dict("records")})
    write_json(serving_dir / "disease_share.json", {"data_mode": "real_local_multi_source", "items": disease_share})
    write_json(serving_dir / "local_real_pipeline_manifest.json", quality_parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Flask serving JSON from multiple real local public datasets without Spark/HDFS.")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--serving-dir", default=None)
    parser.add_argument("--silver-dir", default="data/silver/local")
    parser.add_argument("--gold-dir", default="data/gold/local")
    parser.add_argument("--model-dir", default="data/models/local")
    parser.add_argument("--lstm", action="store_true", help="Train the optional real-data PyTorch LSTM and export it to Flask serving.")
    parser.add_argument("--lstm-window", type=int, default=28)
    parser.add_argument("--lstm-epochs", type=int, default=20)
    parser.add_argument("--lstm-batch-size", type=int, default=128)
    parser.add_argument("--lstm-hidden-size", type=int, default=32)
    parser.add_argument("--lstm-patience", type=int, default=5)
    parser.add_argument("--lstm-no-batch-progress", action="store_true")
    parser.add_argument("--print-json", action="store_true", help="Print the full manifest JSON after the concise summary.")
    parser.add_argument("--no-progress", action="store_true", help="Disable step progress output.")
    args = parser.parse_args()
    progress = PipelineProgress(total=12, enabled=not args.no_progress)

    if args.lstm:
        from src.models.lstm_optional import PYTORCH_INSTALL_COMMAND, pytorch_available

        if not pytorch_available():
            raise SystemExit(
                "LSTM was requested, but PyTorch is not installed in the intership environment.\n"
                f"Install it first:\n  {PYTORCH_INSTALL_COMMAND}"
            )

    progress.start("Load config, country scope and source paths")
    settings = load_settings(project_path(args.config))
    selected_codes = {str(code).upper() for code in get_setting(settings, "collectors.countries", [])}
    selected_codes.add("USA")
    start_date = str(get_setting(settings, "collectors.start_date", "2020-01-01"))
    end_date = str(get_setting(settings, "collectors.end_date", "2025-12-31"))
    mapping = read_country_mapping()
    location_catalog = read_location_catalog(project_path(get_setting(settings, "paths.weather_locations", "config/weather_locations.csv")))
    owid_path = resolve_latest_csv(project_path(get_setting(settings, "paths.owid_raw", "data/raw/owid")), "owid*.csv")
    kaggle_covid_path = project_path(get_setting(settings, "paths.epidemic_raw"))
    tuberculosis_root = project_path(get_setting(settings, "paths.tuberculosis_raw", "data/raw/kaggle/epidemic/Tuberculosis"))
    respiratory_path = resolve_latest_csv(project_path(get_setting(settings, "paths.respiratory_raw", "data/raw/kaggle/epidemic/Weekly Hospital Respiratory Data and Metrics")))
    kaggle_population_path = project_path(get_setting(settings, "paths.population_raw"))
    world_bank_root = project_path(get_setting(settings, "paths.world_bank_raw", "data/raw/world_bank"))
    world_bank_path = resolve_latest_csv(world_bank_root, "world_bank*.csv") if world_bank_root.exists() else None
    weather_root = project_path(get_setting(settings, "paths.weather_raw"))
    serving_dir = project_path(args.serving_dir or get_setting(settings, "paths.serving", "data/serving"))
    silver_dir = project_path(args.silver_dir)
    gold_dir = project_path(args.gold_dir)
    model_dir = project_path(args.model_dir)
    seed = int(get_setting(settings, "model.random_seed", 2026))
    progress.done(f"countries={','.join(sorted(selected_codes))}, dates={start_date}..{end_date}")

    progress.start("Clean OWID COVID-19 daily data (primary)")
    owid, owid_quality = clean_owid(owid_path, selected_codes, start_date, end_date)
    progress.done(f"rows={owid_quality['output_rows']}, countries={owid_quality['country_count']}, date={owid_quality['date_min']}..{owid_quality['date_max']}")

    progress.start("Clean Kaggle COVID-19 data (cross-check only)")
    kaggle_covid, kaggle_quality = clean_kaggle_covid_validation(kaggle_covid_path, mapping, selected_codes)
    covid_validation = compare_covid_sources(owid, kaggle_covid)
    progress.done(f"rows={kaggle_quality['output_rows']}, overlap={covid_validation['overlap_rows']}")

    progress.start("Clean six Tuberculosis annual indicator files")
    tuberculosis, tuberculosis_quality = clean_tuberculosis(tuberculosis_root, selected_codes)
    progress.done(f"rows={tuberculosis_quality['output_rows']}, countries={tuberculosis_quality['country_count']}, years={tuberculosis_quality['year_min']}..{tuberculosis_quality['year_max']}")

    progress.start("Clean US weekly respiratory hospital data")
    respiratory, respiratory_wide, respiratory_quality = clean_respiratory(respiratory_path, selected_codes)
    progress.done(f"rows={respiratory_quality['output_rows']}, series={','.join(respiratory_quality['disease_rows'].keys())}")

    progress.start("Combine World Bank and Kaggle population data")
    population, population_quality = clean_population(kaggle_population_path, world_bank_path, selected_codes)
    progress.done(f"rows={population_quality['output_rows']}, countries={population_quality['country_count']}")

    progress.start("Clean same-period Open-Meteo weather data")
    weather, weather_quality = clean_weather(weather_root, selected_codes)
    progress.done(f"rows={weather_quality['output_rows']}, countries={weather_quality['country_count']}")

    progress.start("Build canonical multi-disease observation table")
    observations = pd.concat([owid, tuberculosis, respiratory], ignore_index=True, sort=False)
    observations = observations.drop_duplicates(["location_code", "disease", "date"], keep="last")
    progress.done(f"rows={len(observations)}, diseases={observations['disease'].nunique()}, countries={observations['location_code'].nunique()}")

    progress.start("Join weather and socioeconomic context without dropping epidemics")
    features, feature_quality = build_features(observations, weather, population, location_catalog)
    progress.done(f"rows={feature_quality['feature_rows']}, weather_matches={feature_quality['weather_matched_rows']}")

    progress.start("Train COVID daily GBDT/LSTM models and frequency-aware baselines")
    features, gbdt_metrics, comparison = fit_predict(
        features,
        seed,
        model_dir=model_dir,
        show_progress=not args.no_progress,
    )
    features, metrics, comparison, available_models = complete_model_training(
        features,
        gbdt_metrics,
        comparison,
        enable_lstm=args.lstm,
        model_dir=model_dir,
        gold_dir=gold_dir,
        lstm_window=args.lstm_window,
        lstm_epochs=args.lstm_epochs,
        lstm_batch_size=args.lstm_batch_size,
        lstm_hidden_size=args.lstm_hidden_size,
        lstm_patience=args.lstm_patience,
        seed=seed,
        show_progress=not args.no_progress,
        show_lstm_batch_progress=not args.lstm_no_batch_progress and not args.no_progress,
    )
    progress.done(
        f"trained={','.join(model for model in available_models if model not in {'naive_last_value', MOVING_AVERAGE_MODEL})}, "
        f"best={comparison.get('best_model')}, mae={metrics.get('mae')}"
    )

    progress.start("Write local Silver and Gold CSV outputs")
    silver_dir.mkdir(parents=True, exist_ok=True)
    gold_dir.mkdir(parents=True, exist_ok=True)
    owid.to_csv(silver_dir / "epidemic_daily_clean.csv", index=False, encoding="utf-8-sig")
    owid.to_csv(silver_dir / "owid_covid_daily_clean.csv", index=False, encoding="utf-8-sig")
    kaggle_covid.to_csv(silver_dir / "kaggle_covid_validation_clean.csv", index=False, encoding="utf-8-sig")
    tuberculosis.to_csv(silver_dir / "tuberculosis_annual_clean.csv", index=False, encoding="utf-8-sig")
    respiratory.to_csv(silver_dir / "respiratory_observations_clean.csv", index=False, encoding="utf-8-sig")
    respiratory_wide.to_csv(silver_dir / "respiratory_weekly_clean.csv", index=False, encoding="utf-8-sig")
    observations.to_csv(silver_dir / "epidemic_observations_clean.csv", index=False, encoding="utf-8-sig")
    population.to_csv(silver_dir / "population_yearly_clean.csv", index=False, encoding="utf-8-sig")
    weather.to_csv(silver_dir / "weather_daily_clean.csv", index=False, encoding="utf-8-sig")
    features.to_csv(gold_dir / "forecast_features.csv", index=False, encoding="utf-8-sig")
    progress.done(f"silver={safe_relative(silver_dir)}, gold={safe_relative(gold_dir)}")

    quality_parts = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "real_local_multi_source",
        "country_scope": sorted(selected_codes),
        "epidemic_date_scope": {"start": start_date, "end": end_date},
        "owid": owid_quality,
        "kaggle_covid": kaggle_quality,
        "covid_source_validation": covid_validation,
        "tuberculosis": tuberculosis_quality,
        "respiratory": respiratory_quality,
        "population": population_quality,
        "weather": weather_quality,
        "features": feature_quality,
        "models": metrics.get("models", {}),
        "available_models": available_models,
        "source_decisions": {
            "primary_covid": "OWID compact daily table",
            "kaggle_covid": "cross-check only to prevent duplicate COVID rows",
            "tuberculosis": "annual incidence per 100,000; auxiliary death/detection/treatment/HIV fields retained",
            "respiratory": "provided USA national weekly row; state rows are not re-summed",
            "historical_kaggle_weather": "excluded because 2012-2017 has no date overlap",
            "china_cdc": "metadata/manual review only because current pages and PDFs are not a stable numeric table",
            "who": "not used because no indicators/files are configured",
        },
        "outputs": {
            "silver_dir": safe_relative(silver_dir),
            "gold_dir": safe_relative(gold_dir),
            "model_dir": safe_relative(model_dir),
            "serving_dir": safe_relative(serving_dir),
        },
    }

    progress.start("Export Flask serving JSON files")
    export_serving(features, metrics, comparison, quality_parts, serving_dir, available_models)
    progress.done(f"serving={safe_relative(serving_dir)}, mode=real_local_multi_source")
    progress.finish("refresh http://127.0.0.1:5000 after Flask starts")

    print("\nSummary:")
    print("  mode: real_local_multi_source")
    print(f"  diseases: {', '.join([name for name in DISEASE_ORDER if name in set(features['disease'])])}")
    print(f"  observation rows: {len(observations)}")
    print(f"  weather matched rows: {feature_quality['weather_matched_rows']} (unmatched rows were retained)")
    print(f"  best COVID daily model: {comparison.get('best_model')}")
    print(f"  trained model options: {', '.join(available_models)}")
    print(f"  model dir: {safe_relative(model_dir)}")
    print(f"  serving dir: {safe_relative(serving_dir)}")
    print("  full report: data/serving/local_real_pipeline_manifest.json")
    if args.print_json:
        print(json.dumps(to_jsonable(quality_parts), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
