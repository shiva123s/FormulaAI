"""
Unit tests for continuous patent data ingestion (Lens.org fetcher + Snowflake loader)
"""

import pytest
from unittest.mock import MagicMock, patch
from ingestion.patents import fetch_agri_patents, load_patents_to_snowflake


def test_fetch_agri_patents_structure():
    """Verify fetch_agri_patents returns the target schema dictionaries."""
    patents = fetch_agri_patents(limit=5)
    assert isinstance(patents, list)
    assert len(patents) > 0

    expected_keys = {
        "PATENT_ID",
        "COUNTRY_CODE",
        "TITLE",
        "ABSTRACT",
        "PUBLICATION_DATE",
        "SOURCE_URL",
    }

    for p in patents:
        assert expected_keys.issubset(p.keys())
        assert p["COUNTRY_CODE"] in ["US", "BR", "WO"]
        assert len(p["PATENT_ID"]) > 0
        assert len(p["TITLE"]) > 0


def test_fetch_agri_patents_mocked_lens():
    """Verify Lens.org API response parsing logic."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "total": 1,
        "data": [
            {
                "lens_id": "001-234-567-890",
                "jurisdiction": "BR",
                "doc_number": "112021008412",
                "kind": "A2",
                "title": [{"text": "Mock Brazilian Formulation Patent", "lang": "pt"}],
                "abstract": [{"text": "Mock abstract covering Beauveria bassiana.", "lang": "pt"}],
                "date_published": "2021-08-10",
            }
        ],
    }

    with patch("requests.post", return_value=mock_response):
        patents = fetch_agri_patents(api_key="mock_lens_key", limit=1)
        assert len(patents) == 1
        p = patents[0]
        assert p["PATENT_ID"] == "BR-112021008412-A2"
        assert p["COUNTRY_CODE"] == "BR"
        assert p["TITLE"] == "Mock Brazilian Formulation Patent"
        assert "Beauveria bassiana" in p["ABSTRACT"]
        assert p["PUBLICATION_DATE"] == "2021-08-10"


def test_load_patents_to_snowflake_empty():
    """Verify empty list is handled cleanly without calling database."""
    result = load_patents_to_snowflake([])
    assert result == 0


def test_load_patents_to_snowflake_mocked():
    """Verify executemany and MERGE queries are invoked correctly."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    sample_patents = [
        {
            "PATENT_ID": "US-10849321-B2",
            "COUNTRY_CODE": "US",
            "TITLE": "Test Patent",
            "ABSTRACT": "Test abstract",
            "PUBLICATION_DATE": "2020-12-01",
            "SOURCE_URL": "https://example.com/patent",
        }
    ]

    with patch("ingestion.patents.get_snowflake_connection", return_value=mock_conn):
        count = load_patents_to_snowflake(sample_patents)
        assert count == 1
        assert mock_cursor.execute.call_count >= 3  # CREATE TABLE + 3 ALTER statements
        assert mock_cursor.executemany.call_count == 1
        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()

