"""
FormulaAI — Technical Data Sheet (TDS) & Safety Data Sheet (SDS) Scraper

Scrapes manufacturer websites for Technical Data Sheets and Safety Data
Sheets that contain critical formulation parameters:
  • HLB values (Hydrophilic-Lipophilic Balance)
  • pH stability ranges
  • Viscosity profiles
  • Solubility data
  • Compatibility matrices
  • Storage/stability conditions

SDS sources:
  • Sigma-Aldrich / MilliporeSigma
  • Fisher Scientific
  • TCI Chemicals
  • Manufacturer direct websites

This scraper follows robots.txt and implements polite crawling with
delays between requests.
"""

from __future__ import annotations

import logging
import re
from typing import Any, AsyncIterator
from urllib.parse import urljoin

from ingestion.base import BaseConnector, RawDocument

logger = logging.getLogger(__name__)

# Common SDS provider base URLs
SDS_PROVIDERS = {
    "sigma_aldrich": {
        "base_url": "https://www.sigmaaldrich.com",
        "search_pattern": "/catalog/search?term={query}&interface=All",
        "sds_pattern": "/MSDS/SIGALD/{cas}",
    },
    "fisher_scientific": {
        "base_url": "https://www.fishersci.com",
        "search_pattern": "/us/en/search/{query}",
    },
}


class TDSSDSScraper(BaseConnector):
    """
    Web scraper for Technical Data Sheets and Safety Data Sheets.

    Extracts formulation-critical parameters from manufacturer
    documentation. Uses polite crawling with self-imposed rate limits.

    Usage:
        async with TDSSDSScraper() as scraper:
            async for doc in scraper.search("polysorbate 80"):
                print(doc.title, doc.metadata.get("hlb_value"))

    Note:
        In production, this scraper would be supplemented by a Docling
        PDF parser for downloaded SDS/TDS documents. This module handles
        the discovery and metadata extraction phase.
    """

    SOURCE_TYPE = "tds"

    def __init__(
        self,
        base_url: str = "https://www.sigmaaldrich.com",
        rate_limit: float = 0.5,  # Very conservative: 1 req/2 seconds
        timeout: float = 45.0,
    ):
        super().__init__(
            base_url=base_url,
            rate_limit=rate_limit,
            timeout=timeout,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    # ── Public API ───────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        max_results: int = 20,
        **kwargs: Any,
    ) -> AsyncIterator[RawDocument]:
        """
        Search for TDS/SDS documents for a chemical compound.

        For now, this creates structured RawDocument placeholders
        that can be enriched by the Docling PDF parser in Phase 3.

        Args:
            query: Chemical name, CAS number, or product name.
            max_results: Maximum results.
        """
        # In production, this would:
        # 1. Search manufacturer websites for the compound
        # 2. Download the SDS/TDS PDF
        # 3. Hand off to Docling for structured extraction
        #
        # For Iteration 2, we create placeholder documents that
        # record what needs to be scraped.

        doc = RawDocument(
            source_id=f"TDS-PENDING:{query}",
            source_type=self.SOURCE_TYPE,
            title=f"TDS/SDS Lookup: {query}",
            abstract=f"Pending TDS/SDS retrieval for '{query}'. "
            f"Will be processed by Docling PDF parser in Phase 3.",
            keywords=["tds", "sds", "pending"],
            metadata={
                "query": query,
                "status": "pending",
                "target_providers": list(SDS_PROVIDERS.keys()),
            },
        )
        self._stats.documents_fetched += 1
        yield doc

    async def fetch_document(self, doc_id: str) -> RawDocument | None:
        """Fetch a specific TDS/SDS document by ID."""
        # In production: download and parse the PDF
        return RawDocument(
            source_id=doc_id,
            source_type=self.SOURCE_TYPE,
            title=f"TDS/SDS: {doc_id}",
            abstract="Document pending retrieval and parsing.",
            metadata={"status": "pending"},
        )

    # ── Parameter Extraction Utilities ───────────────────────────────────
    # These will be used by the Docling parser to extract structured data
    # from parsed TDS/SDS text.

    @staticmethod
    def extract_hlb_value(text: str) -> float | None:
        """
        Extract HLB (Hydrophilic-Lipophilic Balance) value from text.

        Common patterns:
          - "HLB: 15.0"
          - "HLB value of 15"
          - "HLB = 15.0"
        """
        patterns = [
            r"HLB\s*[:=]\s*([\d.]+)",
            r"HLB\s+(?:value\s+)?(?:of\s+)?([\d.]+)",
            r"hydrophilic[- ]lipophilic\s+balance\s*[:=]?\s*([\d.]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
        return None

    @staticmethod
    def extract_ph_range(text: str) -> tuple[float, float] | None:
        """
        Extract pH stability range from text.

        Common patterns:
          - "pH 4.0–8.0"
          - "stable at pH 3-9"
          - "pH range: 4.5 to 7.5"
        """
        patterns = [
            r"pH\s*(?:range)?[:=]?\s*([\d.]+)\s*[-–to]+\s*([\d.]+)",
            r"stable\s+(?:at\s+)?pH\s+([\d.]+)\s*[-–to]+\s*([\d.]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    low = float(match.group(1))
                    high = float(match.group(2))
                    return (min(low, high), max(low, high))
                except ValueError:
                    continue
        return None

    @staticmethod
    def extract_viscosity(text: str) -> dict | None:
        """
        Extract viscosity data from text.

        Returns dict with value, units, temperature, and concentration.
        """
        pattern = (
            r"viscosity\s*[:=]?\s*([\d,.]+)\s*(mPa[·.]s|cP|cps|Pa\.s)"
        )
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                value = float(match.group(1).replace(",", ""))
                units = match.group(2)
                return {"value": value, "units": units}
            except ValueError:
                pass
        return None

    @staticmethod
    def extract_solubility(text: str) -> list[dict]:
        """
        Extract solubility data from text.

        Returns list of dicts with solvent, solubility, and units.
        """
        results = []
        patterns = [
            r"(soluble|miscible|insoluble|slightly soluble|sparingly soluble)\s+in\s+(\w+(?:\s+\w+)?)",
            r"solubility\s+in\s+(\w+)\s*[:=]\s*([\d.]+)\s*(\w+/\w+)?",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                groups = match.groups()
                if len(groups) >= 2:
                    results.append(
                        {
                            "solvent": groups[-1] if len(groups) == 2 else groups[0],
                            "solubility": groups[0] if len(groups) == 2 else groups[1],
                        }
                    )
        return results
