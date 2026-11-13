"""
FormulaAI — Snowflake Client Helper

Provides connection management and query execution against the Snowflake
Enterprise Patent C-RAG warehouse (FORMULA_KNOWLEDGE_DB.GLOBAL_PATENTS).
"""

import os
import logging

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore

try:
    import snowflake.connector  # type: ignore
    SNOWFLAKE_AVAILABLE = True
except ImportError:
    SNOWFLAKE_AVAILABLE = False

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def get_snowflake_connection():
    """
    Creates and returns a Snowflake connection object using credentials
    from centralized Settings (preferred) or os.getenv fallback.
    """
    # Read from Pydantic Settings; fall back to raw env vars
    try:
        from config import get_settings
        _settings = get_settings()
        account = os.environ.get("SNOWFLAKE_ACCOUNT", _settings.snowflake_account)
        user = os.environ.get("SNOWFLAKE_USER", _settings.snowflake_user)
        password = os.environ.get("SNOWFLAKE_PASSWORD", _settings.snowflake_password)
        warehouse = os.environ.get("SNOWFLAKE_WAREHOUSE", _settings.snowflake_warehouse)
        database = os.environ.get("SNOWFLAKE_DATABASE", _settings.snowflake_database)
        schema = os.environ.get("SNOWFLAKE_SCHEMA", _settings.snowflake_schema)
        role = os.environ.get("SNOWFLAKE_ROLE", _settings.snowflake_role)
    except Exception:
        account = os.environ.get("SNOWFLAKE_ACCOUNT", "")
        user = os.environ.get("SNOWFLAKE_USER", "")
        password = os.environ.get("SNOWFLAKE_PASSWORD", "")
        warehouse = os.environ.get("SNOWFLAKE_WAREHOUSE", "FORMULA_APP_WH")
        database = os.environ.get("SNOWFLAKE_DATABASE", "FORMULA_KNOWLEDGE_DB")
        schema = os.environ.get("SNOWFLAKE_SCHEMA", "GLOBAL_PATENTS")
        role = os.environ.get("SNOWFLAKE_ROLE", "")

    # Strip any accidental whitespace or wrapping quotes from .env
    account = account.strip().strip('"\'')
    user = user.strip().strip('"\'')
    password = password.strip().strip('"\'')
    warehouse = warehouse.strip().strip('"\'')
    database = database.strip().strip('"\'')
    schema = schema.strip().strip('"\'')
    role = role.strip().strip('"\'') if role else ""

    if not all([account, user, password]):
        raise ValueError(
            "Missing required Snowflake credentials. "
            "Set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, and SNOWFLAKE_PASSWORD in backend/.env"
        )

    if not SNOWFLAKE_AVAILABLE:
        raise ImportError(
            "snowflake-connector-python is not installed. "
            "Run: pip install snowflake-connector-python[pandas]"
        )

    connect_kwargs = {
        "account": account,
        "user": user,
        "password": password,
        "warehouse": warehouse,
        "database": database,
        "schema": schema,
        "login_timeout": 15,
        "network_timeout": 30,
    }
    if role:
        connect_kwargs["role"] = role

    conn = snowflake.connector.connect(**connect_kwargs)

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
