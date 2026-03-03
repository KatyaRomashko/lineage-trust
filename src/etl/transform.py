"""
STAGE 1-B  –  Clean and normalise raw data before warehouse load.

Steps
-----
1. Drop duplicates
2. Coerce types (timestamps, numerics)
3. Fill / drop nulls
4. Min-max normalise numerical columns
5. Ensure event_timestamp is timezone-aware (UTC)
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

NUMERIC_COLS = [
    "tenure_months",
    "monthly_charges",
    "total_charges",
    "num_support_tickets",
]


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Remove duplicates, coerce types, handle nulls."""
    before = len(df)
    df = df.drop_duplicates(subset=["entity_id"]).copy()
    logger.info("Dropped %d duplicate rows", before - len(df))

    df["event_timestamp"] = pd.to_datetime(df["event_timestamp"], utc=True)

    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Fill missing numerics with column median
    for col in NUMERIC_COLS:
        if df[col].isna().any():
            median = df[col].median()
            df[col] = df[col].fillna(median)
            logger.info("Filled %s nulls with median %.2f", col, median)

    df["churn"] = df["churn"].astype(int)
    return df


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Min-max scale numerical features to [0, 1]."""
    df = df.copy()
    for col in NUMERIC_COLS:
        cmin, cmax = df[col].min(), df[col].max()
        if cmax - cmin > 0:
            df[col] = (df[col] - cmin) / (cmax - cmin)
        else:
            df[col] = 0.0
        logger.info("Normalised %s  (min=%.2f, max=%.2f)", col, cmin, cmax)
    return df


def transform(df: pd.DataFrame) -> pd.DataFrame:
    """Full transform pipeline: clean → normalise."""
    df = clean(df)
    df = normalise(df)
    logger.info("Transform complete – %d rows, %d cols", len(df), len(df.columns))
    return df
