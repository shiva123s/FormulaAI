"""
FormulaAI — EPA INERTFinder API Wrapper

Queries the EPA's Inert Ingredient status for chemicals used in
pesticide formulations. The EPA classifies inert (now "other")
ingredients into lists that determine their regulatory status.

EPA Lists:
  • List 1:  Inerts of toxicological concern (restricted)
  • List 2:  Potentially toxic inerts (restricted)
  • List 3:  Inerts of unknown toxicity
  • List 4A: Minimal risk inerts (generally safe)
  • List 4B: Inerts with sufficient data

This connector wraps the EPA INERTFinder web interface.
When a formal API becomes available, this module will be updated.

Reference: https://www.epa.gov/pesticide-registration/inert-ingredients-overview
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from ingestion.base import BaseConnector, RawDocument

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InertStatus:
    """Regulatory classification of an inert ingredient."""

    ingredient_name: str
    cas_number: str | None = None
    epa_list: str | None = None         # "4A", "4B", "3", "2", "1"
    status: str | None = None           # "approved", "restricted", "unknown"
    use_limitations: str | None = None
    food_use_permitted: bool | None = None


# Curated EPA List 4A ingredients commonly used in agrochemical formulations
_EPA_LIST_4A_SEED: list[dict[str, Any]] = [
    {"name": "Polysorbate 20", "cas": "9005-64-5", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Polysorbate 80", "cas": "9005-65-6", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Glycerin", "cas": "56-81-5", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Propylene Glycol", "cas": "57-55-6", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Sorbitan Monooleate", "cas": "1338-43-8", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Sodium Lauryl Sulfate", "cas": "151-21-3", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Polyethylene Glycol 400", "cas": "25322-68-3", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Methylcellulose", "cas": "9004-67-5", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Xanthan Gum", "cas": "11138-66-2", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Lecithin", "cas": "8002-43-5", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Castor Oil", "cas": "8001-79-4", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Citric Acid", "cas": "77-92-9", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Sodium Bicarbonate", "cas": "144-55-8", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Sodium Chloride", "cas": "7647-14-5", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Silicon Dioxide", "cas": "7631-86-9", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Isopropyl Alcohol", "cas": "67-63-0", "list": "4A", "status": "approved", "food_use": False},
    {"name": "Ethanol", "cas": "64-17-5", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Mineral Oil", "cas": "8042-47-5", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Oleic Acid", "cas": "112-80-1", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Stearic Acid", "cas": "57-11-4", "list": "4A", "status": "approved", "food_use": True},
    {"name": "Dimethyl Sulfoxide", "cas": "67-68-5", "list": "3", "status": "unknown_toxicity", "food_use": False},
    {"name": "N-Methyl-2-Pyrrolidone", "cas": "872-50-4", "list": "2", "status": "restricted", "food_use": False},
]


class EPAInertConnector(BaseConnector):
    """
    Connector for EPA Inert Ingredient (INERTFinder) status lookups.

    Determines the regulatory classification of inert ingredients
    used in pesticide formulations.

    Usage:
        async with EPAInertConnector() as conn:
            status = await conn.check_status("Polysorbate 80")
            if status and status.epa_list == "4A":
                print("Approved for minimal-risk use")
    """

    SOURCE_TYPE = "regulatory"

    def __init__(
        self,
        base_url: str = "",
        rate_limit: float = 1.0,
        timeout: float = 30.0,
    ):
        super().__init__(
            base_url=base_url or "https://www.epa.gov",
            rate_limit=rate_limit,
            timeout=timeout,
        )
        self._status_cache: dict[str, InertStatus] = {}
        self._load_seed_data()

    def _load_seed_data(self) -> None:
        """Pre-populate cache with curated EPA List 4A data."""
        for entry in _EPA_LIST_4A_SEED:
            name_lower = entry["name"].lower()
            self._status_cache[name_lower] = InertStatus(
                ingredient_name=entry["name"],
                cas_number=entry.get("cas"),
                epa_list=entry.get("list"),
                status=entry.get("status"),
                food_use_permitted=entry.get("food_use"),
            )
        logger.info(
            "EPA INERTFinder: loaded %d seed entries", len(self._status_cache)
        )

    # ── Public API ───────────────────────────────────────────────────────

    async def check_status(self, ingredient_name: str) -> InertStatus | None:
        """
        Check the EPA regulatory status of an inert ingredient.

        Args:
            ingredient_name: Name of the ingredient.

        Returns:
            InertStatus record or None if not found.
        """
        normalized = ingredient_name.strip().lower()

        # Check cache first
        if normalized in self._status_cache:
            return self._status_cache[normalized]

        # In production: query the EPA INERTFinder web service
        # For now, return None for unknown ingredients
        logger.info(
            "EPA INERTFinder: no cached status for '%s' (flagged for lookup)",
            ingredient_name,
        )
        return None

    async def check_batch(
        self, ingredient_names: list[str]
    ) -> dict[str, InertStatus | None]:
        """Check EPA status for multiple ingredients."""
        results: dict[str, InertStatus | None] = {}
        for name in ingredient_names:
            results[name] = await self.check_status(name)
        return results

    async def search(
        self,
        query: str,
        max_results: int = 100,
        epa_list: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[RawDocument]:
        """
        Search for inert ingredients matching the query.

        Args:
            query: Ingredient name or partial name.
            max_results: Maximum results.
            epa_list: Filter by EPA list ("4A", "4B", "3", "2", "1").
        """
        query_lower = query.strip().lower()
        fetched = 0

        for key, status in self._status_cache.items():
            if fetched >= max_results:
                return
            if query_lower and query_lower not in key:
                continue
            if epa_list and status.epa_list != epa_list:
                continue

            doc = self._status_to_document(status)
            if doc:
                self._stats.documents_fetched += 1
                fetched += 1
                yield doc

    async def fetch_document(self, doc_id: str) -> RawDocument | None:
        """Fetch an ingredient by name."""
        status = await self.check_status(doc_id)
        if status is None:
            return None
        return self._status_to_document(status)

    async def get_approved_inerts(
        self, max_results: int = 100
    ) -> AsyncIterator[RawDocument]:
        """
        Yield all List 4A (minimal risk) approved inert ingredients.

        These are the safest ingredients for agrochemical formulations.
        """
        async for doc in self.search("", max_results=max_results, epa_list="4A"):
            yield doc

    # ── Parsing ──────────────────────────────────────────────────────────

    def _status_to_document(self, status: InertStatus) -> RawDocument | None:
        """Convert an InertStatus to a RawDocument."""
        try:
            abstract = (
                f"EPA classification: List {status.epa_list or 'Unknown'}. "
                f"Status: {status.status or 'unclassified'}. "
                f"Food use: {'permitted' if status.food_use_permitted else 'not permitted'}."
            )
            if status.cas_number:
                abstract += f" CAS: {status.cas_number}."
            if status.use_limitations:
                abstract += f" Limitations: {status.use_limitations}."

            return RawDocument(
                source_id=f"EPA-INERT:{status.ingredient_name}",
                source_type=self.SOURCE_TYPE,
                title=status.ingredient_name,
                abstract=abstract,
                keywords=[
                    f"EPA-List-{status.epa_list}" if status.epa_list else "EPA",
                    "inert ingredient",
                    "regulatory",
                ],
                url="https://www.epa.gov/pesticide-registration/inert-ingredients-overview",
                metadata={
                    "ingredient_name": status.ingredient_name,
                    "cas_number": status.cas_number,
                    "epa_list": status.epa_list,
                    "status": status.status,
                    "food_use_permitted": status.food_use_permitted,
                    "use_limitations": status.use_limitations,
                },
                raw_response={},
            )
        except Exception:
            logger.exception("Failed to convert InertStatus to document")
            self._stats.documents_failed += 1
            return None
