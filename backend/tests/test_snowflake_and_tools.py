"""
FormulaAI — Snowflake Client & Tools Fallback Unit Tests

Tests Snowflake configuration validation, safe query fallback, and search_global_patents fallback.
"""

import json
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from config import Settings
from database.snowflake_client import get_snowflake_connection, query_patents_to_dataframe
from agents.tools import search_global_patents


class TestSnowflakeConfig:
    def test_is_snowflake_configured_false_when_empty(self):
        settings = Settings(
            snowflake_account="",
            snowflake_user="",
            snowflake_password="",
        )
        assert settings.is_snowflake_configured is False

    def test_is_snowflake_configured_true_when_set(self):
        settings = Settings(
            snowflake_account="test-acc",
            snowflake_user="test-user",
            snowflake_password="test-password",
        )
        assert settings.is_snowflake_configured is True


class TestSnowflakeClient:
    def test_get_snowflake_connection_raises_without_credentials(self, monkeypatch):
        monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "")
        monkeypatch.setenv("SNOWFLAKE_USER", "")
        monkeypatch.setenv("SNOWFLAKE_PASSWORD", "")
        with pytest.raises(ValueError, match="Missing required Snowflake credentials"):
            get_snowflake_connection()

    @patch("database.snowflake_client.get_snowflake_connection")
    def test_query_patents_fallback_on_arrow_error(self, mock_conn):
        mock_cursor = MagicMock()
        mock_cursor.fetch_pandas_all.side_effect = Exception("Arrow batch error")
        mock_cursor.description = [("PATENT_ID",), ("TITLE",), ("ABSTRACT",)]
        mock_cursor.fetchall.return_value = [
            ("US-12345", "Test Patent", "Sample abstract text")
        ]

        mock_conn_instance = MagicMock()
        mock_conn_instance.cursor.return_value = mock_cursor
        mock_conn.return_value = mock_conn_instance

        df = query_patents_to_dataframe("SELECT * FROM RAW_PATENT_DATA")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert list(df.columns) == ["PATENT_ID", "TITLE", "ABSTRACT"]
        assert df.iloc[0]["PATENT_ID"] == "US-12345"


class TestPatentSearchTool:
    @patch("agents.tools.query_patents_to_dataframe")
    def test_search_global_patents_fallback_on_failure(self, mock_query):
        mock_query.side_effect = Exception("Snowflake unreachable")
        res_str = search_global_patents.invoke({"keyword": "glyphosate"})
        res = json.loads(res_str)
        assert res["status"] == "fallback"
        assert "patents" in res
        assert len(res["patents"]) >= 3
        patent_ids = [p["patent_id"] for p in res["patents"]]
        assert "US-10849321-B2" in patent_ids
        assert "BR-112021008412-A2" in patent_ids
        assert "US-10842154-B2" in patent_ids

    @patch("agents.tools.query_patents_to_dataframe")
    def test_search_global_patents_normalizes_columns(self, mock_query):
        # Return dataframe with lowercase column names
        mock_df = pd.DataFrame([
            {"patent_id": "US-TEST-1", "title": "Test Title", "abstract": "Test Abstract"}
        ])
        mock_query.return_value = mock_df

        res_str = search_global_patents.invoke({"keyword": "test"})
        res = json.loads(res_str)
        assert res["status"] == "success"
        assert len(res["patents"]) == 1
        assert res["patents"][0]["patent_id"] == "US-TEST-1"
