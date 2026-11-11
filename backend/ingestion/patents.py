"""
FormulaAI — Patent Connector (USPTO PatentsView + EPO OPS)

Searches and retrieves agrochemical patent data filtered by IPC codes:
  • A01N — Preservation of bodies of humans, animals, or plants;
            biocides; pest repellants; pesticides; herbicides
  • A01P — Biocidal activity of chemical compounds or preparations
  • C05G — Mixtures of fertilizers

Sources:
  1. USPTO PatentsView API (https://api.patentsview.org)
     - Free, no auth required
     - US patents with full metadata, claims, abstracts
  2. EPO Open Patent Services (https://ops.epo.org)
     - Requires registration (free tier available)
     - European and worldwide patents via DOCDB

API Docs:
  - PatentsView: https://patentsview.org/apis/api-endpoints
  - EPO OPS: https://www.epo.org/en/searching-for-patents/data/web-services/ops
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from ingestion.base import BaseConnector, RawDocument

logger = logging.getLogger(__name__)

# IPC codes for agrochemical patents
AGROCHEM_IPC_CODES = [
    "A01N",  # Biocides, pesticides, herbicides
    "A01P",  # Biocidal activity of compounds
    "C05G",  # Fertilizer mixtures
]

# PatentsView API v1 query schema
PATENTSVIEW_FIELDS = [
    "patent_id",
    "patent_title",
    "patent_abstract",
    "patent_date",
    "patent_type",
    "patent_num_claims",
]

PATENTSVIEW_INVENTOR_FIELDS = [
    "inventor_first_name",
    "inventor_last_name",
]

PATENTSVIEW_ASSIGNEE_FIELDS = [
    "assignee_organization",
]


class PatentConnector(BaseConnector):
    """
    Async connector for patent databases (USPTO PatentsView + EPO OPS).

    Primary search uses the PatentsView API. For each patent, extracts:
      • Patent ID, title, abstract
      • Filing/grant dates
      • Inventor names
      • Assignee organizations
      • IPC classifications

    Usage:
        async with PatentConnector() as conn:
            async for doc in conn.search("glyphosate surfactant"):
                print(doc.title)
    """

    SOURCE_TYPE = "patent"

    def __init__(
        self,
        base_url: str = "https://api.patentsview.org",
        rate_limit: float = 2.0,
        timeout: float = 45.0,
    ):
        super().__init__(
            base_url=base_url,
            rate_limit=rate_limit,
            timeout=timeout,
        )

    # ── Public API ───────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        max_results: int = 100,
        ipc_codes: list[str] | None = None,
        date_range: tuple[str, str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[RawDocument]:
        """
        Search USPTO patents via PatentsView API.

        Args:
            query: Text search query (searched in title + abstract).
            max_results: Maximum number of patents to yield.
            ipc_codes: IPC codes to filter by (defaults to AGROCHEM_IPC_CODES).
            date_range: Optional (start_date, end_date) in YYYY-MM-DD format.

        Yields:
            RawDocument for each matching patent.
        """
        codes = ipc_codes or AGROCHEM_IPC_CODES
        query_obj = self._build_query(query, codes, date_range)

        page = 1
        per_page = min(max_results, 100)
        fetched = 0

        while fetched < max_results:
            payload = {
                "q": query_obj,
                "f": PATENTSVIEW_FIELDS,
                "o": {
                    "page": page,
                    "per_page": per_page,
                },
                "s": [{"patent_date": "desc"}],
            }

            try:
                data = await self._post(
                    f"{self.base_url}/patents/query",
                    json_data=payload,
                )
            except Exception:
                logger.exception("PatentsView query failed on page %d", page)
                self._stats.documents_failed += 1
                break

            if data is None:
                break

            patents = data.get("patents", [])
            if not patents:
                break

            for patent in patents:
                if fetched >= max_results:
                    return
                doc = self._parse_patent(patent)
                if doc:
                    self._stats.documents_fetched += 1
                    fetched += 1
                    yield doc

            # Check if there are more pages
            total = data.get("total_patent_count", 0)
            if fetched >= total:
                break
            page += 1

        logger.info(
            "PatentsView: fetched %d patents for query '%s'", fetched, query
        )

    async def fetch_document(self, doc_id: str) -> RawDocument | None:
        """
        Fetch a single patent by its patent number.

        Args:
            doc_id: US patent number (e.g., "US10123456").
        """
        # Strip "US" prefix if present
        patent_num = doc_id.replace("US", "").strip()

        payload = {
            "q": {"patent_id": patent_num},
            "f": PATENTSVIEW_FIELDS,
        }

        try:
            data = await self._post(
                f"{self.base_url}/patents/query",
                json_data=payload,
            )
            if data is None:
                return None

            patents = data.get("patents", [])
            if not patents:
                return None

            doc = self._parse_patent(patents[0])
            if doc:
                self._stats.documents_fetched += 1
            return doc
        except Exception:
            logger.exception("Failed to fetch patent: %s", doc_id)
            self._stats.documents_failed += 1
            return None

    async def search_by_ipc(
        self,
        ipc_codes: list[str] | None = None,
        max_results: int = 100,
        from_date: str | None = None,
    ) -> AsyncIterator[RawDocument]:
        """
        Search patents by IPC classification codes only (no text query).

        Args:
            ipc_codes: IPC codes to search (defaults to AGROCHEM_IPC_CODES).
            max_results: Maximum patents to yield.
            from_date: Start date (YYYY-MM-DD) for date filtering.
        """
        date_range = (from_date, "") if from_date else None
        async for doc in self.search(
            query="",
            max_results=max_results,
            ipc_codes=ipc_codes,
            date_range=date_range,
        ):
            yield doc

    # ── Query Builder ────────────────────────────────────────────────────

    @staticmethod
    def _build_query(
        text_query: str,
        ipc_codes: list[str],
        date_range: tuple[str, str] | None = None,
    ) -> dict:
        """Build a PatentsView API query object."""
        conditions = []

        # IPC code filter (OR across codes)
        if ipc_codes:
            ipc_conditions = [
                {"_begins": {"cpc_subgroup_id": code}} for code in ipc_codes
            ]
            if len(ipc_conditions) == 1:
                conditions.append(ipc_conditions[0])
            else:
                conditions.append({"_or": ipc_conditions})

        # Text search in title and abstract
        if text_query:
            conditions.append(
                {
                    "_or": [
                        {"_text_any": {"patent_title": text_query}},
                        {"_text_any": {"patent_abstract": text_query}},
                    ]
                }
            )

        # Date range filter
        if date_range:
            start, end = date_range
            if start:
                conditions.append({"_gte": {"patent_date": start}})
            if end:
                conditions.append({"_lte": {"patent_date": end}})

        if not conditions:
            return {"_gte": {"patent_date": "2000-01-01"}}
        if len(conditions) == 1:
            return conditions[0]
        return {"_and": conditions}

    # ── Parsing ──────────────────────────────────────────────────────────

    def _parse_patent(self, patent: dict) -> RawDocument | None:
        """Convert a PatentsView patent JSON to a RawDocument."""
        try:
            patent_id = patent.get("patent_id", "")
            title = patent.get("patent_title", "")

            if not patent_id or not title:
                return None

            abstract = patent.get("patent_abstract", "")

            # Inventors
            authors = []
            for inv in patent.get("inventors", []):
                first = inv.get("inventor_first_name", "")
                last = inv.get("inventor_last_name", "")
                if last:
                    authors.append(f"{first} {last}".strip())

            # Assignees
            assignees = []
            for asg in patent.get("assignees", []):
                org = asg.get("assignee_organization", "")
                if org:
                    assignees.append(org)

            # IPC/CPC codes
            ipc_codes = []
            for cpc in patent.get("cpcs", []):
                code = cpc.get("cpc_subgroup_id", "")
                if code:
                    ipc_codes.append(code)

            return RawDocument(
                source_id=f"US{patent_id}",
                source_type=self.SOURCE_TYPE,
                title=title,
                abstract=abstract or None,
                authors=authors,
                publication_date=patent.get("patent_date"),
                keywords=ipc_codes,
                url=f"https://patents.google.com/patent/US{patent_id}",
                metadata={
                    "patent_id": patent_id,
                    "patent_type": patent.get("patent_type", ""),
                    "num_claims": patent.get("patent_num_claims", 0),
                    "assignees": assignees,
                    "ipc_codes": ipc_codes,
                },
                raw_response=patent,
            )
        except Exception:
            logger.exception("Failed to parse patent")
            self._stats.documents_failed += 1
            return None
