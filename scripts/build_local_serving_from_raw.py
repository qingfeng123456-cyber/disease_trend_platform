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
HIV_DISEASE = "HIV/AIDS"
DISEASE_ORDER = [
    COVID_DISEASE,
    INFLUENZA_DISEASE,
    RSV_DISEASE,
    TUBERCULOSIS_DISEASE,
    HIV_DISEASE,
    COVID_HOSPITAL_DISEASE,
]

MODEL_NAME = "local_sklearn_gbdt"
LSTM_MODEL_NAME = "local_pytorch_lstm"
MOVING_AVERAGE_MODEL = "moving_average"
BASELINE_MODEL = MOVING_AVERAGE_MODEL
MODEL_OPTIONS = ["naive_last_value", MOVING_AVERAGE_MODEL, MODEL_NAME]
ISO3_PATTERN = re.compile(r"^[A-Z]{3}$")
WHO_HIV_PRIMARY_INDICATOR = "HIV_0000000026"
WHO_HIV_PREVALENCE_INDICATOR = "MDG_0000000029"
WHO_TB_AUXILIARY_INDICATORS = {
    "MDG_0000000017": "who_tb_deaths_rate_per_100k",
    "TB_1": "who_tb_treatment_coverage_percent",
    "TB_c_newinc": "who_tb_new_relapse_cases",
}

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


def _annual_city_metric(
    path: Path,
    city_columns: list[str],
    *,
    value_name: str,
    value_offset: float = 0.0,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    yearly: dict[int, dict[str, float]] = {}
    input_rows = 0
    date_min: pd.Timestamp | None = None
    date_max: pd.Timestamp | None = None
    for chunk in pd.read_csv(path, usecols=["datetime", *city_columns], chunksize=5000):
        dates = pd.to_datetime(chunk.pop("datetime"), errors="coerce")
        values = chunk.apply(pd.to_numeric, errors="coerce")
        input_rows += len(values)
        valid_dates = dates.dropna()
        if not valid_dates.empty:
            chunk_min = valid_dates.min()
            chunk_max = valid_dates.max()
            date_min = chunk_min if date_min is None else min(date_min, chunk_min)
            date_max = chunk_max if date_max is None else max(date_max, chunk_max)
        for year in sorted(valid_dates.dt.year.unique()):
            year_values = values.loc[dates.dt.year.eq(year)].to_numpy(dtype=float)
            valid = year_values[np.isfinite(year_values)]
            if not len(valid):
                continue
            bucket = yearly.setdefault(int(year), {"sum": 0.0, "count": 0.0, "min": math.inf, "max": -math.inf})
            bucket["sum"] += float(valid.sum())
            bucket["count"] += float(len(valid))
            bucket["min"] = min(bucket["min"], float(valid.min()))
            bucket["max"] = max(bucket["max"], float(valid.max()))

    rows = []
    for year, bucket in sorted(yearly.items()):
        rows.append(
            {
                "year": year,
                value_name: bucket["sum"] / bucket["count"] + value_offset,
                f"{value_name}_observations": int(bucket["count"]),
            }
        )
    quality = {
        "input_path": safe_relative(path),
        "input_rows": input_rows,
        "date_min": iso_date(date_min),
        "date_max": iso_date(date_max),
        "non_null_observations": int(sum(bucket["count"] for bucket in yearly.values())),
    }
    return pd.DataFrame(rows), quality


def clean_historical_weather(
    weather_root: Path,
    selected_codes: set[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    city_path = weather_root / "city_attributes.csv"
    metric_specs = {
        "temperature.csv": ("temperature_mean", -273.15),
        "humidity.csv": ("relative_humidity_mean", 0.0),
        "pressure.csv": ("pressure_mean_hpa", 0.0),
        "wind_speed.csv": ("wind_speed_mean", 0.0),
    }
    required_paths = [city_path, *(weather_root / name for name in metric_specs)]
    missing_files = [safe_relative(path) for path in required_paths if not path.exists()]
    if missing_files:
        quality = {
            "input_root": safe_relative(weather_root),
            "status": "missing",
            "missing_files": missing_files,
            "input_rows": 0,
            "output_rows": 0,
            "country_count": 0,
        }
        return pd.DataFrame(), quality

    cities = pd.read_csv(city_path)
    supported_country_codes = {"United States": "USA"}
    cities["location_code"] = cities["Country"].map(supported_country_codes)
    cities = cities[cities["location_code"].isin(selected_codes)].copy()
    if cities.empty:
        quality = {
            "input_root": safe_relative(weather_root),
            "status": "no_selected_country",
            "input_rows": 0,
            "output_rows": 0,
            "country_count": 0,
            "available_countries": sorted(pd.read_csv(city_path)["Country"].dropna().unique().tolist()),
        }
        return pd.DataFrame(), quality

    country_frames: list[pd.DataFrame] = []
    metric_quality: dict[str, Any] = {}
    raw_rows = 0
    for country_code, country_cities in cities.groupby("location_code", sort=True):
        city_columns = country_cities["City"].dropna().astype(str).tolist()
        annual: pd.DataFrame | None = None
        for file_name, (value_name, offset) in metric_specs.items():
            metric_frame, metric_profile = _annual_city_metric(
                weather_root / file_name,
                city_columns,
                value_name=value_name,
                value_offset=offset,
            )
            raw_rows = max(raw_rows, int(metric_profile["input_rows"]))
            metric_quality[file_name] = metric_profile
            annual = metric_frame if annual is None else annual.merge(metric_frame, on="year", how="outer")
        if annual is None or annual.empty:
            continue
        annual["date"] = pd.to_datetime(annual["year"].astype("Int64").astype(str) + "-12-31", errors="coerce")
        annual["location_code"] = country_code
        annual["location"] = "United States" if country_code == "USA" else country_code
        annual["city_count"] = len(city_columns)
        annual["temperature_max"] = np.nan
        annual["temperature_min"] = np.nan
        annual["precipitation_sum"] = np.nan
        annual["wind_speed_max"] = np.nan
        annual["weather_match_level"] = "historical_hourly_annual_city_mean"
        annual["source"] = "Kaggle historical hourly weather (annual city mean)"
        country_frames.append(annual)

    cleaned = pd.concat(country_frames, ignore_index=True, sort=False) if country_frames else pd.DataFrame()
    if not cleaned.empty:
        cleaned = cleaned.sort_values(["location_code", "year"]).drop_duplicates(["location_code", "year"], keep="last")
    quality = {
        "input_root": safe_relative(weather_root),
        "status": "cleaned" if not cleaned.empty else "empty",
        "input_rows": raw_rows,
        "output_rows": len(cleaned),
        "country_count": int(cleaned["location_code"].nunique()) if not cleaned.empty else 0,
        "city_count": int(cities["City"].nunique()),
        "date_min": iso_date(cleaned["date"].min()) if not cleaned.empty else None,
        "date_max": iso_date(cleaned["date"].max()) if not cleaned.empty else None,
        "temperature_input_unit": "Kelvin",
        "temperature_output_unit": "Celsius",
        "humidity_unit": "percent",
        "usage": "USA annual weather enrichment for same-year Tuberculosis observations; never joined to COVID dates.",
        "metric_profiles": metric_quality,
    }
    return cleaned, quality


def _cdc_report_category(title: str) -> str:
    if "流感监测周报" in title:
        return "Influenza surveillance"
    if "急性呼吸道传染病" in title:
        return "Respiratory pathogen surveillance"
    if "法定传染病" in title:
        return "Notifiable infectious diseases"
    if "新型冠状病毒" in title:
        return "COVID-19 surveillance"
    return "Other China CDC report"


def _cdc_optional_number(text: str, pattern: str, *, as_float: bool = False) -> float | int | None:
    match = re.search(pattern, text)
    if not match:
        return None
    return float(match.group(1)) if as_float else int(match.group(1))


def clean_china_cdc_metadata(cdc_root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    metadata_path = cdc_root / "page_metadata.jsonl"
    if not metadata_path.exists():
        return pd.DataFrame(), {
            "input_path": safe_relative(metadata_path),
            "status": "missing",
            "input_rows": 0,
            "output_rows": 0,
        }

    records: list[dict[str, Any]] = []
    invalid_json_rows = 0
    with metadata_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                invalid_json_rows += 1
                continue
            record["source_line_number"] = line_number
            records.append(record)
    if not records:
        return pd.DataFrame(), {
            "input_path": safe_relative(metadata_path),
            "status": "empty",
            "input_rows": 0,
            "output_rows": 0,
            "invalid_json_rows": invalid_json_rows,
        }

    raw = pd.DataFrame(records)
    raw["downloaded_at_parsed"] = pd.to_datetime(raw.get("downloaded_at"), errors="coerce", utc=True)
    raw = raw.sort_values(["page_url", "downloaded_at_parsed", "source_line_number"])
    duplicate_url_rows = int(raw.duplicated("page_url", keep="last").sum())
    raw = raw.drop_duplicates("page_url", keep="last").copy()

    cleaned_rows: list[dict[str, Any]] = []
    for row in raw.to_dict("records"):
        report_title = str(row.get("anchor_title") or row.get("title") or "").strip()
        text_preview = str(row.get("text_preview") or "")
        title_and_text = f"{report_title}\n{text_preview}"
        week_match = re.search(r"(20\d{2})年第\s*(\d{1,2})\s*周", title_and_text)
        month_match = re.search(r"(20\d{2})年\s*(\d{1,2})\s*月", report_title)
        report_year = int(week_match.group(1)) if week_match else (int(month_match.group(1)) if month_match else None)
        report_week = int(week_match.group(2)) if week_match else None
        report_month = int(month_match.group(2)) if month_match else None
        local_html_path = str(row.get("local_html_path") or "")
        attachment_urls = row.get("attachment_urls") if isinstance(row.get("attachment_urls"), list) else []
        local_attachment_paths = row.get("local_attachment_paths") if isinstance(row.get("local_attachment_paths"), list) else []

        def local_file_exists(relative_path: str) -> bool:
            normalized = relative_path.replace("\\", os.sep).replace("/", os.sep)
            return bool(relative_path) and (cdc_root / normalized).is_file()

        existing_attachments = sum(local_file_exists(str(path)) for path in local_attachment_paths)
        category = _cdc_report_category(report_title)
        cleaned_rows.append(
            {
                "page_url": row.get("page_url"),
                "report_title": report_title,
                "report_category": category,
                "disease": "Influenza" if category == "Influenza surveillance" else None,
                "record_role": "listing" if str(row.get("page_url") or "").endswith("/") else "detail",
                "published_date": pd.to_datetime(row.get("published_date"), errors="coerce"),
                "report_year": report_year,
                "report_week": report_week,
                "report_month": report_month,
                "stat_period": f"{report_year}-W{report_week:02d}" if report_year and report_week else (f"{report_year}-{report_month:02d}" if report_year and report_month else None),
                "reported_ili_outbreaks": _cdc_optional_number(title_and_text, r"全国共报告\s*(\d+)\s*起流感样病例暴发疫情"),
                "south_ili_percent": _cdc_optional_number(title_and_text, r"南方省份哨点医院报告的ILI%为\s*(\d+(?:\.\d+)?)%", as_float=True),
                "north_ili_percent": _cdc_optional_number(title_and_text, r"北方省份哨点医院报告的ILI%为\s*(\d+(?:\.\d+)?)%", as_float=True),
                "influenza_samples_tested": _cdc_optional_number(title_and_text, r"共检测流感样病例监测标本\s*(\d+)\s*份"),
                "attachment_url_count": len(attachment_urls),
                "local_attachment_count": len(local_attachment_paths),
                "existing_attachment_count": existing_attachments,
                "attachments_complete": existing_attachments == len(local_attachment_paths) == len(attachment_urls),
                "local_html_path": local_html_path,
                "local_html_exists": local_file_exists(local_html_path),
                "attachment_urls_json": json.dumps(attachment_urls, ensure_ascii=False),
                "local_attachment_paths_json": json.dumps(local_attachment_paths, ensure_ascii=False),
                "text_preview": text_preview,
                "downloaded_at": row.get("downloaded_at"),
                "source_line_number": row.get("source_line_number"),
                "numeric_extraction_status": "summary_text_only" if category == "Influenza surveillance" else "metadata_only",
            }
        )

    cleaned = pd.DataFrame(cleaned_rows).sort_values(["published_date", "report_title"], ascending=[False, True])
    summary_columns = ["reported_ili_outbreaks", "south_ili_percent", "north_ili_percent", "influenza_samples_tested"]
    quality = {
        "input_path": safe_relative(metadata_path),
        "status": "cleaned_metadata",
        "input_rows": len(records),
        "output_rows": len(cleaned),
        "invalid_json_rows": invalid_json_rows,
        "duplicate_url_rows": duplicate_url_rows,
        "detail_rows": int(cleaned["record_role"].eq("detail").sum()),
        "category_rows": cleaned.groupby("report_category").size().to_dict(),
        "report_week_min": int(cleaned["report_week"].min()) if cleaned["report_week"].notna().any() else None,
        "report_week_max": int(cleaned["report_week"].max()) if cleaned["report_week"].notna().any() else None,
        "local_html_missing_rows": int((~cleaned["local_html_exists"]).sum()),
        "local_attachment_missing_count": int((cleaned["local_attachment_count"] - cleaned["existing_attachment_count"]).clip(lower=0).sum()),
        "high_confidence_summary_rows": int(cleaned[summary_columns].notna().any(axis=1).sum()),
        "usage": "Clean report index and high-confidence summary fields; raw HTML/PDF remains unchanged and PDF tables are not used as model targets.",
    }
    return cleaned, quality


def _who_file_descriptor(path: Path) -> tuple[str, str, str]:
    match = re.match(
        r"^who_(covid|influenza|tuberculosis|hiv)_(.+)_(\d{8}T\d{6}Z)\.csv$",
        path.name,
        flags=re.IGNORECASE,
    )
    if not match:
        return "unknown", path.stem, ""
    return match.group(1).lower(), match.group(2), match.group(3)


def _parse_who_raw_dimensions(value: Any) -> dict[str, Any]:
    result = {
        "who_record_id": None,
        "parent_location_code": None,
        "parent_location_name": None,
        "dimension_1_type": None,
        "dimension_1_value": None,
        "dimension_2_type": None,
        "dimension_2_value": None,
        "dimension_3_type": None,
        "dimension_3_value": None,
        "data_source_dimension_type": None,
        "data_source_dimension_value": None,
        "who_record_updated_at": None,
        "who_comments": None,
        "raw_json_valid": False,
    }
    if value is None or pd.isna(value):
        return result
    try:
        payload = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return result
    if not isinstance(payload, dict):
        return result
    result.update(
        {
            "who_record_id": payload.get("Id"),
            "parent_location_code": payload.get("ParentLocationCode"),
            "parent_location_name": payload.get("ParentLocation"),
            "dimension_1_type": payload.get("Dim1Type"),
            "dimension_1_value": payload.get("Dim1"),
            "dimension_2_type": payload.get("Dim2Type"),
            "dimension_2_value": payload.get("Dim2"),
            "dimension_3_type": payload.get("Dim3Type"),
            "dimension_3_value": payload.get("Dim3"),
            "data_source_dimension_type": payload.get("DataSourceDimType"),
            "data_source_dimension_value": payload.get("DataSourceDim"),
            "who_record_updated_at": payload.get("Date"),
            "who_comments": payload.get("Comments"),
            "raw_json_valid": True,
        }
    )
    return result


def _infer_who_unit(indicator_name: str) -> str:
    name = indicator_name.lower()
    if "per 100 000" in name or "per 100,000" in name:
        return "per_100k"
    if "percent" in name or "percentage" in name or "(%)" in name:
        return "percent"
    if "number" in name or "number of" in name or "cases" in name or "diagnosis" in name:
        return "count"
    if "rate" in name:
        return "rate"
    return "unspecified"


def _who_topic_matches(topic: str, indicator_name: str, indicator_code: str = "") -> bool:
    normalized_code = indicator_code.upper()
    if topic == "hiv" and normalized_code.startswith("HIV_"):
        return True
    if topic == "tuberculosis" and normalized_code.startswith("TB_"):
        return True
    patterns = {
        "covid": r"\bcovid(?:-19)?\b|\bcoronavirus\b|\bsars-cov-2\b",
        "influenza": r"\binfluenza\b|\bseasonal flu\b",
        "tuberculosis": r"\btuberculosis\b|\btb\b",
        "hiv": r"\bhiv\b|\baids\b",
    }
    pattern = patterns.get(topic)
    return bool(pattern and re.search(pattern, indicator_name.lower()))


def _who_usage_class(topic: str, indicator_code: str, indicator_name: str) -> str:
    if indicator_code == WHO_HIV_PRIMARY_INDICATOR:
        return "primary_hiv_observation"
    if indicator_code == WHO_HIV_PREVALENCE_INDICATOR or indicator_code in WHO_TB_AUXILIARY_INDICATORS:
        return "auxiliary_feature"
    if indicator_code.upper().startswith("PRISON_"):
        return "special_population_reference"
    if topic != "unknown" and not _who_topic_matches(topic, indicator_name, indicator_code):
        return "keyword_false_positive"
    return "catalog_only"


def clean_who(
    who_root: Path,
    selected_codes: set[str],
    location_catalog: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    all_files = sorted(who_root.rglob("*.csv")) if who_root.exists() else []
    if not all_files:
        quality = {
            "status": "missing",
            "input_root": safe_relative(who_root),
            "input_files": 0,
            "input_rows": 0,
            "output_rows": 0,
            "hiv_observation_rows": 0,
            "tb_auxiliary_rows": 0,
        }
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), quality

    latest_files: dict[tuple[str, str], tuple[str, Path]] = {}
    unmatched_files: list[Path] = []
    for path in all_files:
        topic, indicator_from_name, stamp = _who_file_descriptor(path)
        if topic == "unknown":
            unmatched_files.append(path)
            continue
        key = (topic, indicator_from_name)
        current = latest_files.get(key)
        if current is None or stamp >= current[0]:
            latest_files[key] = (stamp, path)
    files = sorted([item[1] for item in latest_files.values()] + unmatched_files)

    expected_columns = [
        "source",
        "endpoint",
        "indicator_code",
        "indicator_name",
        "location_code",
        "location_name",
        "location_type",
        "year",
        "value",
        "numeric_value",
        "low",
        "high",
        "unit",
        "sex",
        "age",
        "publish_state",
        "raw_json",
    ]
    frames: list[pd.DataFrame] = []
    file_rows_by_topic: dict[str, int] = {}
    empty_files: list[str] = []
    schema_error_files: list[str] = []
    false_keyword_files: set[str] = set()
    invalid_raw_json_rows = 0

    for path in files:
        topic, indicator_from_name, _ = _who_file_descriptor(path)
        available = pd.read_csv(path, nrows=0).columns.tolist()
        missing_columns = [column for column in expected_columns if column not in available]
        if missing_columns:
            schema_error_files.append(path.name)
            continue
        frame = pd.read_csv(path, usecols=expected_columns, low_memory=False)
        file_rows_by_topic[topic] = file_rows_by_topic.get(topic, 0) + len(frame)
        if frame.empty:
            empty_files.append(path.name)
            continue

        frame["source_file"] = safe_relative(path)
        frame["collector_topic"] = topic
        frame["indicator_code"] = frame["indicator_code"].fillna(indicator_from_name).astype(str).str.strip()
        frame["indicator_name"] = frame["indicator_name"].fillna("").astype(str).str.strip()
        raw_details = pd.DataFrame(
            frame["raw_json"].map(_parse_who_raw_dimensions).tolist(),
            index=frame.index,
        )
        invalid_raw_json_rows += int((~raw_details["raw_json_valid"]).sum())
        frame = pd.concat([frame.drop(columns="raw_json"), raw_details], axis=1)
        frame["location_code"] = frame["location_code"].astype("string").str.upper().str.strip()
        frame["location_type"] = frame["location_type"].astype("string").str.upper().str.strip()
        frame["year"] = pd.to_numeric(frame["year"], errors="coerce").astype("Int64")
        frame["date"] = pd.to_datetime(frame["year"].astype("string") + "-12-31", errors="coerce")
        frame["numeric_value_clean"] = pd.to_numeric(frame["numeric_value"], errors="coerce").combine_first(
            pd.to_numeric(frame["value"], errors="coerce")
        )
        frame["low"] = pd.to_numeric(frame["low"], errors="coerce")
        frame["high"] = pd.to_numeric(frame["high"], errors="coerce")
        inferred_units = frame["indicator_name"].map(_infer_who_unit)
        frame["unit"] = frame["unit"].where(frame["unit"].notna(), inferred_units)
        explicit_units = {
            WHO_HIV_PRIMARY_INDICATOR: "count",
            WHO_HIV_PREVALENCE_INDICATOR: "percent",
            "MDG_0000000017": "per_100k",
            "TB_1": "percent",
            "TB_c_newinc": "count",
        }
        explicit_unit_values = frame["indicator_code"].map(explicit_units)
        frame["unit"] = frame["unit"].where(explicit_unit_values.isna(), explicit_unit_values)
        for column in [
            "sex",
            "age",
            "dimension_1_type",
            "dimension_1_value",
            "dimension_2_type",
            "dimension_2_value",
            "dimension_3_type",
            "dimension_3_value",
        ]:
            frame[column] = frame[column].astype("string")

        for index in range(1, 4):
            type_column = f"dimension_{index}_type"
            value_column = f"dimension_{index}_value"
            sex_mask = frame["sex"].isna() & frame[type_column].astype("string").str.upper().eq("SEX")
            age_mask = frame["age"].isna() & frame[type_column].astype("string").str.upper().eq("AGEGROUP")
            frame.loc[sex_mask, "sex"] = frame.loc[sex_mask, value_column]
            frame.loc[age_mask, "age"] = frame.loc[age_mask, value_column]

        frame["is_selected_country"] = frame["location_type"].eq("COUNTRY") & frame["location_code"].isin(
            selected_codes
        )
        frame["collector_topic_match"] = [
            _who_topic_matches(topic, name, code)
            for code, name in zip(frame["indicator_code"].astype(str), frame["indicator_name"].astype(str))
        ]
        frame["usage_class"] = [
            _who_usage_class(topic, code, name)
            for code, name in zip(frame["indicator_code"].astype(str), frame["indicator_name"].astype(str))
        ]
        frame["quality_flag"] = np.select(
            [
                frame["year"].isna(),
                frame["year"].gt(datetime.now().year),
                frame["usage_class"].eq("keyword_false_positive"),
                frame["numeric_value_clean"].isna(),
            ],
            ["invalid_year", "future_year", "keyword_false_positive", "non_numeric_reference"],
            default="ok",
        )
        if frame["usage_class"].eq("keyword_false_positive").any():
            false_keyword_files.add(path.name)
        frames.append(frame)

    if not frames:
        quality = {
            "status": "empty",
            "input_root": safe_relative(who_root),
            "input_files": len(all_files),
            "processed_latest_files": len(files),
            "input_rows": 0,
            "output_rows": 0,
            "schema_error_files": schema_error_files,
            "hiv_observation_rows": 0,
            "tb_auxiliary_rows": 0,
        }
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), quality

    catalog = pd.concat(frames, ignore_index=True, sort=False)
    input_rows = len(catalog)
    fallback_key_columns = [
        "indicator_code",
        "location_type",
        "location_code",
        "year",
        "dimension_1_type",
        "dimension_1_value",
        "dimension_2_type",
        "dimension_2_value",
        "dimension_3_type",
        "dimension_3_value",
        "numeric_value_clean",
        "value",
    ]
    catalog["_dedup_key"] = catalog[fallback_key_columns].astype("string").fillna("").agg("|".join, axis=1)
    record_id_mask = catalog["who_record_id"].notna()
    catalog.loc[record_id_mask, "_dedup_key"] = (
        catalog.loc[record_id_mask, "indicator_code"].astype(str)
        + "|id:"
        + pd.to_numeric(catalog.loc[record_id_mask, "who_record_id"], errors="coerce").astype("Int64").astype(str)
    )
    catalog["duplicate_source_count"] = catalog.groupby("_dedup_key")["_dedup_key"].transform("size")
    catalog = (
        catalog.sort_values(["_dedup_key", "collector_topic_match", "source_file"])
        .drop_duplicates("_dedup_key", keep="last")
        .drop(columns="_dedup_key")
        .reset_index(drop=True)
    )
    duplicate_rows_removed = input_rows - len(catalog)

    location_lookup = location_catalog.set_index("location_code")["location"].to_dict()
    primary_candidates = catalog[
        catalog["indicator_code"].eq(WHO_HIV_PRIMARY_INDICATOR)
        & catalog["location_type"].eq("COUNTRY")
        & catalog["location_code"].isin(selected_codes)
    ].copy()
    hiv = primary_candidates[
        primary_candidates["numeric_value_clean"].notna() & primary_candidates["numeric_value_clean"].ge(0)
    ][
        ["location_code", "year", "numeric_value_clean", "low", "high", "indicator_name"]
    ].copy()
    hiv = hiv.rename(
        columns={
            "numeric_value_clean": "value",
            "low": "who_estimate_low",
            "high": "who_estimate_high",
            "indicator_name": "who_indicator_name",
        }
    )
    hiv = hiv.sort_values(["location_code", "year"]).drop_duplicates(["location_code", "year"], keep="last")

    prevalence = catalog[
        catalog["indicator_code"].eq(WHO_HIV_PREVALENCE_INDICATOR)
        & catalog["location_type"].eq("COUNTRY")
        & catalog["location_code"].isin(selected_codes)
        & catalog["numeric_value_clean"].notna()
    ][["location_code", "year", "numeric_value_clean", "low", "high"]].rename(
        columns={
            "numeric_value_clean": "hiv_prevalence_adults_percent",
            "low": "hiv_prevalence_adults_percent_low",
            "high": "hiv_prevalence_adults_percent_high",
        }
    )
    prevalence = prevalence.drop_duplicates(["location_code", "year"], keep="last")
    hiv = hiv.merge(prevalence, on=["location_code", "year"], how="left")
    if not hiv.empty:
        hiv["date"] = pd.to_datetime(hiv["year"].astype(str) + "-12-31")
        hiv["location"] = hiv["location_code"].map(location_lookup).fillna(hiv["location_code"])
        hiv["disease"] = HIV_DISEASE
        hiv["frequency"] = "annual"
        hiv["period_days"] = 365
        hiv["metric"] = "new_infections"
        hiv["metric_label"] = "年度新增 HIV 感染数"
        hiv["new_cases_clean"] = hiv["value"]
        hiv["published_smoothed"] = np.nan
        hiv["total_cases"] = np.nan
        hiv["total_deaths"] = np.nan
        hiv["new_deaths"] = np.nan
        hiv["is_negative_case_correction"] = False
        hiv["is_negative_death_correction"] = False
        hiv["source_population"] = np.nan
        hiv["source_density_per_km2"] = np.nan
        hiv["source_gdp_per_capita"] = np.nan
        hiv["source"] = f"WHO GHO {WHO_HIV_PRIMARY_INDICATOR}"
        hiv["quality_flag"] = np.where(
            hiv["who_estimate_low"].notna() & hiv["who_estimate_high"].notna(),
            "who_estimate_with_interval",
            "ok",
        )
        hiv["who_indicator_code"] = WHO_HIV_PRIMARY_INDICATOR

    tb_auxiliary: pd.DataFrame | None = None
    for indicator_code, output_column in WHO_TB_AUXILIARY_INDICATORS.items():
        part = catalog[
            catalog["indicator_code"].eq(indicator_code)
            & catalog["location_type"].eq("COUNTRY")
            & catalog["location_code"].isin(selected_codes)
            & catalog["numeric_value_clean"].notna()
        ][["location_code", "year", "numeric_value_clean", "low", "high"]].copy()
        part = part.rename(
            columns={
                "numeric_value_clean": output_column,
                "low": f"{output_column}_low",
                "high": f"{output_column}_high",
            }
        ).drop_duplicates(["location_code", "year"], keep="last")
        tb_auxiliary = part if tb_auxiliary is None else tb_auxiliary.merge(
            part,
            on=["location_code", "year"],
            how="outer",
        )
    if tb_auxiliary is None:
        tb_auxiliary = pd.DataFrame(columns=["location_code", "year"])
    if not tb_auxiliary.empty:
        tb_auxiliary["date"] = pd.to_datetime(tb_auxiliary["year"].astype("Int64").astype(str) + "-12-31")
        tb_auxiliary["location"] = tb_auxiliary["location_code"].map(location_lookup).fillna(
            tb_auxiliary["location_code"]
        )
        tb_auxiliary["source"] = "WHO GHO tuberculosis auxiliary indicators"

    hiv_year_gap_count = 0
    for _, group in hiv.groupby("location_code") if not hiv.empty else []:
        years = sorted(group["year"].dropna().astype(int).unique().tolist())
        if years:
            hiv_year_gap_count += max(years) - min(years) + 1 - len(years)
    quality = {
        "status": "cleaned" if not catalog.empty else "empty",
        "input_root": safe_relative(who_root),
        "input_files": len(all_files),
        "processed_latest_files": len(files),
        "stale_file_count": len(all_files) - len(files),
        "input_rows": input_rows,
        "output_rows": len(catalog),
        "duplicate_rows_removed": duplicate_rows_removed,
        "invalid_raw_json_rows": invalid_raw_json_rows,
        "empty_file_count": len(empty_files),
        "empty_files": empty_files,
        "schema_error_files": schema_error_files,
        "indicator_count": int(catalog["indicator_code"].nunique()),
        "numeric_rows": int(catalog["numeric_value_clean"].notna().sum()),
        "location_types": catalog.groupby("location_type").size().to_dict(),
        "files_by_topic_rows": file_rows_by_topic,
        "usage_rows": catalog.groupby("usage_class").size().to_dict(),
        "false_keyword_match_files": sorted(false_keyword_files),
        "future_date_rows": int(catalog["year"].gt(datetime.now().year).sum()),
        "date_min": iso_date(catalog["date"].min()),
        "date_max": iso_date(catalog["date"].max()),
        "primary_indicator": WHO_HIV_PRIMARY_INDICATOR,
        "primary_candidate_rows": len(primary_candidates),
        "primary_no_data_rows": int(primary_candidates["numeric_value_clean"].isna().sum()),
        "hiv_observation_rows": len(hiv),
        "hiv_country_count": int(hiv["location_code"].nunique()) if not hiv.empty else 0,
        "hiv_rows_by_country": hiv.groupby("location_code").size().to_dict() if not hiv.empty else {},
        "hiv_year_min": int(hiv["year"].min()) if not hiv.empty else None,
        "hiv_year_max": int(hiv["year"].max()) if not hiv.empty else None,
        "hiv_internal_year_gap_count": hiv_year_gap_count,
        "tb_auxiliary_rows": len(tb_auxiliary),
        "tb_auxiliary_country_count": int(tb_auxiliary["location_code"].nunique()) if not tb_auxiliary.empty else 0,
        "important_rule": "Only HIV_0000000026 becomes a disease observation. TB indicators are auxiliary; prison and keyword false-positive indicators remain catalog-only.",
    }
    return catalog.sort_values(["indicator_code", "location_type", "location_code", "year"]), hiv, tb_auxiliary, quality


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
        grouped["weather_source"] = "Open-Meteo representative-city daily weather"
        return grouped
    if frequency == "annual":
        frame["year"] = frame["date"].dt.year
        grouped = frame.groupby(["location_code", "year"], as_index=False)[WEATHER_VALUE_COLUMNS].mean()
        grouped["join_date"] = pd.to_datetime(grouped["year"].astype(str) + "-12-31")
        grouped = grouped.drop(columns="year")
        grouped["weather_match_level"] = "annual_mean"
        grouped["weather_source"] = "Open-Meteo representative-city daily weather"
        return grouped
    frame = frame.rename(columns={"date": "join_date"})
    frame["weather_match_level"] = "exact_day"
    frame["weather_source"] = "Open-Meteo representative-city daily weather"
    return frame[["location_code", "join_date", *WEATHER_VALUE_COLUMNS, "weather_match_level", "weather_source"]]


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
    historical_weather: pd.DataFrame | None = None,
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
        if frequency == "annual" and historical_weather is not None and not historical_weather.empty:
            historical = historical_weather.copy()
            for column in WEATHER_VALUE_COLUMNS:
                if column not in historical.columns:
                    historical[column] = np.nan
            historical["join_date"] = pd.to_datetime(historical["date"], errors="coerce")
            historical["weather_source"] = historical.get(
                "source",
                pd.Series("Kaggle historical hourly weather", index=historical.index),
            )
            historical = historical[
                ["location_code", "join_date", *WEATHER_VALUE_COLUMNS, "weather_match_level", "weather_source"]
            ]
            weather_for_frequency = (
                pd.concat([weather_for_frequency, historical], ignore_index=True, sort=False)
                .sort_values(["location_code", "join_date", "weather_match_level"])
                .drop_duplicates(["location_code", "join_date"], keep="last")
            )
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
    joined["weather_source"] = joined["weather_source"].fillna("unmatched")

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
        "weather_matches_by_level": joined.loc[joined["has_weather"]].groupby("weather_match_level").size().to_dict(),
        "weather_matches_by_source": joined.loc[joined["has_weather"]].groupby("weather_source").size().to_dict(),
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
    cdc_quality = quality_parts.get("china_cdc", {})
    who_quality = quality_parts.get("who", {})
    historical_quality = quality_parts.get("historical_weather", {})
    who_rows = int(who_quality.get("output_rows", 0))
    who_files = int(who_quality.get("input_files", 0))
    who_hiv_rows = int(who_quality.get("hiv_observation_rows", 0))
    who_status = "ok" if who_rows and who_hiv_rows else ("info" if who_rows else "not_configured")
    items = [
        {"name": "OWID COVID-19 daily (primary)", "status": "ok", "updated_at": generated_at, "rows": quality_parts["owid"]["output_rows"], "detail": "COVID 日频主表，已完成字段、日期和国家代码标准化。"},
        {"name": "Kaggle COVID-19 (cross-check)", "status": "ok", "updated_at": generated_at, "rows": quality_parts["kaggle_covid"]["output_rows"], "detail": "仅用于与 OWID 交叉核验，避免重复叠加病例。"},
        {"name": "Kaggle Tuberculosis annual indicators", "status": "ok", "updated_at": generated_at, "rows": quality_parts["tuberculosis"]["output_rows"], "detail": "结核病年发病率及辅助指标，保留原统计口径。"},
        {"name": "US weekly respiratory hospital metrics", "status": "ok", "updated_at": generated_at, "rows": quality_parts["respiratory"]["output_rows"], "detail": "美国全国周频住院指标，未重复汇总州级行。"},
        {"name": "Open-Meteo same-period daily weather", "status": "ok", "updated_at": generated_at, "rows": quality_parts["weather"]["output_rows"], "detail": "与疫情同期的代表城市日频天气。"},
        {"name": "World Bank + Kaggle population", "status": "ok", "updated_at": generated_at, "rows": quality_parts["population"]["output_rows"], "detail": "按 ISO3 和年份合并，缺年仅在相邻已知年份之间插值。"},
        {
            "name": "China CDC cleaned report index",
            "status": "info" if cdc_quality.get("output_rows", 0) else "warn",
            "updated_at": generated_at,
            "rows": cdc_quality.get("output_rows", 0),
            "raw_rows": cdc_quality.get("input_rows", 0),
            "detail": "网页索引、周次、附件完整性及高置信摘要字段已清洗；原 HTML/PDF 保留，复杂表格暂不作为模型标签。",
        },
        {
            "name": "WHO GHO indicators and HIV annual series",
            "status": who_status,
            "updated_at": generated_at,
            "rows": who_rows,
            "raw_rows": who_quality.get("input_rows", 0),
            "detail": (
                f"{who_files} 个本地 CSV 已清洗（{who_quality.get('empty_file_count', 0)} 个接口返回空表）；"
                f"HIV 年度主序列 {who_hiv_rows} 行，WHO 结核病指标作为辅助字段。"
                if who_rows
                else "未发现可用 WHO CSV；需要先采集或放入 data/raw/who。"
            ),
        },
        {
            "name": "Kaggle 2012-2017 historical weather",
            "status": "ok" if historical_quality.get("output_rows", 0) else "warn",
            "updated_at": generated_at,
            "rows": historical_quality.get("output_rows", 0),
            "raw_rows": historical_quality.get("input_rows", 0),
            "detail": "小时数据已聚合为美国 2012-2017 年天气，用于同年结核病探索性关联，不与 COVID 强行拼接。",
        },
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
                "detail": "模型已训练并导出预测结果。" if details.get("status", "trained") == "trained" else "模型训练状态需要检查。",
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
                "total_cases": numeric_or_none(row.get("total_cases")),
                "total_deaths": numeric_or_none(row.get("total_deaths")),
                "who_estimate_low": numeric_or_none(row.get("who_estimate_low")),
                "who_estimate_high": numeric_or_none(row.get("who_estimate_high")),
                "hiv_prevalence_adults_percent": numeric_or_none(row.get("hiv_prevalence_adults_percent")),
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

    model_predictions = (
        features[features["target_t_plus_7"].notna()]
        .sort_values(["disease", "location_code", "date"])
        .groupby(["disease", "location_code"], as_index=False, group_keys=False)
        .tail(2500)
        .copy()
    )
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
            "当前为 Windows 本地 Pandas 流水线，未使用 Spark/HDFS。",
            "Open-Meteo 使用国家代表城市天气，仅作为教学代理特征。",
            "结核病是年度每10万人发病率，呼吸系统数据是周住院人数，不跨口径相加。",
            "Kaggle 历史小时天气仅关联同年份美国结核病，不与 COVID 强行拼接。",
            "China CDC 已清洗元数据和高置信正文摘要，复杂 PDF 表格仍需人工复核。",
            "WHO HIV_0000000026 提供 HIV/AIDS 年度观测；No data 保留在目录但不作为模型目标。",
            "WHO 监狱指标和关键词误匹配只进入目录；WHO 结核病指标不覆盖原发病率目标。",
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
        location_date_ranges: dict[str, Any] = {}
        for code, series in subset.groupby("location_code", sort=True):
            series = series.sort_values("date")
            full_start = pd.Timestamp(series["date"].min())
            full_end = pd.Timestamp(series["date"].max())
            default_start = full_start
            default_end = full_end
            last_nonzero_date = None
            if disease == COVID_DISEASE and str(series["frequency"].iloc[0]) == "daily":
                signal_columns = [
                    "value",
                    "rolling_mean_7",
                    "prediction_error",
                ]
                informative = pd.Series(False, index=series.index)
                for column in signal_columns:
                    if column in series:
                        informative = informative | pd.to_numeric(series[column], errors="coerce").abs().gt(1e-9)
                nonzero_actual = pd.to_numeric(series["value"], errors="coerce").abs().gt(1e-9)
                if nonzero_actual.any():
                    last_nonzero_date = pd.Timestamp(series.loc[nonzero_actual, "date"].max())
                if informative.any():
                    default_end = pd.Timestamp(series.loc[informative, "date"].max())
                    default_start = max(full_start, default_end - pd.Timedelta(days=365))
            location_date_ranges[str(code)] = {
                "full_start": iso_date(full_start),
                "full_end": iso_date(full_end),
                "default_start": iso_date(default_start),
                "default_end": iso_date(default_end),
                "last_nonzero_date": iso_date(last_nonzero_date),
            }
        availability[disease] = {
            "locations": [location_by_code[code] for code in codes if code in location_by_code],
            "date_range": {"start": iso_date(subset["date"].min()), "end": iso_date(subset["date"].max())},
            "frequency": first["frequency"],
            "metric": first["metric"],
            "metric_label": first["metric_label"],
            "models": models,
            "location_date_ranges": location_date_ranges,
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
            "weather_source",
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
    progress = PipelineProgress(total=15, enabled=not args.no_progress)

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
    historical_weather_root = project_path(
        get_setting(settings, "paths.historical_weather_raw", "data/raw/kaggle/weather/historical-hourly-weather-data")
    )
    china_cdc_root = project_path(get_setting(settings, "paths.china_cdc_raw", "data/raw/china_cdc"))
    who_root = project_path(get_setting(settings, "paths.who_raw", "data/raw/who"))
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

    progress.start("Aggregate Kaggle 2012-2017 hourly weather without forcing COVID joins")
    historical_weather, historical_weather_quality = clean_historical_weather(historical_weather_root, selected_codes)
    progress.done(
        f"raw_rows={historical_weather_quality['input_rows']}, annual_rows={historical_weather_quality['output_rows']}, "
        f"countries={historical_weather_quality['country_count']}"
    )

    progress.start("Clean China CDC report metadata and verify local attachments")
    china_cdc, china_cdc_quality = clean_china_cdc_metadata(china_cdc_root)
    progress.done(
        f"rows={china_cdc_quality['output_rows']}, detail={china_cdc_quality.get('detail_rows', 0)}, "
        f"missing_attachments={china_cdc_quality.get('local_attachment_missing_count', 0)}"
    )

    progress.start("Clean WHO GHO catalog and curate HIV/Tuberculosis indicators")
    who_catalog, who_hiv, who_tb_auxiliary, who_quality = clean_who(
        who_root,
        selected_codes,
        location_catalog,
    )
    who_tb_columns = [
        column
        for column in who_tb_auxiliary.columns
        if column.startswith("who_tb_")
    ]
    if who_tb_columns:
        tuberculosis = tuberculosis.merge(
            who_tb_auxiliary[["location_code", "year", *who_tb_columns]],
            on=["location_code", "year"],
            how="left",
        )
    tuberculosis_quality["who_auxiliary_matched_rows"] = int(
        tuberculosis[who_tb_columns].notna().any(axis=1).sum()
    ) if who_tb_columns else 0
    tuberculosis_quality["who_auxiliary_non_missing_rate"] = {
        column: round(float(tuberculosis[column].notna().mean()), 6) for column in who_tb_columns
    }
    progress.done(
        f"catalog={who_quality['output_rows']}, HIV={who_quality['hiv_observation_rows']}, "
        f"TB_aux={who_quality['tb_auxiliary_rows']}, false_matches={len(who_quality['false_keyword_match_files'])}"
    )

    progress.start("Build canonical multi-disease observation table")
    observations = pd.concat([owid, tuberculosis, respiratory, who_hiv], ignore_index=True, sort=False)
    observations = observations.drop_duplicates(["location_code", "disease", "date"], keep="last")
    progress.done(f"rows={len(observations)}, diseases={observations['disease'].nunique()}, countries={observations['location_code'].nunique()}")

    progress.start("Join weather and socioeconomic context without dropping epidemics")
    features, feature_quality = build_features(
        observations,
        weather,
        population,
        location_catalog,
        historical_weather=historical_weather,
    )
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
    historical_weather.to_csv(silver_dir / "historical_weather_annual_clean.csv", index=False, encoding="utf-8-sig")
    china_cdc.to_csv(silver_dir / "china_cdc_metadata_clean.csv", index=False, encoding="utf-8-sig")
    who_catalog.to_csv(silver_dir / "who_indicators_clean.csv", index=False, encoding="utf-8-sig")
    who_hiv.to_csv(silver_dir / "who_hiv_annual_clean.csv", index=False, encoding="utf-8-sig")
    who_tb_auxiliary.to_csv(silver_dir / "who_tuberculosis_auxiliary_clean.csv", index=False, encoding="utf-8-sig")
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
        "historical_weather": historical_weather_quality,
        "china_cdc": china_cdc_quality,
        "who": who_quality,
        "features": feature_quality,
        "models": metrics.get("models", {}),
        "available_models": available_models,
        "source_decisions": {
            "primary_covid": "OWID compact daily table",
            "kaggle_covid": "cross-check only to prevent duplicate COVID rows",
            "tuberculosis": "annual incidence per 100,000; auxiliary death/detection/treatment/HIV fields retained",
            "respiratory": "provided USA national weekly row; state rows are not re-summed",
            "historical_kaggle_weather": "aggregated to USA annual means and joined only to same-year Tuberculosis rows; never joined to COVID",
            "china_cdc": "clean metadata and high-confidence text summaries; original HTML/PDF retained, complex PDF tables excluded from model labels",
            "who": "HIV_0000000026 is an annual HIV/AIDS observation; selected TB indicators are auxiliary; prison and keyword false-positive indicators remain catalog-only",
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
    print(f"  WHO catalog rows: {who_quality['output_rows']}; HIV observation rows: {who_quality['hiv_observation_rows']}")
    print(f"  best COVID daily model: {comparison.get('best_model')}")
    print(f"  trained model options: {', '.join(available_models)}")
    print(f"  model dir: {safe_relative(model_dir)}")
    print(f"  serving dir: {safe_relative(serving_dir)}")
    print("  full report: data/serving/local_real_pipeline_manifest.json")
    if args.print_json:
        print(json.dumps(to_jsonable(quality_parts), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
