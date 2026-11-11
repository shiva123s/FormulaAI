"""
FormulaAI — PubChem REST API Resolver

Asynchronously resolves chemical names and SMILES to canonical identifiers:
  • CAS Registry Number
  • Canonical SMILES
  • IUPAC Name
  • Molecular Formula / Weight
  • Synonyms

Uses the PubChem PUG REST API:
  https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest

All external calls are rate-limited (default 5 req/s) and retried on
transient failures with exponential backoff.
"""

from __future__ import annotations

import logging
import re
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

# CAS numbers follow the pattern: 2-7 digits, dash, 2 digits, dash, 1 digit
_CAS_PATTERN = re.compile(r"^\d{2,7}-\d{2}-\d$")


@dataclass(frozen=True)
class PubChemCompound:
    """Resolved compound data from PubChem."""

    cid: int
    name: str
    iupac_name: str | None = None
    canonical_smiles: str | None = None
    cas_number: str | None = None
    molecular_formula: str | None = None
    molecular_weight: float | None = None
    synonyms: tuple[str, ...] = field(default_factory=tuple)


class PubChemResolver:
    """
    Async resolver that queries PubChem PUG REST for compound identification.

    Usage:
        resolver = PubChemResolver(base_url="https://pubchem.ncbi.nlm.nih.gov/rest/pug")
        compound = await resolver.resolve_by_name("Glyphosate")
        await resolver.close()

    Or as an async context manager:
        async with PubChemResolver(...) as resolver:
            compound = await resolver.resolve_by_name("Glyphosate")
    """

    def __init__(
        self,
        base_url: str = "https://pubchem.ncbi.nlm.nih.gov/rest/pug",
        rate_limit: float = 5.0,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._limiter = AsyncLimiter(max_rate=rate_limit, time_period=1.0)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    async def __aenter__(self) -> PubChemResolver:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ── Public API ───────────────────────────────────────────────────────

    async def resolve_by_name(self, name: str) -> PubChemCompound | None:
        """
        Resolve a compound by its common/trade/IUPAC name.

        Returns None if the compound is not found or an error occurs.
        """
        cid = await self._search_cid_by_name(name)
        if cid is None:
            return None
        return await self._build_compound(cid, original_name=name)

    async def resolve_by_smiles(self, smiles: str) -> PubChemCompound | None:
        """Resolve a compound by its SMILES string."""
        cid = await self._search_cid_by_smiles(smiles)
        if cid is None:
            return None
        return await self._build_compound(cid, original_name=smiles)

    async def resolve_by_cas(self, cas_number: str) -> PubChemCompound | None:
        """Resolve a compound by its CAS Registry Number."""
        # PubChem treats CAS as a synonym/name
        return await self.resolve_by_name(cas_number)

    # ── Internal Methods ─────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _get(self, url: str) -> dict | None:
        """Rate-limited GET request with retry logic."""
        async with self._limiter:
            logger.debug("PubChem GET: %s", url)
            resp = await self._client.get(url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def _search_cid_by_name(self, name: str) -> int | None:
        """Search PubChem for a compound CID by name."""
        url = f"{self.base_url}/compound/name/{httpx.URL(name).raw_path.decode() if False else name}/cids/JSON"
        # Safer URL construction
        url = f"{self.base_url}/compound/name/{name}/cids/JSON"
        try:
            data = await self._get(url)
            if data is None:
                return None
            cids = data.get("IdentifierList", {}).get("CID", [])
            return cids[0] if cids else None
        except (httpx.HTTPStatusError, httpx.TimeoutException):
            logger.warning("PubChem name lookup failed for: %s", name)
            return None
        except Exception:
            logger.exception("Unexpected error in PubChem name lookup: %s", name)
            return None

    async def _search_cid_by_smiles(self, smiles: str) -> int | None:
        """Search PubChem for a compound CID by SMILES."""
        url = f"{self.base_url}/compound/smiles/cids/JSON"
        try:
            async with self._limiter:
                resp = await self._client.post(url, data={"smiles": smiles})
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                data = resp.json()
                cids = data.get("IdentifierList", {}).get("CID", [])
                return cids[0] if cids else None
        except Exception:
            logger.warning("PubChem SMILES lookup failed for: %s", smiles)
            return None

    async def _get_properties(self, cid: int) -> dict | None:
        """Fetch compound properties by CID."""
        props = "IUPACName,CanonicalSMILES,MolecularFormula,MolecularWeight"
        url = f"{self.base_url}/compound/cid/{cid}/property/{props}/JSON"
        try:
            data = await self._get(url)
            if data is None:
                return None
            rows = data.get("PropertyTable", {}).get("Properties", [])
            return rows[0] if rows else None
        except Exception:
            logger.warning("PubChem property fetch failed for CID %d", cid)
            return None

    async def _get_synonyms(self, cid: int, max_synonyms: int = 50) -> list[str]:
        """Fetch compound synonyms by CID."""
        url = f"{self.base_url}/compound/cid/{cid}/synonyms/JSON"
        try:
            data = await self._get(url)
            if data is None:
                return []
            info_list = data.get("InformationList", {}).get("Information", [])
            if not info_list:
                return []
            synonyms = info_list[0].get("Synonym", [])
            return synonyms[:max_synonyms]
        except Exception:
            logger.warning("PubChem synonym fetch failed for CID %d", cid)
            return []

    @staticmethod
    def _extract_cas_from_synonyms(synonyms: list[str]) -> str | None:
        """Extract the first CAS Registry Number from a list of synonyms."""
        for syn in synonyms:
            if _CAS_PATTERN.match(syn.strip()):
                return syn.strip()
        return None

    async def _build_compound(
        self, cid: int, original_name: str
    ) -> PubChemCompound | None:
        """Assemble a PubChemCompound from properties + synonyms."""
        props = await self._get_properties(cid)
        synonyms = await self._get_synonyms(cid)

        if props is None:
            return PubChemCompound(cid=cid, name=original_name)

        cas_number = self._extract_cas_from_synonyms(synonyms)

        mw_raw = props.get("MolecularWeight")
        mw = float(mw_raw) if mw_raw is not None else None

        return PubChemCompound(
            cid=cid,
            name=original_name,
            iupac_name=props.get("IUPACName"),
            canonical_smiles=props.get("CanonicalSMILES"),
            cas_number=cas_number,
            molecular_formula=props.get("MolecularFormula"),
            molecular_weight=mw,
            synonyms=tuple(synonyms),
        )
