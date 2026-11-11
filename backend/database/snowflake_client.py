"""
FormulaAI — Snowflake Client Helper

Provides connection management and query execution against the Snowflake
Enterprise Patent C-RAG warehouse (FORMULA_KNOWLEDGE_DB.GLOBAL_PATENTS).
"""

import os
import logging
import pandas as pd
import snowflake.connector
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def get_snowflake_connection() -> snowflake.connector.SnowflakeConnection:
    """
    Creates and returns a Snowflake connection object using credentials
    from centralized Settings (preferred) or os.getenv fallback.
    """
    # Read from Pydantic Settings; fall back to raw env vars
    try:
        from config import get_settings
        _settings = get_settings()
        account = _settings.snowflake_account or os.getenv("SNOWFLAKE_ACCOUNT", "")
        user = _settings.snowflake_user or os.getenv("SNOWFLAKE_USER", "")
        password = _settings.snowflake_password or os.getenv("SNOWFLAKE_PASSWORD", "")
        warehouse = _settings.snowflake_warehouse or os.getenv("SNOWFLAKE_WAREHOUSE", "FORMULA_APP_WH")
        database = _settings.snowflake_database or os.getenv("SNOWFLAKE_DATABASE", "FORMULA_KNOWLEDGE_DB")
        schema = _settings.snowflake_schema or os.getenv("SNOWFLAKE_SCHEMA", "GLOBAL_PATENTS")
    except Exception:
        account = os.getenv("SNOWFLAKE_ACCOUNT", "")
        user = os.getenv("SNOWFLAKE_USER", "")
        password = os.getenv("SNOWFLAKE_PASSWORD", "")
        warehouse = os.getenv("SNOWFLAKE_WAREHOUSE", "FORMULA_APP_WH")
        database = os.getenv("SNOWFLAKE_DATABASE", "FORMULA_KNOWLEDGE_DB")
        schema = os.getenv("SNOWFLAKE_SCHEMA", "GLOBAL_PATENTS")

    # Strip any accidental whitespace or wrapping quotes from .env
    account = account.strip().strip('"\'')
    user = user.strip().strip('"\'')
    password = password.strip().strip('"\'')
    warehouse = warehouse.strip().strip('"\'')
    database = database.strip().strip('"\'')
    schema = schema.strip().strip('"\'')

    if not all([account, user, password]):
        raise ValueError(
            "Missing required Snowflake credentials. "
            "Set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, and SNOWFLAKE_PASSWORD in backend/.env"
        )

    conn = snowflake.connector.connect(
        account=account,
        user=user,
        password=password,
        warehouse=warehouse,
        database=database,
        schema=schema,
        login_timeout=15,
        network_timeout=30,
    )

    logger.info("Snowflake connection established (warehouse=%s)", conn.warehouse)
    return conn


def query_patents_to_dataframe(query: str, params: dict | list | tuple | None = None) -> pd.DataFrame:
    """
    Executes a SQL query against Snowflake and returns results as a pandas DataFrame.
    Safely handles both Arrow-backed fetches and empty result sets.
    """
    conn = get_snowflake_connection()
    cursor = conn.cursor()
    try:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        try:
            df = cursor.fetch_pandas_all()
        except Exception:
            # Fallback if Arrow batch fetch fails on empty results or specific Windows builds
            rows = cursor.fetchall()
            cols = [col[0] for col in cursor.description] if cursor.description else []
            df = pd.DataFrame(rows, columns=cols)

        logger.info("Snowflake query returned %d rows", len(df))
        return df
    finally:
        cursor.close()
        conn.close()
        logger.debug("Snowflake connection closed")
