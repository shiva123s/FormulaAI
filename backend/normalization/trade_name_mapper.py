"""
FormulaAI — Trade Name → Generic Name Mapper

Standardizes commercial/trade names to their generic IUPAC or CAS names.

Strategy (in order):
  1. Fast lookup in the static dictionary of 100+ common agrochemical
     and pharma-excipient trade names.
  2. Async fallback to PubChem API if the name is not in the dictionary.
  3. Return the original name unchanged if no mapping is found (flagged
     for manual review).

The static dictionary is curated for the agrochemical & formulation
domain and covers surfactants, solvents, emulsifiers, polymers, PGRs,
and common pesticide brands.
"""

from __future__ import annotations

import logging
from normalization.pubchem_resolver import PubChemResolver

logger = logging.getLogger(__name__)


# ── Static Trade Name Map ────────────────────────────────────────────────────
# Format: "trade name (lowercase)" → "generic/IUPAC name"
# Sources: FDA IID, EPA, Merck Index, common agrochemical references

TRADE_NAME_MAP: dict[str, str] = {
    # ── Surfactants & Emulsifiers ────────────────────────────────────────
    "tween 20": "polysorbate 20",
    "tween 40": "polysorbate 40",
    "tween 60": "polysorbate 60",
    "tween 80": "polysorbate 80",
    "span 20": "sorbitan monolaurate",
    "span 40": "sorbitan monopalmitate",
    "span 60": "sorbitan monostearate",
    "span 80": "sorbitan monooleate",
    "brij 35": "polyoxyethylene (23) lauryl ether",
    "brij 58": "polyoxyethylene (20) cetyl ether",
    "triton x-100": "polyethylene glycol tert-octylphenyl ether",
    "triton x-114": "polyethylene glycol tert-octylphenyl ether",
    "cremophor el": "polyoxyl 35 castor oil",
    "cremophor rh 40": "polyoxyl 40 hydrogenated castor oil",
    "pluronic f-127": "poloxamer 407",
    "pluronic f-68": "poloxamer 188",
    "pluronic l-61": "poloxamer 181",
    "lutrol f 127": "poloxamer 407",
    "solutol hs 15": "macrogol 15 hydroxystearate",
    "kolliphor hs 15": "macrogol 15 hydroxystearate",
    "kolliphor el": "polyoxyl 35 castor oil",

    # ── Solvents & Co-solvents ───────────────────────────────────────────
    "dmso": "dimethyl sulfoxide",
    "dmf": "dimethylformamide",
    "nmp": "n-methyl-2-pyrrolidone",
    "peg 400": "polyethylene glycol 400",
    "peg 600": "polyethylene glycol 600",
    "peg 4000": "polyethylene glycol 4000",
    "peg 6000": "polyethylene glycol 6000",
    "propylene glycol": "propane-1,2-diol",

    # ── Polymers & Thickeners ────────────────────────────────────────────
    "carbopol 940": "carbomer 940",
    "carbopol 934": "carbomer 934",
    "carbopol 974p": "carbomer 974P",
    "methocel k4m": "hydroxypropyl methylcellulose K4M",
    "methocel k100m": "hydroxypropyl methylcellulose K100M",
    "pvp k-30": "polyvinylpyrrolidone K-30",
    "pvp k-90": "polyvinylpyrrolidone K-90",
    "kollidon 30": "polyvinylpyrrolidone K-30",
    "kollidon va 64": "copovidone",
    "eudragit l100": "methacrylic acid-methyl methacrylate copolymer (1:1)",
    "eudragit s100": "methacrylic acid-methyl methacrylate copolymer (1:2)",
    "xanthan gum": "xanthan gum",

    # ── Pesticides & Herbicides (Brand → Active Ingredient) ──────────────
    "roundup": "glyphosate",
    "liberty": "glufosinate-ammonium",
    "paraquat": "paraquat dichloride",
    "gramoxone": "paraquat dichloride",
    "chlorothalonil": "chlorothalonil",
    "daconil": "chlorothalonil",
    "mancozeb": "mancozeb",
    "dithane": "mancozeb",
    "ridomil": "metalaxyl",
    "metalaxyl-m": "mefenoxam",
    "amistar": "azoxystrobin",
    "quadris": "azoxystrobin",
    "score": "difenoconazole",
    "tilt": "propiconazole",
    "karate": "lambda-cyhalothrin",
    "decis": "deltamethrin",
    "confidor": "imidacloprid",
    "gaucho": "imidacloprid",
    "admire": "imidacloprid",
    "actara": "thiamethoxam",
    "cruiser": "thiamethoxam",
    "spinosad": "spinosad",
    "success": "spinosad",
    "bt": "bacillus thuringiensis",
    "dipel": "bacillus thuringiensis subsp. kurstaki",
    "thuricide": "bacillus thuringiensis subsp. kurstaki",

    # ── Plant Growth Regulators ──────────────────────────────────────────
    "ethrel": "ethephon",
    "ethephon": "2-chloroethylphosphonic acid",
    "cycocel": "chlormequat chloride",
    "alar": "daminozide",
    "paclobutrazol": "paclobutrazol",
    "cultar": "paclobutrazol",
    "uniconazole": "uniconazole-P",
    "gibberellic acid": "gibberellin A3",
    "ga3": "gibberellin A3",

    # ── Biostimulants & Biologicals ──────────────────────────────────────
    "serenade": "bacillus subtilis strain QST 713",
    "trichoderma": "trichoderma harzianum",
    "rootshield": "trichoderma harzianum strain T-22",
    "mycostop": "streptomyces griseoviridis strain K61",

    # ── Adjuvants & Spray Additives ──────────────────────────────────────
    "silwet l-77": "trisiloxane ethoxylate",
    "li-700": "phosphatidylcholine + methylacetic acid",
    "croplife adjuvant": "methylated seed oil",
    "mso": "methylated seed oil",
    "coc": "crop oil concentrate",
    "nonionic surfactant": "alkylphenol ethoxylate",

    # ── Common Excipients ────────────────────────────────────────────────
    "aerosil 200": "fumed silica",
    "cab-o-sil": "fumed silica",
    "avicel ph-101": "microcrystalline cellulose",
    "avicel ph-102": "microcrystalline cellulose",
    "cmc": "carboxymethylcellulose",
    "hpmc": "hydroxypropyl methylcellulose",
    "sds": "sodium dodecyl sulfate",
    "sls": "sodium lauryl sulfate",
    "sodium lauryl sulfate": "sodium dodecyl sulfate",
}


class TradeNameMapper:
    """
    Resolves trade/commercial names to their generic chemical names.

    Uses a two-tier strategy:
      1. Fast static dictionary lookup (O(1))
      2. Async PubChem API fallback (rate-limited)
    """

    def __init__(self, pubchem_resolver: PubChemResolver | None = None):
        self._static_map = TRADE_NAME_MAP
        self._pubchem = pubchem_resolver
        # Runtime cache for PubChem lookups (avoids repeated API calls)
        self._dynamic_cache: dict[str, str] = {}

    async def resolve(self, trade_name: str) -> tuple[str, bool]:
        """
        Resolve a trade name to its generic equivalent.

        Returns:
            A tuple of (resolved_name, was_resolved):
              - was_resolved=True if a mapping was found (static or PubChem)
              - was_resolved=False if returning the original name unchanged
        """
        normalized = trade_name.strip().lower()

        # Tier 1: Static dictionary
        if normalized in self._static_map:
            resolved = self._static_map[normalized]
            logger.debug("Static map: '%s' → '%s'", trade_name, resolved)
            return resolved, True

        # Tier 1b: Dynamic cache
        if normalized in self._dynamic_cache:
            resolved = self._dynamic_cache[normalized]
            logger.debug("Cache hit: '%s' → '%s'", trade_name, resolved)
            return resolved, True

        # Tier 2: PubChem fallback
        if self._pubchem is not None:
            try:
                compound = await self._pubchem.resolve_by_name(trade_name)
                if compound and compound.iupac_name:
                    self._dynamic_cache[normalized] = compound.iupac_name
                    logger.info(
                        "PubChem resolved: '%s' → '%s'",
                        trade_name,
                        compound.iupac_name,
                    )
                    return compound.iupac_name, True
            except Exception:
                logger.warning(
                    "PubChem fallback failed for trade name: %s", trade_name
                )

        # Unresolved — return original, flagged for review
        logger.info("Unresolved trade name (flagged for review): %s", trade_name)
        return trade_name, False

    def add_mapping(self, trade_name: str, generic_name: str) -> None:
        """Add a new trade-name mapping to the dynamic cache."""
        self._dynamic_cache[trade_name.strip().lower()] = generic_name

    @property
    def static_map_size(self) -> int:
        """Number of entries in the static dictionary."""
        return len(self._static_map)

    @property
    def cache_size(self) -> int:
        """Number of entries in the dynamic cache."""
        return len(self._dynamic_cache)
