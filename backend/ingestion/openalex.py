"""
FormulaAI — OpenAlex Works API Connector

Searches and retrieves scholarly works from the OpenAlex database
(https://docs.openalex.org/). Covers 250M+ works including all
major agrochemical, formulation, and biological sciences journals.

Features:
  • Concept/keyword search with agrochemical domain filters
  • Cursor-based pagination for large result sets
  • Polite pool access via email (10 req/s vs 1 req/s)
  • Full abstract and metadata extraction

API Docs: https://docs.openalex.org/api-entities/works
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from ingestion.base import BaseConnector, RawDocument

logger = logging.getLogger(__name__)

# OpenAlex concept IDs for agrochemical domain filtering
AGROCHEM_CONCEPTS = [
    "C71240020",   # Pesticide
    "C159654299",  # Herbicide
    "C2778407487",  # Fungicide
    "C2779433900",  # Insecticide
    "C2910814878",  # Biopesticide
    "C178790620",  # Agrochemistry
    "C159047783",  # Fertilizer
    "C55493867",   # Surfactant
    "C2776129985",  # Formulation
]

# Default search filters for agrochemical literature
DEFAULT_FILTER = "type:article,has_abstract:true"


class OpenAlexConnector(BaseConnector):
    """
    Async connector for the OpenAlex Works API.

    Usage:
        async with OpenAlexConnector(
            base_url="https://api.openalex.org",
            email="you@example.com",
        ) as conn:
            async for doc in conn.search("glyphosate surfactant formulation"):
                print(doc.title)
    """

    SOURCE_TYPE = "paper"

    def __init__(
        self,
        base_url: str = "https://api.openalex.org",
        email: str = "",
        rate_limit: float = 10.0,
        timeout: float = 30.0,
    ):
        headers = {}
        params_extra = {}
        if email:
            # Polite pool: higher rate limits
            headers["User-Agent"] = f"FormulaAI-DataFactory/1.0 (mailto:{email})"
            self._email = email
        else:
            logger.warning(
                "OpenAlex: No email provided. Using common pool (slower rate limits). "
                "Set OPENALEX_EMAIL in .env for polite pool access."
            )
            rate_limit = min(rate_limit, 1.0)
            self._email = ""

        super().__init__(
            base_url=base_url,
            rate_limit=rate_limit,
            timeout=timeout,
            headers=headers,
        )

    # ── Public API ───────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        max_results: int = 100,
        filter_str: str = DEFAULT_FILTER,
        sort: str = "relevance_score:desc",
        **kwargs: Any,
    ) -> AsyncIterator[RawDocument]:
        """
        Search OpenAlex for works matching the query.

        Args:
            query: Full-text search query (e.g., "glyphosate surfactant").
            max_results: Maximum number of documents to yield.
            filter_str: OpenAlex filter expression.
            sort: Sort order (default: relevance).

        Yields:
            RawDocument for each matching work.
        """
        url = f"{self.base_url}/works"
        params: dict[str, Any] = {
            "search": query,
            "filter": filter_str,
            "sort": sort,
            "per_page": min(max_results, 200),
            "cursor": "*",
        }

        if self._email:
            params["mailto"] = self._email

        fetched = 0
        async for batch in self._paginate(
            url=url,
            params=params,
            results_key="results",
            cursor_key="cursor",
            cursor_response_key="next_cursor",
            page_size=min(max_results, 200),
            max_pages=(max_results // 200) + 1,
        ):
            for work in batch:
                if fetched >= max_results:
                    return
                doc = self._parse_work(work)
                if doc is not None:
                    self._stats.documents_fetched += 1
                    fetched += 1
                    yield doc

    async def fetch_document(self, doc_id: str) -> RawDocument | None:
        """
        Fetch a single work by its OpenAlex ID or DOI.

        Args:
            doc_id: OpenAlex ID (e.g., "W2741809807") or DOI URL.
        """
        # OpenAlex accepts both W-ids and DOIs
        url = f"{self.base_url}/works/{doc_id}"
        params = {}
        if self._email:
            params["mailto"] = self._email

        try:
            data = await self._get(url, params=params)
            if data is None:
                return None
            doc = self._parse_work(data)
            if doc:
                self._stats.documents_fetched += 1
            return doc
        except Exception:
            logger.exception("Failed to fetch OpenAlex work: %s", doc_id)
            self._stats.documents_failed += 1
            return None

    async def search_by_concepts(
        self,
        concept_ids: list[str] | None = None,
        max_results: int = 100,
        from_date: str | None = None,
    ) -> AsyncIterator[RawDocument]:
        """
        Search by OpenAlex concept IDs (useful for broad topic sweeps).

        Args:
            concept_ids: List of OpenAlex concept IDs.
                         Defaults to AGROCHEM_CONCEPTS.
            max_results: Maximum documents to yield.
            from_date: ISO date string (e.g., "2020-01-01") for recency filter.
        """
        ids = concept_ids or AGROCHEM_CONCEPTS
        concept_filter = "|".join(ids)
        filter_parts = [f"concepts.id:{concept_filter}", "has_abstract:true"]
        if from_date:
            filter_parts.append(f"from_publication_date:{from_date}")

        async for doc in self.search(
            query="",
            max_results=max_results,
            filter_str=",".join(filter_parts),
            sort="publication_date:desc",
        ):
            yield doc

    # ── Parsing ──────────────────────────────────────────────────────────

    def _parse_work(self, work: dict) -> RawDocument | None:
        """Convert an OpenAlex work JSON object to a RawDocument."""
        try:
            openalex_id = work.get("id", "")
            doi = work.get("doi", "")
            title = work.get("title") or work.get("display_name", "")

            if not title:
                return None

            # Extract abstract from inverted index
            abstract = self._reconstruct_abstract(
                work.get("abstract_inverted_index")
            )

            # Authors
            authors = []
            for authorship in work.get("authorships", []):
                author = authorship.get("author", {})
                name = author.get("display_name")
                if name:
                    authors.append(name)

            # Keywords and concepts
            keywords = []
            for concept in work.get("concepts", []):
                name = concept.get("display_name")
                if name:
                    keywords.append(name)
            for kw in work.get("keywords", []):
                if isinstance(kw, dict):
                    keywords.append(kw.get("keyword", ""))
                elif isinstance(kw, str):
                    keywords.append(kw)

            # Publication date
            pub_date = work.get("publication_date")

            # PDF URL
            oa = work.get("open_access", {})
            pdf_url = oa.get("oa_url")

            # Primary location URL
            primary = work.get("primary_location", {}) or {}
            landing_url = primary.get("landing_page_url")

            return RawDocument(
                source_id=doi or openalex_id,
                source_type=self.SOURCE_TYPE,
                title=title,
                abstract=abstract,
                authors=authors,
                publication_date=pub_date,
                keywords=keywords,
                url=landing_url or doi,
                pdf_url=pdf_url,
                metadata={
                    "openalex_id": openalex_id,
                    "doi": doi,
                    "cited_by_count": work.get("cited_by_count", 0),
                    "type": work.get("type", ""),
                    "is_open_access": oa.get("is_oa", False),
                    "source": (primary.get("source", {}) or {}).get(
                        "display_name", ""
                    ),
                },
                raw_response=work,
            )
        except Exception:
            logger.exception("Failed to parse OpenAlex work")
            self._stats.documents_failed += 1
            return None

    @staticmethod
    def _reconstruct_abstract(
        inverted_index: dict[str, list[int]] | None,
    ) -> str | None:
        """
        Reconstruct abstract text from OpenAlex's inverted index format.

        OpenAlex stores abstracts as {word: [positions]} to save space.
        """
        if not inverted_index:
            return None
        try:
            # Find total length
            max_pos = 0
            for positions in inverted_index.values():
                for pos in positions:
                    if pos > max_pos:
                        max_pos = pos

            words = [""] * (max_pos + 1)
            for word, positions in inverted_index.items():
                for pos in positions:
                    words[pos] = word

            return " ".join(words).strip()
        except Exception:
            logger.debug("Failed to reconstruct abstract from inverted index")
            return None
