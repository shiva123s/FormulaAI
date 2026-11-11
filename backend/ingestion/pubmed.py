"""
FormulaAI — PubMed E-Utilities Connector

Searches and retrieves biomedical literature from PubMed/MEDLINE via
the NCBI E-Utilities API. Covers 36M+ citations with a focus on
agrochemical formulation, toxicology, and plant science.

Pipeline:
  1. esearch → find PMIDs matching a query
  2. efetch  → retrieve full article metadata + abstracts in XML
  3. Parse XML → yield RawDocument objects

API Docs: https://www.ncbi.nlm.nih.gov/books/NBK25500/

Rate limits:
  • Without API key: 3 req/s
  • With API key:   10 req/s (set NCBI_API_KEY in .env)
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any, AsyncIterator

from ingestion.base import BaseConnector, RawDocument

logger = logging.getLogger(__name__)

# PubMed search terms for agrochemical literature
AGROCHEM_MESH_TERMS = [
    "Agrochemicals[MeSH]",
    "Pesticides[MeSH]",
    "Herbicides[MeSH]",
    "Fungicides, Industrial[MeSH]",
    "Insecticides[MeSH]",
    "Fertilizers[MeSH]",
    "Plant Growth Regulators[MeSH]",
    "Surfactants[MeSH]",
    "Excipients[MeSH]",
    "Drug Delivery Systems[MeSH]",
    "Nanoparticles[MeSH]",
]


class PubMedConnector(BaseConnector):
    """
    Async connector for the PubMed E-Utilities API.

    Usage:
        async with PubMedConnector(
            email="you@example.com",
            api_key="your_ncbi_key",
        ) as conn:
            async for doc in conn.search("glyphosate surfactant formulation"):
                print(doc.title, doc.source_id)
    """

    SOURCE_TYPE = "paper"

    def __init__(
        self,
        base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        email: str = "",
        api_key: str = "",
        rate_limit: float = 3.0,
        timeout: float = 30.0,
    ):
        if not email:
            raise ValueError(
                "NCBI requires an email address for E-Utilities API access. "
                "Set NCBI_EMAIL in your .env file."
            )

        # With API key: 10 req/s, without: 3 req/s
        effective_rate = 10.0 if api_key else rate_limit

        super().__init__(
            base_url=base_url,
            rate_limit=effective_rate,
            timeout=timeout,
        )
        self._email = email
        self._api_key = api_key

    def _base_params(self) -> dict[str, str]:
        """Common parameters for all E-Utilities requests."""
        params = {"email": self._email, "tool": "FormulaAI"}
        if self._api_key:
            params["api_key"] = self._api_key
        return params

    # ── Public API ───────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        max_results: int = 100,
        date_range: tuple[str, str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[RawDocument]:
        """
        Search PubMed for articles matching the query.

        Args:
            query: PubMed search query (supports MeSH terms, boolean).
            max_results: Maximum number of documents to yield.
            date_range: Optional (min_date, max_date) in YYYY/MM/DD format.

        Yields:
            RawDocument for each matching article.
        """
        pmids = await self._esearch(query, max_results, date_range)
        if not pmids:
            logger.info("PubMed search returned no results for: %s", query)
            return

        logger.info("PubMed found %d PMIDs for: %s", len(pmids), query)

        # Fetch articles in batches of 100
        batch_size = 100
        for i in range(0, len(pmids), batch_size):
            batch = pmids[i : i + batch_size]
            docs = await self._efetch_batch(batch)
            for doc in docs:
                yield doc

    async def fetch_document(self, doc_id: str) -> RawDocument | None:
        """
        Fetch a single PubMed article by its PMID.

        Args:
            doc_id: PubMed ID (e.g., "12345678").
        """
        docs = await self._efetch_batch([doc_id])
        return docs[0] if docs else None

    async def search_mesh(
        self,
        mesh_terms: list[str] | None = None,
        max_results: int = 100,
    ) -> AsyncIterator[RawDocument]:
        """
        Search PubMed using MeSH (Medical Subject Headings) terms.

        Defaults to AGROCHEM_MESH_TERMS if none provided.
        """
        terms = mesh_terms or AGROCHEM_MESH_TERMS
        query = " OR ".join(terms)
        async for doc in self.search(query, max_results=max_results):
            yield doc

    # ── Internal Methods ─────────────────────────────────────────────────

    async def _esearch(
        self,
        query: str,
        max_results: int,
        date_range: tuple[str, str] | None = None,
    ) -> list[str]:
        """Execute an esearch and return a list of PMIDs."""
        params = {
            **self._base_params(),
            "db": "pubmed",
            "term": query,
            "retmax": str(min(max_results, 10000)),
            "retmode": "json",
            "sort": "relevance",
        }
        if date_range:
            params["mindate"] = date_range[0]
            params["maxdate"] = date_range[1]
            params["datetype"] = "pdat"

        try:
            data = await self._get(
                f"{self.base_url}/esearch.fcgi", params=params
            )
            if data is None:
                return []
            return data.get("esearchresult", {}).get("idlist", [])
        except Exception:
            logger.exception("PubMed esearch failed for query: %s", query)
            return []

    async def _efetch_batch(self, pmids: list[str]) -> list[RawDocument]:
        """Fetch full article records for a batch of PMIDs via efetch XML."""
        params = {
            **self._base_params(),
            "db": "pubmed",
            "id": ",".join(pmids),
            "rettype": "xml",
            "retmode": "xml",
        }

        try:
            xml_text = await self._get_text(
                f"{self.base_url}/efetch.fcgi", params=params
            )
            if xml_text is None:
                return []
            return self._parse_pubmed_xml(xml_text)
        except Exception:
            logger.exception(
                "PubMed efetch failed for PMIDs: %s", pmids[:5]
            )
            self._stats.documents_failed += len(pmids)
            return []

    def _parse_pubmed_xml(self, xml_text: str) -> list[RawDocument]:
        """Parse PubMed efetch XML response into RawDocument list."""
        documents = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            logger.error("Failed to parse PubMed XML response")
            return []

        for article_el in root.findall(".//PubmedArticle"):
            try:
                doc = self._parse_article(article_el)
                if doc:
                    documents.append(doc)
                    self._stats.documents_fetched += 1
            except Exception:
                logger.exception("Failed to parse PubMed article")
                self._stats.documents_failed += 1

        return documents

    def _parse_article(self, article_el: ET.Element) -> RawDocument | None:
        """Parse a single PubmedArticle XML element."""
        medline = article_el.find(".//MedlineCitation")
        if medline is None:
            return None

        # PMID
        pmid_el = medline.find(".//PMID")
        pmid = pmid_el.text if pmid_el is not None else ""
        if not pmid:
            return None

        article = medline.find(".//Article")
        if article is None:
            return None

        # Title
        title_el = article.find(".//ArticleTitle")
        title = self._get_text_content(title_el)
        if not title:
            return None

        # Abstract
        abstract_parts = []
        abstract_el = article.find(".//Abstract")
        if abstract_el is not None:
            for abs_text in abstract_el.findall(".//AbstractText"):
                label = abs_text.get("Label", "")
                text = self._get_text_content(abs_text)
                if text:
                    if label:
                        abstract_parts.append(f"{label}: {text}")
                    else:
                        abstract_parts.append(text)
        abstract = " ".join(abstract_parts) if abstract_parts else None

        # Authors
        authors = []
        author_list = article.find(".//AuthorList")
        if author_list is not None:
            for author_el in author_list.findall("Author"):
                last = author_el.findtext("LastName", "")
                first = author_el.findtext("ForeName", "")
                if last:
                    authors.append(f"{first} {last}".strip())

        # Publication date
        pub_date = self._extract_pub_date(article)

        # Journal
        journal_el = article.find(".//Journal/Title")
        journal = journal_el.text if journal_el is not None else ""

        # DOI
        doi = ""
        for eid in article_el.findall(
            ".//PubmedData/ArticleIdList/ArticleId"
        ):
            if eid.get("IdType") == "doi":
                doi = eid.text or ""
                break

        # MeSH keywords
        keywords = []
        for mesh in medline.findall(".//MeshHeadingList/MeshHeading"):
            desc = mesh.find("DescriptorName")
            if desc is not None and desc.text:
                keywords.append(desc.text)

        return RawDocument(
            source_id=f"PMID:{pmid}",
            source_type=self.SOURCE_TYPE,
            title=title,
            abstract=abstract,
            authors=authors,
            publication_date=pub_date,
            keywords=keywords,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            metadata={
                "pmid": pmid,
                "doi": doi,
                "journal": journal,
            },
            raw_response={},  # Omit raw XML to save memory
        )

    @staticmethod
    def _get_text_content(element: ET.Element | None) -> str:
        """Extract all text content from an XML element, including children."""
        if element is None:
            return ""
        return "".join(element.itertext()).strip()

    @staticmethod
    def _extract_pub_date(article: ET.Element) -> str | None:
        """Extract publication date in ISO format."""
        for date_path in [
            ".//Journal/JournalIssue/PubDate",
            ".//ArticleDate",
        ]:
            date_el = article.find(date_path)
            if date_el is not None:
                year = date_el.findtext("Year", "")
                month = date_el.findtext("Month", "01")
                day = date_el.findtext("Day", "01")
                if year:
                    # Normalize month names to numbers
                    month_map = {
                        "jan": "01", "feb": "02", "mar": "03",
                        "apr": "04", "may": "05", "jun": "06",
                        "jul": "07", "aug": "08", "sep": "09",
                        "oct": "10", "nov": "11", "dec": "12",
                    }
                    month = month_map.get(month.lower()[:3], month)
                    try:
                        return f"{year}-{int(month):02d}-{int(day):02d}"
                    except (ValueError, TypeError):
                        return f"{year}-01-01"
        return None
