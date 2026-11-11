"""
FormulaAI — Extraction Pydantic Schemas

Strictly-typed data models for every entity and relationship extracted
from agrochemical documents. These schemas are the scientific core of
the pipeline — they enforce that the LLM returns physicochemical
parameters whenever present.

CRITICAL DESIGN DECISIONS:
  • All optional numeric fields default to None (not 0.0) so we can
    distinguish "not mentioned" from "zero".
  • Compound classes and relationship types use Literal unions for
    strict validation — the LLM cannot hallucinate a new category.
  • Every entity carries a `confidence` field (0.0–1.0) for downstream
    graph weighting and UI provenance display.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ── Enums & Literals ─────────────────────────────────────────────────────────


class CompoundClass(str, Enum):
    """Chemical classification taxonomy."""
    ORGANIC = "organic"
    INORGANIC = "inorganic"
    SYNTHETIC = "synthetic"
    SYNTHETIC_ANALOG = "synthetic_analog"
    NUCLEIC_ACID = "nucleic_acid"
    PEPTIDE = "peptide"
    BIOLOGICAL = "biological"
    NANOMATERIAL = "nanomaterial"


class BiologicalAgentType(str, Enum):
    """Classification of biological agents."""
    BACTERIA = "bacteria"
    FUNGI = "fungi"
    VIRUS = "virus"
    ENDOPHYTE = "endophyte"


class FunctionalCategory(str, Enum):
    """Agrochemical functional use-case taxonomy."""
    CROP_IMPROVEMENT = "crop_improvement"
    CROP_PRODUCTION = "crop_production"
    CROP_PROTECTION = "crop_protection"
    FERTILIZER = "fertilizer"
    BIOFERTILIZER = "biofertilizer"
    PESTICIDE = "pesticide"
    BIOPESTICIDE = "biopesticide"
    BIOSTIMULANT = "biostimulant"
    CROP_ENHANCER = "crop_enhancer"
    INSECTICIDE = "insecticide"
    FUNGICIDE = "fungicide"
    NEMATICIDE = "nematicide"
    HERBICIDE = "herbicide"
    BIOHERBICIDE = "bioherbicide"
    PGR = "plant_growth_regulator"
    SOIL_CONDITIONER = "soil_conditioner"
    BOTANICAL_ADDITIVE = "botanical_additive"
    LIVESTOCK_PROTECTION = "livestock_protection"
    SOIL_SUPPLEMENT = "soil_supplement"
    RNAI_VECTOR = "rnai_delivery_vector"
    NANOMATERIAL = "nanomaterial"
    SURFACTANT_ADJUVANT = "surfactant_adjuvant"
    EXCIPIENT = "excipient"
    SOLUBILIZER = "solubilizer"
    STABILIZER = "stabilizer"
    EMULSIFIER = "emulsifier"


RELATIONSHIP_TYPES = Literal[
    "FORMULATED_WITH",
    "STABILIZES",
    "INCOMPATIBLE_WITH",
    "REPURPOSABLE_AS",
    "SYNERGIZES_WITH",
    "REGULATED_BY",
    "FAILED_DUE_TO",
    "SOLUBILIZES",
    "DEGRADES",
    "ENHANCES",
    "INHIBITS",
    "DELIVERS",
    "ENCAPSULATES",
]

SOURCE_TYPES = Literal[
    "patent",
    "paper",
    "tds",
    "sds",
    "fda_iid",
    "chembl",
    "textbook",
    "regulatory",
    "web",
]


# ── Entity Schemas ───────────────────────────────────────────────────────────


class ExtractedCompound(BaseModel):
    """
    A chemical compound extracted from a document.

    The LLM must populate physicochemical fields whenever the source
    document mentions them. Fields left as None indicate the parameter
    was not present in the source text.
    """

    name: str = Field(
        ..., description="Chemical name as found in the source text"
    )
    iupac_name: str | None = Field(
        None, description="IUPAC systematic name if mentioned"
    )
    trade_names: list[str] = Field(
        default_factory=list,
        description="Commercial/trade names mentioned for this compound",
    )
    cas_number: str | None = Field(
        None, description="CAS Registry Number if mentioned (e.g., '1071-83-6')"
    )
    canonical_smiles: str | None = Field(
        None, description="SMILES string if mentioned or derivable"
    )
    inchikey: str | None = Field(
        None, description="InChIKey if mentioned"
    )

    # ── Physicochemical Parameters (CRITICAL) ────────────────────────────
    molecular_weight: float | None = Field(
        None, description="Molecular weight in g/mol"
    )
    log_p: float | None = Field(
        None, description="LogP (octanol-water partition coefficient)"
    )
    hlb_value: float | None = Field(
        None,
        description="Hydrophilic-Lipophilic Balance value (0-20 scale)",
    )
    ph_stability_min: float | None = Field(
        None, description="Lower bound of pH stability range"
    )
    ph_stability_max: float | None = Field(
        None, description="Upper bound of pH stability range"
    )
    solubility_g_per_l: float | None = Field(
        None, description="Aqueous solubility in g/L at 25°C"
    )

    # ── Classification ───────────────────────────────────────────────────
    compound_class: CompoundClass | None = Field(
        None,
        description="Chemical classification: organic, inorganic, synthetic, etc.",
    )
    functional_categories: list[FunctionalCategory] = Field(
        default_factory=list,
        description="Functional use-cases this compound serves",
    )

    # ── Extraction Metadata ──────────────────────────────────────────────
    confidence: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        description="LLM self-assessed extraction confidence (0.0–1.0)",
    )
    source_context: str | None = Field(
        None,
        description="The exact sentence or table cell where this entity was found",
    )


class ExtractedBiological(BaseModel):
    """
    A biological agent (microbe/strain) extracted from a document.

    Used for bacteria, fungi, viruses, and endophytes found in
    biopesticide and biostimulant formulations.
    """

    organism_name: str = Field(
        ..., description="Scientific name of the organism"
    )
    strain_designation: str | None = Field(
        None, description="Specific strain ID (e.g., 'QST 713', 'T-22')"
    )
    ncbi_taxonomy_id: int | None = Field(
        None, description="NCBI Taxonomy ID if known"
    )
    agent_type: BiologicalAgentType = Field(
        ..., description="Type of biological agent"
    )
    target_organisms: list[str] = Field(
        default_factory=list,
        description="Pest/pathogen organisms this agent targets",
    )
    mode_of_action: str | None = Field(
        None,
        description="Mechanism of action (e.g., 'competitive exclusion', 'antibiosis')",
    )
    functional_categories: list[FunctionalCategory] = Field(
        default_factory=list,
        description="Functional use-cases",
    )
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    source_context: str | None = None


class ExtractedPeptide(ExtractedCompound):
    """
    Peptide-specific extensions.

    Inherits all fields from ExtractedCompound and adds peptide-specific
    physicochemical parameters.
    """

    isoelectric_point: float | None = Field(
        None, description="Isoelectric point (pI) of the peptide"
    )
    amino_acid_sequence: str | None = Field(
        None, description="Amino acid sequence in single-letter code"
    )
    sequence_length: int | None = Field(
        None, description="Number of amino acid residues"
    )
    is_cyclic: bool | None = Field(
        None, description="Whether the peptide is cyclic"
    )


class ExtractedNanomaterial(ExtractedCompound):
    """
    Nanomaterial / RNAi delivery vector extensions.

    Inherits all fields from ExtractedCompound and adds nano-specific
    characterization parameters.
    """

    zeta_potential_mv: float | None = Field(
        None, description="Zeta potential in millivolts (mV)"
    )
    particle_size_nm: float | None = Field(
        None, description="Mean particle diameter in nanometers (nm)"
    )
    pdi: float | None = Field(
        None,
        description="Polydispersity Index (0.0 = monodisperse, 1.0 = polydisperse)",
    )
    encapsulation_efficiency: float | None = Field(
        None, description="Encapsulation efficiency as percentage (0-100)"
    )
    delivery_vector_type: str | None = Field(
        None,
        description="Vector type (e.g., 'lipid nanoparticle', 'chitosan NP', 'PLGA')",
    )
    cargo_type: str | None = Field(
        None,
        description="What the nanoparticle carries (e.g., 'dsRNA', 'siRNA', 'pesticide')",
    )


# ── Relationship Schema ─────────────────────────────────────────────────────


class ExtractedRelationship(BaseModel):
    """
    A relationship triple extracted from a document.

    Represents a directed edge: source_entity → [relationship_type] → target_entity
    with optional properties that parameterize the relationship.
    """

    source_entity: str = Field(
        ..., description="Name of the source entity in the relationship"
    )
    target_entity: str = Field(
        ..., description="Name of the target entity in the relationship"
    )
    relationship_type: RELATIONSHIP_TYPES = Field(
        ...,
        description="Type of relationship between the entities",
    )

    # ── Relationship Properties ──────────────────────────────────────────
    ratio: str | None = Field(
        None, description="Mixing ratio (e.g., '1:10 w/w', '5% v/v')"
    )
    ph: float | None = Field(
        None, description="pH at which this relationship was observed"
    )
    temperature_c: float | None = Field(
        None, description="Temperature in °C at which this was observed"
    )
    mechanism: str | None = Field(
        None,
        description="Mechanism of the relationship (e.g., 'hydrogen bonding', 'UV degradation')",
    )
    physical_state: str | None = Field(
        None,
        description="Physical state outcome (e.g., 'precipitation', 'phase separation')",
    )
    target_use: str | None = Field(
        None,
        description="Target use-case for REPURPOSABLE_AS relationships",
    )
    status: str | None = Field(
        None,
        description="Regulatory status for REGULATED_BY relationships",
    )
    reason: str | None = Field(
        None,
        description="Reason for INCOMPATIBLE_WITH or FAILED_DUE_TO relationships",
    )

    confidence: float = Field(0.5, ge=0.0, le=1.0)
    source_context: str | None = Field(
        None,
        description="The exact text where this relationship was described",
    )
    is_negative_data: bool = Field(
        False,
        description="True if this represents a failure/incompatibility (negative data)",
    )


# ── Top-Level Extraction Result ─────────────────────────────────────────────


class ExtractionResult(BaseModel):
    """
    Complete extraction output from a single document.

    This is the top-level response model that the LLM returns.
    It aggregates all entities and relationships found in one document.
    """

    source_id: str = Field(
        ..., description="Document identifier (DOI, patent number, PMID)"
    )
    source_type: SOURCE_TYPES = Field(
        ..., description="Type of source document"
    )

    # ── Extracted Entities ────────────────────────────────────────────────
    compounds: list[ExtractedCompound] = Field(
        default_factory=list,
        description="Chemical compounds found in the document",
    )
    biologicals: list[ExtractedBiological] = Field(
        default_factory=list,
        description="Biological agents found in the document",
    )
    peptides: list[ExtractedPeptide] = Field(
        default_factory=list,
        description="Peptides found in the document",
    )
    nanomaterials: list[ExtractedNanomaterial] = Field(
        default_factory=list,
        description="Nanomaterials/RNAi vectors found in the document",
    )

    # ── Extracted Relationships ──────────────────────────────────────────
    relationships: list[ExtractedRelationship] = Field(
        default_factory=list,
        description="Relationship triples between entities",
    )

    # ── Document-Level Metadata ──────────────────────────────────────────
    formulation_type: str | None = Field(
        None,
        description="Overall formulation type (e.g., 'SC', 'EC', 'WP', 'WG', 'SL')",
    )
    document_summary: str | None = Field(
        None,
        description="Brief 2-3 sentence summary of the document's formulation findings",
    )

    @property
    def total_entities(self) -> int:
        return (
            len(self.compounds)
            + len(self.biologicals)
            + len(self.peptides)
            + len(self.nanomaterials)
        )

    @property
    def total_relationships(self) -> int:
        return len(self.relationships)

    @property
    def negative_data_count(self) -> int:
        return sum(1 for r in self.relationships if r.is_negative_data)
