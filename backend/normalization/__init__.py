"""
FormulaAI — Chemical & Biological Normalization Package

Resolves extracted entity names into canonical identifiers:
  • RDKit   → SMILES, InChIKey, MW, LogP
  • PubChem → CAS, IUPAC name, synonyms
  • NCBI    → Taxonomy ID for biological agents
  • Trade   → Trade-name-to-generic mapping
"""

from normalization.rdkit_resolver import RDKitResolver
from normalization.pubchem_resolver import PubChemResolver
from normalization.ncbi_taxonomy import NCBITaxonomyResolver
from normalization.trade_name_mapper import TradeNameMapper
from normalization.confidence import SourceType, get_confidence_score

__all__ = [
    "RDKitResolver",
    "PubChemResolver",
    "NCBITaxonomyResolver",
    "TradeNameMapper",
    "SourceType",
    "get_confidence_score",
]
