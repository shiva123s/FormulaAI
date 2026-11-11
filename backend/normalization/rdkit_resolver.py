"""
FormulaAI — RDKit Chemical Resolver

Validates SMILES strings and computes physicochemical properties:
  • Canonical SMILES
  • InChIKey
  • Molecular Weight (g/mol)
  • LogP (Wildman-Crippen)
  • Molecular Formula

Gracefully degrades when RDKit is not installed (e.g., on Windows
without conda). In that case, all methods return None and log a warning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Conditional RDKit import ─────────────────────────────────────────────────
try:
    from rdkit import Chem  # type: ignore
    from rdkit.Chem import Descriptors, rdMolDescriptors, inchi as rdkit_inchi  # type: ignore

    RDKIT_AVAILABLE = True
except ImportError:
    RDKIT_AVAILABLE = False
    logger.warning(
        "RDKit is not installed. Chemical property computation will be unavailable. "
        "Install with: pip install rdkit-pypi"
    )


@dataclass(frozen=True)
class ChemicalIdentity:
    """Resolved chemical identifiers and physicochemical properties."""

    canonical_smiles: str | None = None
    inchikey: str | None = None
    molecular_weight: float | None = None
    log_p: float | None = None
    molecular_formula: str | None = None
    num_h_bond_donors: int | None = None
    num_h_bond_acceptors: int | None = None
    tpsa: float | None = None  # Topological Polar Surface Area

    @property
    def is_valid(self) -> bool:
        """Return True if a valid canonical SMILES was resolved."""
        return self.canonical_smiles is not None

    @property
    def smiles(self) -> str | None:
        """Alias for canonical_smiles."""
        return self.canonical_smiles

    @property
    def logp(self) -> float | None:
        """Alias for log_p."""
        return self.log_p


class RDKitResolver:
    """Stateless resolver that wraps RDKit operations behind a clean API."""

    @staticmethod
    def is_available() -> bool:
        """Check if RDKit is installed and usable."""
        return RDKIT_AVAILABLE

    @staticmethod
    def resolve_smiles(smiles: str) -> ChemicalIdentity:
        """
        Alias for compute_properties() for pipeline compatibility.
        Computes chemical properties and identifiers from a SMILES string.
        """
        return RDKitResolver.compute_properties(smiles)

    @staticmethod
    def validate_smiles(smiles: str) -> str | None:
        """
        Validate a SMILES string and return its canonical form.

        Returns None if the SMILES is invalid or RDKit is unavailable.
        """
        if not RDKIT_AVAILABLE:
            return None
        try:
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                logger.debug("Invalid SMILES: %s", smiles)
                return None
            return Chem.MolToSmiles(mol, canonical=True)
        except Exception:
            logger.exception("RDKit error validating SMILES: %s", smiles)
            return None

    @staticmethod
    def smiles_to_inchikey(smiles: str) -> str | None:
        """Convert a SMILES string to an InChIKey."""
        if not RDKIT_AVAILABLE:
            return None
        try:
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                return None
            inchi_str = rdkit_inchi.MolToInchi(mol)
            if inchi_str is None:
                return None
            return rdkit_inchi.InchiToInchiKey(inchi_str)
        except Exception:
            logger.exception("RDKit error computing InChIKey for: %s", smiles)
            return None

    @staticmethod
    def compute_properties(smiles: str) -> ChemicalIdentity:
        """
        Compute a full set of physicochemical properties from a SMILES string.

        Returns a ChemicalIdentity with all fields populated if valid,
        or all-None fields if the SMILES is invalid or RDKit is unavailable.
        """
        if not RDKIT_AVAILABLE:
            return ChemicalIdentity()

        try:
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                logger.debug("Cannot parse SMILES for property computation: %s", smiles)
                return ChemicalIdentity()

            canonical = Chem.MolToSmiles(mol, canonical=True)

            # InChIKey
            inchi_str = rdkit_inchi.MolToInchi(mol)
            inchikey = (
                rdkit_inchi.InchiToInchiKey(inchi_str) if inchi_str else None
            )

            return ChemicalIdentity(
                canonical_smiles=canonical,
                inchikey=inchikey,
                molecular_weight=round(Descriptors.ExactMolWt(mol), 4),
                log_p=round(Descriptors.MolLogP(mol), 4),
                molecular_formula=rdMolDescriptors.CalcMolFormula(mol),
                num_h_bond_donors=Descriptors.NumHDonors(mol),
                num_h_bond_acceptors=Descriptors.NumHAcceptors(mol),
                tpsa=round(Descriptors.TPSA(mol), 4),
            )
        except Exception:
            logger.exception("RDKit error computing properties for: %s", smiles)
            return ChemicalIdentity()

    @staticmethod
    def are_same_compound(smiles_a: str, smiles_b: str) -> bool | None:
        """
        Check if two SMILES represent the same canonical molecule.

        Returns None if either SMILES is invalid or RDKit is unavailable.
        """
        if not RDKIT_AVAILABLE:
            return None
        canonical_a = RDKitResolver.validate_smiles(smiles_a)
        canonical_b = RDKitResolver.validate_smiles(smiles_b)
        if canonical_a is None or canonical_b is None:
            return None
        return canonical_a == canonical_b
