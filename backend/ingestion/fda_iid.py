"""
FormulaAI — FDA Inactive Ingredient Database (IID) Connector

Ingests the FDA's Inactive Ingredient Database, which lists excipients
that have been used in FDA-approved drug products. This is a critical
source for the pharma-to-agro excipient repurposing pipeline.

The IID provides:
  • Excipient name (trade and generic)
  • Route of administration
  • Dosage form
  • Maximum potency (concentration) used in approved products
  • CAS Number (when available)

Data Source: https://www.accessdata.fda.gov/scripts/cder/iig/
API: https://www.accessdata.fda.gov/scripts/cder/iig/index.cfm (web scrape)

Note: The FDA IID does not have a formal REST API. We scrape the search
interface or parse the downloadable dataset.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any, AsyncIterator

from ingestion.base import BaseConnector, RawDocument

logger = logging.getLogger(__name__)

# FDA IID downloadable dataset URL (CSV format)
FDA_IID_DOWNLOAD_URL = (
    "https://www.accessdata.fda.gov/scripts/cder/iig/index.cfm"
)

# Routes of administration relevant to agrochemical repurposing
# (topical, oral, and inhalation formulations share delivery challenges)
RELEVANT_ROUTES = [
    "TOPICAL",
    "ORAL",
    "INHALATION",
    "OPHTHALMIC",
    "TRANSDERMAL",
    "NASAL",
]

# Dosage form keywords relevant to agrochemical formulation
RELEVANT_DOSAGE_FORMS = [
    "EMULSION",
    "SUSPENSION",
    "SOLUTION",
    "GEL",
    "CREAM",
    "SPRAY",
    "POWDER",
    "GRANULE",
    "TABLET",
    "CAPSULE",
]


class FDAIIDConnector(BaseConnector):
    """
    Connector for the FDA Inactive Ingredient Database.

    Parses FDA IID data to identify excipients that can be repurposed
    for agrochemical formulations (surfactants, solubilizers, stabilizers).

    Usage:
        async with FDAIIDConnector() as conn:
            async for doc in conn.search("polysorbate"):
                print(doc.title, doc.metadata)
    """

    SOURCE_TYPE = "fda_iid"

    def __init__(
        self,
        base_url: str = "https://www.accessdata.fda.gov/scripts/cder/iig",
        rate_limit: float = 1.0,
        timeout: float = 60.0,
    ):
        super().__init__(
            base_url=base_url,
            rate_limit=rate_limit,
            timeout=timeout,
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
        self._cached_ingredients: list[dict] | None = None

    # ── Public API ───────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        max_results: int = 100,
        routes: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[RawDocument]:
        """
        Search for FDA-approved inactive ingredients (excipients).

        Args:
            query: Ingredient name or partial name to search for.
            max_results: Maximum results to yield.
            routes: Filter by route of administration (defaults to all).

        Yields:
            RawDocument for each matching ingredient.
        """
        ingredients = await self._load_ingredients()
        query_lower = query.strip().lower()
        target_routes = {r.upper() for r in (routes or RELEVANT_ROUTES)}

        fetched = 0
        for ingredient in ingredients:
            if fetched >= max_results:
                return

            name = ingredient.get("ingredient_name", "").lower()
            route = ingredient.get("route", "").upper()

            # Filter by query match and route
            if query_lower and query_lower not in name:
                continue
            if target_routes and route not in target_routes:
                continue

            doc = self._parse_ingredient(ingredient)
            if doc:
                self._stats.documents_fetched += 1
                fetched += 1
                yield doc

    async def fetch_document(self, doc_id: str) -> RawDocument | None:
        """
        Fetch a single ingredient by its name.

        Args:
            doc_id: Ingredient name (exact match preferred).
        """
        ingredients = await self._load_ingredients()
        doc_id_lower = doc_id.strip().lower()

        for ingredient in ingredients:
            name = ingredient.get("ingredient_name", "").lower()
            if name == doc_id_lower:
                return self._parse_ingredient(ingredient)
        return None

    async def get_all_surfactants(
        self, max_results: int = 500
    ) -> AsyncIterator[RawDocument]:
        """
        Retrieve all surfactant-like excipients from the FDA IID.

        Searches for common surfactant keywords to identify excipients
        that could serve as agrochemical adjuvants.
        """
        surfactant_keywords = [
            "polysorbate",
            "sorbitan",
            "polyethylene glycol",
            "poloxamer",
            "sodium lauryl",
            "sodium dodecyl",
            "cetyl",
            "stearyl",
            "oleate",
            "laurate",
            "surfactant",
            "emulsifier",
        ]

        seen_names: set[str] = set()
        fetched = 0

        for keyword in surfactant_keywords:
            if fetched >= max_results:
                return
            async for doc in self.search(keyword, max_results=max_results - fetched):
                if doc.title.lower() not in seen_names:
                    seen_names.add(doc.title.lower())
                    fetched += 1
                    yield doc

    # ── Internal Methods ─────────────────────────────────────────────────

    async def _load_ingredients(self) -> list[dict]:
        """
        Load the FDA IID ingredient list.

        Uses an in-memory cache to avoid re-fetching on every search.
        In production, this would be replaced with a proper dataset
        download + local database.
        """
        if self._cached_ingredients is not None:
            return self._cached_ingredients

        # For now, return a curated seed list of common excipients
        # In production, this would scrape the FDA IID or parse
        # the downloadable dataset
        self._cached_ingredients = self._get_seed_data()
        logger.info(
            "FDA IID: loaded %d seed ingredients", len(self._cached_ingredients)
        )
        return self._cached_ingredients

    @staticmethod
    def _get_seed_data() -> list[dict]:
        """
        Return a curated seed dataset of common FDA-approved excipients
        relevant to agrochemical formulation repurposing.

        This serves as the initial dataset. The full FDA IID dataset
        (~13,000 entries) will be ingested via bulk download in Phase 3.
        """
        return [
            {"ingredient_name": "Polysorbate 20", "route": "TOPICAL", "dosage_form": "EMULSION", "max_potency": "5%", "cas_number": "9005-64-5"},
            {"ingredient_name": "Polysorbate 80", "route": "ORAL", "dosage_form": "SOLUTION", "max_potency": "4%", "cas_number": "9005-65-6"},
            {"ingredient_name": "Sodium Lauryl Sulfate", "route": "TOPICAL", "dosage_form": "CREAM", "max_potency": "2%", "cas_number": "151-21-3"},
            {"ingredient_name": "Polyethylene Glycol 400", "route": "ORAL", "dosage_form": "SOLUTION", "max_potency": "50%", "cas_number": "25322-68-3"},
            {"ingredient_name": "Polyethylene Glycol 4000", "route": "ORAL", "dosage_form": "POWDER", "max_potency": "100%", "cas_number": "25322-68-3"},
            {"ingredient_name": "Poloxamer 188", "route": "ORAL", "dosage_form": "SOLUTION", "max_potency": "0.5%", "cas_number": "9003-11-6"},
            {"ingredient_name": "Poloxamer 407", "route": "TOPICAL", "dosage_form": "GEL", "max_potency": "25%", "cas_number": "9003-11-6"},
            {"ingredient_name": "Sorbitan Monooleate", "route": "TOPICAL", "dosage_form": "EMULSION", "max_potency": "5%", "cas_number": "1338-43-8"},
            {"ingredient_name": "Propylene Glycol", "route": "TOPICAL", "dosage_form": "SOLUTION", "max_potency": "50%", "cas_number": "57-55-6"},
            {"ingredient_name": "Dimethyl Sulfoxide", "route": "TOPICAL", "dosage_form": "SOLUTION", "max_potency": "90%", "cas_number": "67-68-5"},
            {"ingredient_name": "Glycerin", "route": "ORAL", "dosage_form": "SOLUTION", "max_potency": "50%", "cas_number": "56-81-5"},
            {"ingredient_name": "Carboxymethylcellulose Sodium", "route": "ORAL", "dosage_form": "SUSPENSION", "max_potency": "2.5%", "cas_number": "9004-32-4"},
            {"ingredient_name": "Hydroxypropyl Methylcellulose", "route": "ORAL", "dosage_form": "TABLET", "max_potency": "30%", "cas_number": "9004-65-3"},
            {"ingredient_name": "Microcrystalline Cellulose", "route": "ORAL", "dosage_form": "TABLET", "max_potency": "90%", "cas_number": "9004-34-6"},
            {"ingredient_name": "Xanthan Gum", "route": "ORAL", "dosage_form": "SUSPENSION", "max_potency": "1%", "cas_number": "11138-66-2"},
            {"ingredient_name": "Sodium Alginate", "route": "ORAL", "dosage_form": "SUSPENSION", "max_potency": "10%", "cas_number": "9005-38-3"},
            {"ingredient_name": "Methylcellulose", "route": "ORAL", "dosage_form": "SOLUTION", "max_potency": "5%", "cas_number": "9004-67-5"},
            {"ingredient_name": "Polyvinylpyrrolidone K-30", "route": "ORAL", "dosage_form": "TABLET", "max_potency": "15%", "cas_number": "9003-39-8"},
            {"ingredient_name": "Polyvinyl Alcohol", "route": "OPHTHALMIC", "dosage_form": "SOLUTION", "max_potency": "1.4%", "cas_number": "9002-89-5"},
            {"ingredient_name": "Benzalkonium Chloride", "route": "OPHTHALMIC", "dosage_form": "SOLUTION", "max_potency": "0.02%", "cas_number": "63449-41-2"},
            {"ingredient_name": "Cetyl Alcohol", "route": "TOPICAL", "dosage_form": "CREAM", "max_potency": "8%", "cas_number": "36653-82-4"},
            {"ingredient_name": "Stearic Acid", "route": "TOPICAL", "dosage_form": "CREAM", "max_potency": "15%", "cas_number": "57-11-4"},
            {"ingredient_name": "Lecithin", "route": "ORAL", "dosage_form": "CAPSULE", "max_potency": "76%", "cas_number": "8002-43-5"},
            {"ingredient_name": "Oleic Acid", "route": "TOPICAL", "dosage_form": "CREAM", "max_potency": "25%", "cas_number": "112-80-1"},
            {"ingredient_name": "Triethyl Citrate", "route": "ORAL", "dosage_form": "TABLET", "max_potency": "7%", "cas_number": "77-93-0"},
            {"ingredient_name": "Castor Oil", "route": "ORAL", "dosage_form": "CAPSULE", "max_potency": "100%", "cas_number": "8001-79-4"},
            {"ingredient_name": "Fumed Silica", "route": "ORAL", "dosage_form": "POWDER", "max_potency": "2%", "cas_number": "112945-52-5"},
        ]

    def _parse_ingredient(self, ingredient: dict) -> RawDocument | None:
        """Convert an FDA IID ingredient record to a RawDocument."""
        try:
            name = ingredient.get("ingredient_name", "")
            if not name:
                return None

            route = ingredient.get("route", "")
            dosage = ingredient.get("dosage_form", "")
            potency = ingredient.get("max_potency", "")
            cas = ingredient.get("cas_number", "")

            abstract = (
                f"FDA-approved inactive ingredient. "
                f"Route: {route}. Dosage form: {dosage}. "
                f"Max potency: {potency}."
            )
            if cas:
                abstract += f" CAS: {cas}."

            return RawDocument(
                source_id=f"FDA-IID:{name}:{route}:{dosage}",
                source_type=self.SOURCE_TYPE,
                title=name,
                abstract=abstract,
                keywords=[route, dosage, "excipient", "FDA-approved"],
                url="https://www.accessdata.fda.gov/scripts/cder/iig/",
                metadata={
                    "ingredient_name": name,
                    "route": route,
                    "dosage_form": dosage,
                    "max_potency": potency,
                    "cas_number": cas,
                    "repurposable": True,
                },
                raw_response=ingredient,
            )
        except Exception:
            logger.exception("Failed to parse FDA IID ingredient")
            self._stats.documents_failed += 1
            return None
