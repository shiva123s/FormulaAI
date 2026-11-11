"""
FormulaAI — ChEMBL REST API Connector

Queries the ChEMBL database (https://www.ebi.ac.uk/chembl/) for:
  • Bioactive molecules (compounds with measured activity data)
  • Drug delivery excipients repurposable for agrochemical use
  • Solubilizers, permeation enhancers, and surfactants
  • Bioactivity data (IC50, Ki, EC50) for toxicology screening

The ChEMBL database is curated by the EBI and contains 2.4M+ compounds
with 19M+ bioactivity measurements from 88K+ publications.

API Docs: https://chembl.gitbook.io/chembl-interface-documentation/web-services/chembl-data-web-services
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from ingestion.base import BaseConnector, RawDocument

logger = logging.getLogger(__name__)

# ChEMBL molecule types relevant to agrochemical formulations
RELEVANT_MOLECULE_TYPES = [
    "Small molecule",
    "Antibody",
    "Protein",
    "Oligosaccharide",
    "Enzyme",
    "Oligonucleotide",
]

# Target organism types for agrochemical screening
AGROCHEM_TARGET_ORGANISMS = [
    "Fungi",
    "Insecta",
    "Nematoda",
    "Plantae",
    "Bacteria",
]


class ChEMBLConnector(BaseConnector):
    """
    Async connector for the ChEMBL REST API.

    Searches for compounds, bioactivity data, and target information
    relevant to agrochemical formulation and excipient repurposing.

    Usage:
        async with ChEMBLConnector() as conn:
            async for doc in conn.search("surfactant solubilizer"):
                print(doc.title)
    """

    SOURCE_TYPE = "chembl"

    def __init__(
        self,
        base_url: str = "https://www.ebi.ac.uk/chembl/api/data",
        rate_limit: float = 15.0,
        timeout: float = 30.0,
    ):
        super().__init__(
            base_url=base_url,
            rate_limit=rate_limit,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    # ── Public API ───────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        max_results: int = 100,
        **kwargs: Any,
    ) -> AsyncIterator[RawDocument]:
        """
        Search ChEMBL for molecules matching the query.

        Args:
            query: Molecule name, synonym, or partial name.
            max_results: Maximum documents to yield.

        Yields:
            RawDocument for each matching molecule.
        """
        offset = 0
        limit = min(max_results, 20)
        fetched = 0

        while fetched < max_results:
            params = {
                "search": query,
                "limit": limit,
                "offset": offset,
                "format": "json",
            }

            try:
                data = await self._get(
                    f"{self.base_url}/molecule.json", params=params
                )
            except Exception:
                logger.exception("ChEMBL molecule search failed at offset %d", offset)
                break

            if data is None:
                break

            molecules = data.get("molecules", [])
            if not molecules:
                break

            for mol in molecules:
                if fetched >= max_results:
                    return
                doc = self._parse_molecule(mol)
                if doc:
                    self._stats.documents_fetched += 1
                    fetched += 1
                    yield doc

            # Check pagination
            page_meta = data.get("page_meta", {})
            if not page_meta.get("next"):
                break
            offset += limit

        logger.info(
            "ChEMBL: fetched %d molecules for query '%s'", fetched, query
        )

    async def fetch_document(self, doc_id: str) -> RawDocument | None:
        """
        Fetch a single molecule by its ChEMBL ID.

        Args:
            doc_id: ChEMBL ID (e.g., "CHEMBL25").
        """
        try:
            data = await self._get(f"{self.base_url}/molecule/{doc_id}.json")
            if data is None:
                return None
            doc = self._parse_molecule(data)
            if doc:
                self._stats.documents_fetched += 1
            return doc
        except Exception:
            logger.exception("Failed to fetch ChEMBL molecule: %s", doc_id)
            self._stats.documents_failed += 1
            return None

    async def fetch_bioactivities(
        self,
        chembl_id: str,
        max_results: int = 50,
    ) -> list[dict]:
        """
        Fetch bioactivity data (IC50, Ki, EC50) for a molecule.

        Args:
            chembl_id: ChEMBL molecule ID.
            max_results: Maximum activities to return.

        Returns:
            List of activity dicts with type, value, units, target.
        """
        params = {
            "molecule_chembl_id": chembl_id,
            "limit": max_results,
            "format": "json",
        }

        try:
            data = await self._get(
                f"{self.base_url}/activity.json", params=params
            )
            if data is None:
                return []

            activities = []
            for act in data.get("activities", []):
                activities.append(
                    {
                        "activity_id": act.get("activity_id"),
                        "type": act.get("standard_type", ""),
                        "value": act.get("standard_value"),
                        "units": act.get("standard_units", ""),
                        "relation": act.get("standard_relation", "="),
                        "target_name": act.get("target_pref_name", ""),
                        "target_organism": act.get("target_organism", ""),
                        "target_chembl_id": act.get("target_chembl_id", ""),
                        "assay_type": act.get("assay_type", ""),
                        "document_chembl_id": act.get("document_chembl_id", ""),
                    }
                )
            return activities
        except Exception:
            logger.exception(
                "Failed to fetch bioactivities for: %s", chembl_id
            )
            return []

    async def search_by_target_organism(
        self,
        organism: str,
        activity_type: str = "IC50",
        max_results: int = 100,
    ) -> AsyncIterator[RawDocument]:
        """
        Find molecules tested against a specific target organism.

        Useful for finding pesticides/fungicides/insecticides with known
        activity data against specific pest organisms.

        Args:
            organism: Target organism name (e.g., "Botrytis cinerea").
            activity_type: Activity measurement type (IC50, Ki, EC50).
            max_results: Maximum results.
        """
        params = {
            "target_organism__icontains": organism,
            "standard_type": activity_type,
            "limit": min(max_results, 20),
            "format": "json",
        }

        offset = 0
        fetched = 0

        while fetched < max_results:
            params["offset"] = offset
            try:
                data = await self._get(
                    f"{self.base_url}/activity.json", params=params
                )
            except Exception:
                break

            if data is None:
                break

            activities = data.get("activities", [])
            if not activities:
                break

            for act in activities:
                if fetched >= max_results:
                    return
                doc = self._parse_activity_as_document(act)
                if doc:
                    self._stats.documents_fetched += 1
                    fetched += 1
                    yield doc

            if not data.get("page_meta", {}).get("next"):
                break
            offset += len(activities)

    # ── Parsing ──────────────────────────────────────────────────────────

    def _parse_molecule(self, mol: dict) -> RawDocument | None:
        """Convert a ChEMBL molecule JSON to a RawDocument."""
        try:
            chembl_id = mol.get("molecule_chembl_id", "")
            pref_name = mol.get("pref_name", "") or ""
            mol_type = mol.get("molecule_type", "")

            # Extract structural data
            structures = mol.get("molecule_structures") or {}
            smiles = structures.get("canonical_smiles", "")
            inchi_key = structures.get("standard_inchi_key", "")

            # Properties
            properties = mol.get("molecule_properties") or {}

            title = pref_name or chembl_id
            abstract_parts = []
            if mol_type:
                abstract_parts.append(f"Type: {mol_type}")
            if smiles:
                abstract_parts.append(f"SMILES: {smiles}")
            if properties.get("full_mwt"):
                abstract_parts.append(f"MW: {properties['full_mwt']}")
            if properties.get("alogp"):
                abstract_parts.append(f"ALogP: {properties['alogp']}")

            return RawDocument(
                source_id=chembl_id,
                source_type=self.SOURCE_TYPE,
                title=title,
                abstract=" | ".join(abstract_parts) if abstract_parts else None,
                url=f"https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}/",
                keywords=[mol_type] if mol_type else [],
                metadata={
                    "chembl_id": chembl_id,
                    "pref_name": pref_name,
                    "molecule_type": mol_type,
                    "canonical_smiles": smiles,
                    "inchi_key": inchi_key,
                    "molecular_weight": properties.get("full_mwt"),
                    "alogp": properties.get("alogp"),
                    "hba": properties.get("hba"),
                    "hbd": properties.get("hbd"),
                    "psa": properties.get("psa"),
                    "num_ro5_violations": properties.get("num_ro5_violations"),
                    "max_phase": mol.get("max_phase"),
                    "first_approval": mol.get("first_approval"),
                    "oral": mol.get("oral"),
                    "topical": mol.get("topical"),
                },
                raw_response=mol,
            )
        except Exception:
            logger.exception("Failed to parse ChEMBL molecule")
            self._stats.documents_failed += 1
            return None

    def _parse_activity_as_document(self, act: dict) -> RawDocument | None:
        """Convert a ChEMBL activity record to a RawDocument."""
        try:
            mol_id = act.get("molecule_chembl_id", "")
            mol_name = act.get("molecule_pref_name", "") or mol_id
            target = act.get("target_pref_name", "")
            organism = act.get("target_organism", "")
            act_type = act.get("standard_type", "")
            act_value = act.get("standard_value", "")
            act_units = act.get("standard_units", "")

            title = f"{mol_name} — {act_type} against {target}"
            abstract = (
                f"{act_type}: {act_value} {act_units} | "
                f"Target: {target} ({organism}) | "
                f"Assay: {act.get('assay_type', '')}"
            )

            return RawDocument(
                source_id=f"{mol_id}_{act.get('activity_id', '')}",
                source_type=self.SOURCE_TYPE,
                title=title,
                abstract=abstract,
                metadata={
                    "molecule_chembl_id": mol_id,
                    "activity_type": act_type,
                    "activity_value": act_value,
                    "activity_units": act_units,
                    "target_name": target,
                    "target_organism": organism,
                    "smiles": act.get("canonical_smiles", ""),
                },
                raw_response=act,
            )
        except Exception:
            logger.exception("Failed to parse ChEMBL activity")
            self._stats.documents_failed += 1
            return None
