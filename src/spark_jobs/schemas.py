from __future__ import annotations

EPIDEMIC_RAW_COLUMNS = [
    "SNo",
    "ObservationDate",
    "Province/State",
    "Country/Region",
    "Last Update",
    "Confirmed",
    "Deaths",
    "Recovered",
]

POPULATION_RAW_COLUMNS = [
    "Rank",
    "CCA3",
    "Country/Territory",
    "Capital",
    "Continent",
    "2022 Population",
    "2020 Population",
    "2015 Population",
    "2010 Population",
    "2000 Population",
    "1990 Population",
    "1980 Population",
    "1970 Population",
    "Area (km²)",
    "Density (per km²)",
    "Growth Rate",
    "World Population Percentage",
]

WEATHER_RAW_COLUMNS = [
    "date",
    "location",
    "location_code",
    "representative_city",
    "latitude",
    "longitude",
    "temperature_mean",
    "temperature_max",
    "temperature_min",
    "precipitation_sum",
    "relative_humidity_mean",
    "wind_speed_max",
    "source",
    "source_timezone",
    "downloaded_at",
]

EPIDEMIC_SILVER_COLUMNS = [
    "date",
    "location",
    "location_code",
    "total_cases",
    "total_deaths",
    "total_recovered",
    "new_cases_raw",
    "new_cases_clean",
    "new_deaths_raw",
    "new_deaths_clean",
    "is_negative_case_correction",
    "is_negative_death_correction",
    "has_province_rows",
    "has_national_row",
    "aggregation_conflict",
    "source",
    "collected_at",
]


def epidemic_raw_schema():
    from pyspark.sql import types as T

    return T.StructType(
        [
            T.StructField("SNo", T.IntegerType(), True),
            T.StructField("ObservationDate", T.StringType(), True),
            T.StructField("Province/State", T.StringType(), True),
            T.StructField("Country/Region", T.StringType(), True),
            T.StructField("Last Update", T.StringType(), True),
            T.StructField("Confirmed", T.DoubleType(), True),
            T.StructField("Deaths", T.DoubleType(), True),
            T.StructField("Recovered", T.DoubleType(), True),
        ]
    )


def country_mapping_schema():
    from pyspark.sql import types as T

    return T.StructType(
        [
            T.StructField("epidemic_name", T.StringType(), True),
            T.StructField("population_name", T.StringType(), True),
            T.StructField("standard_name", T.StringType(), True),
            T.StructField("location_code", T.StringType(), True),
            T.StructField("enabled", T.StringType(), True),
            T.StructField("notes", T.StringType(), True),
        ]
    )


def population_raw_schema():
    from pyspark.sql import types as T

    return T.StructType(
        [
            T.StructField("Rank", T.IntegerType(), True),
            T.StructField("CCA3", T.StringType(), True),
            T.StructField("Country/Territory", T.StringType(), True),
            T.StructField("Capital", T.StringType(), True),
            T.StructField("Continent", T.StringType(), True),
            T.StructField("2022 Population", T.LongType(), True),
            T.StructField("2020 Population", T.LongType(), True),
            T.StructField("2015 Population", T.LongType(), True),
            T.StructField("2010 Population", T.LongType(), True),
            T.StructField("2000 Population", T.LongType(), True),
            T.StructField("1990 Population", T.LongType(), True),
            T.StructField("1980 Population", T.LongType(), True),
            T.StructField("1970 Population", T.LongType(), True),
            T.StructField("Area (km²)", T.DoubleType(), True),
            T.StructField("Density (per km²)", T.DoubleType(), True),
            T.StructField("Growth Rate", T.DoubleType(), True),
            T.StructField("World Population Percentage", T.DoubleType(), True),
        ]
    )


def weather_raw_schema():
    from pyspark.sql import types as T

    return T.StructType(
        [
            T.StructField("date", T.StringType(), True),
            T.StructField("location", T.StringType(), True),
            T.StructField("location_code", T.StringType(), True),
            T.StructField("representative_city", T.StringType(), True),
            T.StructField("latitude", T.DoubleType(), True),
            T.StructField("longitude", T.DoubleType(), True),
            T.StructField("temperature_mean", T.DoubleType(), True),
            T.StructField("temperature_max", T.DoubleType(), True),
            T.StructField("temperature_min", T.DoubleType(), True),
            T.StructField("precipitation_sum", T.DoubleType(), True),
            T.StructField("relative_humidity_mean", T.DoubleType(), True),
            T.StructField("wind_speed_max", T.DoubleType(), True),
            T.StructField("source", T.StringType(), True),
            T.StructField("source_timezone", T.StringType(), True),
            T.StructField("downloaded_at", T.StringType(), True),
        ]
    )
