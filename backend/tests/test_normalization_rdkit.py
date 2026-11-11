"""
FormulaAI — RDKit & Chemical Normalization Unit Tests

Tests property computation, ChemicalIdentity aliases, and graceful fallbacks.
"""

import pytest
from normalization.rdkit_resolver import ChemicalIdentity, RDKitResolver


class TestChemicalIdentity:
    def test_properties_valid(self):
        ident = ChemicalIdentity(
            canonical_smiles="CC(=O)OC1=CC=CC=C1C(=O)O",
            inchikey="BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            molecular_weight=180.1574,
            log_p=1.31,
        )
        assert ident.is_valid is True
        assert ident.smiles == "CC(=O)OC1=CC=CC=C1C(=O)O"
        assert ident.logp == 1.31

    def test_properties_invalid(self):
        ident = ChemicalIdentity()
        assert ident.is_valid is False
        assert ident.smiles is None
        assert ident.logp is None


class TestRDKitResolver:
    def test_resolve_smiles_alias(self):
        # Even if RDKit is not installed in the current environment,
        # resolve_smiles must return a ChemicalIdentity instance without raising.
        res = RDKitResolver.resolve_smiles("CCO")
        assert isinstance(res, ChemicalIdentity)
        if RDKitResolver.is_available():
            assert res.is_valid is True
            assert res.canonical_smiles == "CCO"
            assert res.molecular_weight is not None
            assert res.molecular_weight > 40
        else:
            assert res.is_valid is False

    def test_invalid_smiles(self):
        res = RDKitResolver.compute_properties("INVALID_SMILES_STRING_12345")
        assert isinstance(res, ChemicalIdentity)
        assert res.is_valid is False
        assert res.canonical_smiles is None
