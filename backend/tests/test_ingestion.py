"""
FormulaAI — Ingestion Connector Unit Tests

Tests all ingestion connectors using respx to mock HTTP responses.
No actual API calls are made during testing.
"""

from __future__ import annotations

import pytest
import httpx
import respx

from ingestion.base import RawDocument, IngestionStats
from ingestion.openalex import OpenAlexConnector
from ingestion.pubmed import PubMedConnector
from ingestion.patents import PatentConnector
from ingestion.chembl import ChEMBLConnector
from ingestion.fda_iid import FDAIIDConnector
from ingestion.epa_inert import EPAInertConnector
from ingestion.tds_sds_scraper import TDSSDSScraper
from tests.conftest import (
    SAMPLE_OPENALEX_RESPONSE,
    SAMPLE_OPENALEX_WORK,
    SAMPLE_PUBMED_XML,
    SAMPLE_CHEMBL_SEARCH_RESPONSE,
    SAMPLE_CHEMBL_MOLECULE,
    SAMPLE_PATENT_RESPONSE,
)


# ── RawDocument Tests ────────────────────────────────────────────────────────


class TestRawDocument:
    def test_creation(self):
        doc = RawDocument(
            source_id="DOI:10.1000/test",
            source_type="paper",
            title="Test Paper",
            abstract="Test abstract",
        )
        assert doc.source_id == "DOI:10.1000/test"
        assert doc.source_type == "paper"
        assert doc.title == "Test Paper"
        assert doc.ingested_at.endswith("Z")

    def test_defaults(self):
        doc = RawDocument(source_id="x", source_type="y", title="z")
        assert doc.abstract is None
        assert doc.full_text is None
        assert doc.authors == []
        assert doc.keywords == []
        assert doc.metadata == {}
        assert doc.raw_response == {}


class TestIngestionStats:
    def test_tracking(self):
        stats = IngestionStats(connector_name="TestConnector")
        assert stats.documents_fetched == 0
        stats.documents_fetched += 5
        stats.api_calls_made += 10
        stats.finish()
        assert stats.documents_fetched == 5
        assert stats.api_calls_made == 10
        assert stats.finished_at is not None


# ── OpenAlex Connector Tests ────────────────────────────────────────────────


class TestOpenAlexConnector:
    @pytest.mark.asyncio
    @respx.mock
    async def test_search(self):
        respx.get("https://api.openalex.org/works").mock(
            return_value=httpx.Response(200, json=SAMPLE_OPENALEX_RESPONSE)
        )

        async with OpenAlexConnector(
            base_url="https://api.openalex.org",
            email="test@example.com",
        ) as conn:
            docs = []
            async for doc in conn.search("glyphosate surfactant", max_results=10):
                docs.append(doc)

            assert len(docs) == 1
            assert docs[0].source_type == "paper"
            assert "surfactant" in docs[0].title.lower()
            assert docs[0].authors == ["Jane Smith", "John Doe"]
            assert docs[0].publication_date == "2023-06-15"

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_document(self):
        respx.get("https://api.openalex.org/works/W2741809807").mock(
            return_value=httpx.Response(200, json=SAMPLE_OPENALEX_WORK)
        )

        async with OpenAlexConnector(
            base_url="https://api.openalex.org",
            email="test@example.com",
        ) as conn:
            doc = await conn.fetch_document("W2741809807")
            assert doc is not None
            assert doc.title == "Novel surfactant systems for glyphosate formulation"

    def test_reconstruct_abstract(self):
        inverted_index = {
            "Hello": [0],
            "world": [1],
            "of": [2],
            "chemistry.": [3],
        }
        result = OpenAlexConnector._reconstruct_abstract(inverted_index)
        assert result == "Hello world of chemistry."

    def test_reconstruct_abstract_none(self):
        assert OpenAlexConnector._reconstruct_abstract(None) is None
        assert OpenAlexConnector._reconstruct_abstract({}) is None


# ── PubMed Connector Tests ──────────────────────────────────────────────────


class TestPubMedConnector:
    @pytest.mark.asyncio
    @respx.mock
    async def test_search(self):
        # Mock esearch
        respx.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"esearchresult": {"idlist": ["12345678"]}},
            )
        )
        # Mock efetch
        respx.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        ).mock(return_value=httpx.Response(200, text=SAMPLE_PUBMED_XML))

        async with PubMedConnector(
            email="test@example.com",
            api_key="test_key",
        ) as conn:
            docs = []
            async for doc in conn.search("surfactant pesticide", max_results=10):
                docs.append(doc)

            assert len(docs) == 1
            assert docs[0].source_id == "PMID:12345678"
            assert docs[0].source_type == "paper"
            assert "Surfactant" in docs[0].title
            assert "Maria Garcia" in docs[0].authors
            assert "Surfactants" in docs[0].keywords

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_document(self):
        respx.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        ).mock(return_value=httpx.Response(200, text=SAMPLE_PUBMED_XML))

        async with PubMedConnector(
            email="test@example.com",
        ) as conn:
            doc = await conn.fetch_document("12345678")
            assert doc is not None
            assert doc.source_id == "PMID:12345678"

    def test_email_required(self):
        with pytest.raises(ValueError, match="NCBI requires an email"):
            PubMedConnector(email="")


# ── Patent Connector Tests ──────────────────────────────────────────────────


class TestPatentConnector:
    @pytest.mark.asyncio
    @respx.mock
    async def test_search(self):
        respx.post("https://api.patentsview.org/patents/query").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATENT_RESPONSE)
        )

        async with PatentConnector() as conn:
            docs = []
            async for doc in conn.search("herbicide surfactant", max_results=10):
                docs.append(doc)

            assert len(docs) == 1
            assert docs[0].source_type == "patent"
            assert docs[0].source_id == "US10123456"
            assert "Herbicide" in docs[0].title
            assert "Alice Johnson" in docs[0].authors

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_document(self):
        respx.post("https://api.patentsview.org/patents/query").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATENT_RESPONSE)
        )

        async with PatentConnector() as conn:
            doc = await conn.fetch_document("US10123456")
            assert doc is not None
            assert doc.metadata["patent_type"] == "utility"
            assert doc.metadata["num_claims"] == 20

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_not_found(self):
        respx.post("https://api.patentsview.org/patents/query").mock(
            return_value=httpx.Response(200, json={"patents": [], "total_patent_count": 0})
        )

        async with PatentConnector() as conn:
            docs = []
            async for doc in conn.search("nonexistent compound xyz"):
                docs.append(doc)
            assert len(docs) == 0


# ── ChEMBL Connector Tests ──────────────────────────────────────────────────


class TestChEMBLConnector:
    @pytest.mark.asyncio
    @respx.mock
    async def test_search(self):
        respx.get("https://www.ebi.ac.uk/chembl/api/data/molecule.json").mock(
            return_value=httpx.Response(200, json=SAMPLE_CHEMBL_SEARCH_RESPONSE)
        )

        async with ChEMBLConnector() as conn:
            docs = []
            async for doc in conn.search("aspirin", max_results=10):
                docs.append(doc)

            assert len(docs) == 1
            assert docs[0].source_id == "CHEMBL25"
            assert docs[0].source_type == "chembl"
            assert docs[0].metadata["canonical_smiles"] == "CC(=O)Oc1ccccc1C(O)=O"

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_document(self):
        respx.get(
            "https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL25.json"
        ).mock(return_value=httpx.Response(200, json=SAMPLE_CHEMBL_MOLECULE))

        async with ChEMBLConnector() as conn:
            doc = await conn.fetch_document("CHEMBL25")
            assert doc is not None
            assert doc.title == "ASPIRIN"


# ── FDA IID Connector Tests ─────────────────────────────────────────────────


class TestFDAIIDConnector:
    @pytest.mark.asyncio
    async def test_search(self):
        async with FDAIIDConnector() as conn:
            docs = []
            async for doc in conn.search("polysorbate"):
                docs.append(doc)

            assert len(docs) >= 2  # Polysorbate 20 and 80
            for doc in docs:
                assert doc.source_type == "fda_iid"
                assert "polysorbate" in doc.title.lower()

    @pytest.mark.asyncio
    async def test_fetch_document(self):
        async with FDAIIDConnector() as conn:
            doc = await conn.fetch_document("Polysorbate 80")
            assert doc is not None
            assert doc.metadata["cas_number"] == "9005-65-6"

    @pytest.mark.asyncio
    async def test_surfactant_search(self):
        async with FDAIIDConnector() as conn:
            docs = []
            async for doc in conn.get_all_surfactants(max_results=50):
                docs.append(doc)
            assert len(docs) > 0


# ── EPA INERTFinder Tests ────────────────────────────────────────────────────


class TestEPAInertConnector:
    @pytest.mark.asyncio
    async def test_check_status_cached(self):
        async with EPAInertConnector() as conn:
            status = await conn.check_status("Polysorbate 80")
            assert status is not None
            assert status.epa_list == "4A"
            assert status.status == "approved"
            assert status.food_use_permitted is True

    @pytest.mark.asyncio
    async def test_check_status_restricted(self):
        async with EPAInertConnector() as conn:
            status = await conn.check_status("N-Methyl-2-Pyrrolidone")
            assert status is not None
            assert status.epa_list == "2"
            assert status.status == "restricted"

    @pytest.mark.asyncio
    async def test_check_status_unknown(self):
        async with EPAInertConnector() as conn:
            status = await conn.check_status("NonexistentCompound123")
            assert status is None

    @pytest.mark.asyncio
    async def test_search(self):
        async with EPAInertConnector() as conn:
            docs = []
            async for doc in conn.search("glycerin"):
                docs.append(doc)
            assert len(docs) == 1
            assert docs[0].source_type == "regulatory"

    @pytest.mark.asyncio
    async def test_get_approved_inerts(self):
        async with EPAInertConnector() as conn:
            docs = []
            async for doc in conn.get_approved_inerts():
                docs.append(doc)
            assert len(docs) > 0
            for doc in docs:
                assert "EPA-List-4A" in doc.keywords


# ── TDS/SDS Scraper Tests ───────────────────────────────────────────────────


class TestTDSSDSScraper:
    @pytest.mark.asyncio
    async def test_search_placeholder(self):
        async with TDSSDSScraper() as scraper:
            docs = []
            async for doc in scraper.search("polysorbate 80"):
                docs.append(doc)
            assert len(docs) == 1
            assert docs[0].metadata["status"] == "pending"

    def test_extract_hlb_value(self):
        assert TDSSDSScraper.extract_hlb_value("HLB: 15.0") == 15.0
        assert TDSSDSScraper.extract_hlb_value("HLB = 4.3") == 4.3
        assert TDSSDSScraper.extract_hlb_value("HLB value of 12") == 12.0
        assert TDSSDSScraper.extract_hlb_value("no data here") is None

    def test_extract_ph_range(self):
        result = TDSSDSScraper.extract_ph_range("stable at pH 4.0-8.5")
        assert result == (4.0, 8.5)

        result = TDSSDSScraper.extract_ph_range("pH range: 3 to 9")
        assert result == (3.0, 9.0)

        assert TDSSDSScraper.extract_ph_range("no pH data") is None

    def test_extract_viscosity(self):
        result = TDSSDSScraper.extract_viscosity("viscosity: 450 mPa.s")
        assert result is not None
        assert result["value"] == 450.0

        assert TDSSDSScraper.extract_viscosity("no viscosity info") is None
