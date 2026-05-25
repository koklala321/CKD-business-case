"""
data_builder.py
===============
Cleans raw API records from api_client.py into a validated long-format DataFrame.
"""

from __future__ import annotations
import logging
import pandas as pd
logger = logging.getLogger(__name__)


#cleanse raw records
def clean_raw_records(records: list[dict]) -> pd.DataFrame:
    """
    Convert the raw list of dicts from api_client into a clean long-format DataFrame.
    """
    if not records:
        raise ValueError("clean_raw_records() received an empty records list.")

    df = pd.DataFrame(records)

    #stripping string fields
    for col in ("area_name", "indicator_code", "time_period_name"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    # Drop rows with missing or empty identifier fields
    identity_cols = ["area_name", "time_period_id", "indicator_code"]
    before = len(df)
    df = df.dropna(subset=identity_cols)
    non_empty = df[identity_cols].apply(lambda s: s.astype(str).str.len() > 0).all(axis=1)
    df = df[non_empty]
    _log_dropped("missing or empty identity fields", before, len(df))

    #Drop rows with null numerator or denominator
    before = len(df)
    df = df.dropna(subset=["numerator", "denominator"])
    _log_dropped("null numerator or denominator", before, len(df))

    #Dedup on identifier — include category columns so stratified records are
    #preserved when unfiltered records are passed.
    dedup_keys = ["area_id", "time_period_id", "indicator_code"]
    for col in ("category_attribute", "metric_category_type_name", "metric_category_name"):
        if col in df.columns:
            dedup_keys = dedup_keys + [col]
    before = len(df)
    df = df.drop_duplicates(subset=dedup_keys, keep="first")
    _log_dropped("duplicate (area, period, indicator, category) combinations", before, len(df))

    #Coerce to numeric (catches strings like "N/A" that slipped through)
    for col in ("numerator", "denominator", "value"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    before = len(df)
    df = df.dropna(subset=["numerator", "denominator"])
    _log_dropped("non-numeric numerator/denominator after coercion", before, len(df))

    #Cast to int (counts are always whole numbers)
    df["numerator"] = df["numerator"].astype(int)
    df["denominator"] = df["denominator"].astype(int)

    #Drop zero-denominator rows
    mask_zero = df["denominator"] == 0
    if mask_zero.any():
        logger.warning(
            "Dropping %d row(s) with denominator == 0 (no base population):\n%s",
            mask_zero.sum(),
            df.loc[mask_zero, ["area_name", "indicator_code", "time_period_name"]]
            .to_string(index=False),
        )
    before = len(df)
    df = df[~mask_zero]
    _log_dropped("zero denominator", before, len(df))

    #Drop rows where numerator > denominator
    mask_invalid = df["numerator"] > df["denominator"]
    if mask_invalid.any():
        logger.warning(
            "Dropping %d row(s) where numerator > denominator "
            "(data integrity violation):\n%s",
            mask_invalid.sum(),
            df.loc[
                mask_invalid,
                ["area_name", "indicator_code", "time_period_name", "numerator", "denominator"],
            ].to_string(index=False),
        )
    df = df[~mask_invalid]

    logger.info(
        "Cleaned long-format DataFrame: %d rows across %d ICBs, %d indicators",
        len(df),
        df["area_name"].nunique(),
        df["indicator_code"].nunique(),
    )
    return df.reset_index(drop=True)


def _log_dropped(reason: str, before: int, after: int) -> None:
    """Emit a warning only when rows were actually dropped."""
    dropped = before - after
    if dropped > 0:
        logger.warning("Dropped %d row(s) — reason: %s", dropped, reason)
