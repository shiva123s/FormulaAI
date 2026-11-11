"""
FormulaAI — NCBI Taxonomy Resolver

Asynchronously resolves organism names to NCBI Taxonomy IDs using the
NCBI E-Utilities API (esearch + esummary).

Required for biological agents: bacteria, fungi, viruses, and endophytes
extracted from patents and literature.

Docs: https://www.ncbi.nlm.nih.gov/books/NBK25500/
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import httpx
from aiolimiter import AsyncLimiter
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaxonomyRecord:
    """Resolved NCBI Taxonomy information for a biological agent."""

    taxonomy_id: int
    scientific_name: str
    common_name: str | None = None
    rank: str | None = None
    division: str | None = None
    lineage: str | None = None  # Semicolon-separated lineage string


class NCBITaxonomyResolver:
    """
    Async resolver for NCBI Taxonomy lookups via E-Utilities.

    Usage:
        resolver = NCBITaxonomyResolver(email="you@example.com")
        record = await resolver.resolve("Bacillus thuringiensis")
        await resolver.close()

    Or as an async context manager:
        async with NCBITaxonomyResolver(email="...") as resolver:
            record = await resolver.resolve("Trichoderma harzianum")
    """

    def __init__(
        self,
        email: str,
        api_key: str = "",
        base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        rate_limit: float = 3.0,
        timeout: float = 30.0,
    ):
        if not email:
            raise ValueError(
                "NCBI requires an email address for E-Utilities API access. "
                "Set NCBI_EMAIL in your .env file."
            )
        self.email = email
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._limiter = AsyncLimiter(
            max_rate=10.0 if api_key else rate_limit, time_period=1.0
        )
        self._client = httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self) -> NCBITaxonomyResolver:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ── Public API ───────────────────────────────────────────────────────

    async def resolve(self, organism_name: str) -> TaxonomyRecord | None:
        """
        Resolve an organism name to its NCBI Taxonomy record.

        Performs a two-step lookup:
          1. esearch → get taxonomy ID(s)
          2. esummary → get full record details

        Returns None if the organism is not found.
        """
        tax_id = await self._search(organism_name)
        if tax_id is None:
            logger.info("No NCBI Taxonomy match for: %s", organism_name)
            return None
        return await self._fetch_summary(tax_id)

    async def resolve_batch(
        self, organism_names: list[str]
    ) -> dict[str, TaxonomyRecord | None]:
        """Resolve multiple organism names. Returns a dict keyed by name."""
        results: dict[str, TaxonomyRecord | None] = {}
        for name in organism_names:
            results[name] = await self.resolve(name)
        return results

    # ── Internal Methods ─────────────────────────────────────────────────

    def _base_params(self) -> dict[str, str]:
        """Common query parameters for all E-Utilities requests."""
        params = {"email": self.email}
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _search(self, organism_name: str) -> int | None:
        """
        Use esearch to find the Taxonomy ID for an organism name.

        Returns the first matching taxonomy ID, or None.
        """
        params = {
            **self._base_params(),
            "db": "taxonomy",
            "term": organism_name,
            "retmode": "json",
            "retmax": "1",
        }
        try:
            async with self._limiter:
                resp = await self._client.get(
                    f"{self.base_url}/esearch.fcgi", params=params
                )
                resp.raise_for_status()

            data = resp.json()
            id_list = data.get("esearchresult", {}).get("idlist", [])
            if not id_list:
                return None
            return int(id_list[0])
        except (httpx.HTTPStatusError, httpx.TimeoutException):
            logger.warning("NCBI esearch failed for: %s", organism_name)
            return None
        except Exception:
            logger.exception("Unexpected error in NCBI esearch: %s", organism_name)
            return None

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _fetch_summary(self, taxonomy_id: int) -> TaxonomyRecord | None:
        """
        Use esummary to fetch detailed taxonomy information.

        Returns a TaxonomyRecord or None on failure.
        """
        params = {
            **self._base_params(),
            "db": "taxonomy",
            "id": str(taxonomy_id),
            "retmode": "json",
        }
        try:
            async with self._limiter:
                resp = await self._client.get(
                    f"{self.base_url}/esummary.fcgi", params=params
                )
                resp.raise_for_status()

            data = resp.json()
            result = data.get("result", {})
            record_data = result.get(str(taxonomy_id))

            if record_data is None:
                logger.warning(
                    "No esummary result for taxonomy ID %d", taxonomy_id
                )
                return None

            return TaxonomyRecord(
                taxonomy_id=taxonomy_id,
                scientific_name=record_data.get("scientificname", ""),
                common_name=record_data.get("commonname") or None,
                rank=record_data.get("rank") or None,
                division=record_data.get("division") or None,
                lineage=record_data.get("lineage") or None,
            )
        except (httpx.HTTPStatusError, httpx.TimeoutException):
            logger.warning(
                "NCBI esummary failed for taxonomy ID %d", taxonomy_id
            )
            return None
        except Exception:
            logger.exception(
                "Unexpected error in NCBI esummary for taxonomy ID %d",
                taxonomy_id,
            )
            return None
