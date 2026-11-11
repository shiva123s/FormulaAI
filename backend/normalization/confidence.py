"""
FormulaAI — Source-Authority Confidence Scoring

Assigns a confidence score (0.0–1.0) to extracted data based on the
authority and reliability of its source. Used by the graph loader to
weight edges and by the UI to surface provenance quality.
"""

from __future__ import annotations

from enum import Enum


class SourceType(str, Enum):
    """Classification of data sources by authority level."""

    PEER_REVIEWED = "peer_reviewed"    # PubMed, OpenAlex (peer-reviewed journals)
    TDS = "tds"                        # Manufacturer Technical Data Sheet
    SDS = "sds"                        # Safety Data Sheet
    REGULATORY = "regulatory"          # EPA, FDA filings
    PATENT = "patent"                  # USPTO, EPO, WIPO
    CHEMBL = "chembl"                  # ChEMBL curated bioactivity
    FDA_IID = "fda_iid"                # FDA Inactive Ingredient Database
    TEXTBOOK = "textbook"              # Formulation manuals, reference books
    WEB = "web"                        # Unverified web sources
    UNKNOWN = "unknown"                # Fallback


# ── Confidence Matrix ────────────────────────────────────────────────────────
# Rationale documented in implementation_plan.md § Confidence Scoring Matrix

_CONFIDENCE_MATRIX: dict[SourceType, float] = {
    SourceType.PEER_REVIEWED: 0.95,   # Gold standard, peer-reviewed
    SourceType.TDS: 0.93,             # Empirical lab data from manufacturer
    SourceType.SDS: 0.93,             # Regulatory-mandated safety data
    SourceType.REGULATORY: 0.90,      # Government-filed, verified
    SourceType.CHEMBL: 0.88,          # Curated from literature by EBI
    SourceType.FDA_IID: 0.90,         # FDA-approved inactive ingredients
    SourceType.PATENT: 0.85,          # Claims may be aspirational / broad
    SourceType.TEXTBOOK: 0.80,        # Authoritative but may be dated
    SourceType.WEB: 0.60,             # Requires manual validation
    SourceType.UNKNOWN: 0.50,         # Minimum baseline
}


def get_confidence_score(source_type: SourceType | str) -> float:
    """
    Return the confidence score for a given source type.

    Args:
        source_type: A SourceType enum member or its string value.

    Returns:
        A float between 0.0 and 1.0 representing source reliability.
    """
    if isinstance(source_type, str):
        try:
            source_type = SourceType(source_type)
        except ValueError:
            return _CONFIDENCE_MATRIX[SourceType.UNKNOWN]
    return _CONFIDENCE_MATRIX.get(source_type, _CONFIDENCE_MATRIX[SourceType.UNKNOWN])


def apply_extraction_penalty(
    base_confidence: float,
    llm_confidence: float | None = None,
    was_rdkit_validated: bool = False,
) -> float:
    """
    Adjust confidence based on extraction quality signals.

    - If the LLM reports a self-assessed confidence, blend it (30% weight).
    - If RDKit successfully validated the compound, add a small bonus.
    - Final score is clamped to [0.0, 1.0].

    Args:
        base_confidence: The source-authority score from get_confidence_score().
        llm_confidence: Optional LLM self-reported extraction confidence (0–1).
        was_rdkit_validated: True if RDKit confirmed the SMILES/InChIKey.

    Returns:
        Adjusted confidence score, clamped to [0.0, 1.0].
    """
    score = base_confidence

    # Blend in LLM self-confidence (30% weight)
    if llm_confidence is not None:
        score = 0.70 * score + 0.30 * llm_confidence

    # RDKit validation bonus
    if was_rdkit_validated:
        score = min(score + 0.03, 1.0)

    return round(max(0.0, min(score, 1.0)), 4)
