"""
STAGE 1-C  –  Load transformed data into PostgreSQL Data Warehouse.
"""

import logging

import pandas as pd
from sqlalchemy import create_engine

logger = logging.getLogger(__name__)


def load_to_postgres(
    df: pd.DataFrame,
    pg_url: str,
    table_name: str,
    if_exists: str = "replace",
) -> None:
    """Write a DataFrame to a PostgreSQL table using SQLAlchemy."""
    engine = create_engine(pg_url)
    logger.info("Loading %d rows into %s (mode=%s)", len(df), table_name, if_exists)
    df.to_sql(table_name, engine, index=False, if_exists=if_exists, method="multi")
    logger.info("Load complete → %s", table_name)
    engine.dispose()
