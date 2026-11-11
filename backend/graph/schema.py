"""
FormulaAI — Extended Neo4j Schema (Constraints + Indexes)

Replaces the basic Phase 1 db_init.py with a comprehensive schema
that covers all entity types from the extraction pipeline:

  Node Labels:
    • Compound         — Chemical compounds (active ingredients, excipients, solvents)
    • Biological       — Microbes, strains (bacteria, fungi, viruses, endophytes)
    • Peptide          — Antimicrobial/cell-penetrating peptides
    • Nanomaterial     — Nanoparticles, RNAi delivery vectors
    • Document         — Source documents (patents, papers, TDS/SDS)
    • FunctionalCategory — Taxonomy nodes for classification
    • RegulatoryBody   — EPA, FDA, etc.
    • Crop             — Target crops
    • TargetOrganism   — Pest/pathogen organisms
    • Formulation      — A specific formulation recipe from a document

  Relationship Types:
    FORMULATED_WITH, STABILIZES, INCOMPATIBLE_WITH, REPURPOSABLE_AS,
    SYNERGIZES_WITH, REGULATED_BY, FAILED_DUE_TO, SOLUBILIZES, DEGRADES,
    ENHANCES, INHIBITS, DELIVERS, ENCAPSULATES, EXTRACTED_FROM,
    CATEGORIZED_AS, TARGETS

  Indexes:
    • Full-text index on Compound names for fuzzy search
    • Composite indexes for common query patterns

Usage:
    from graph.schema import GraphSchema
    from graph.connection import get_neo4j

    neo4j = get_neo4j()
    await neo4j.connect()
    schema = GraphSchema(neo4j)
    await schema.initialize()
"""

from __future__ import annotations

import logging

from graph.connection import Neo4jConnection

logger = logging.getLogger(__name__)


# ── Uniqueness Constraints ───────────────────────────────────────────────────
# Every node label that represents a deduplicated entity gets a
# uniqueness constraint on its canonical identifier.

CONSTRAINTS = [
    # ── Core Entities ────────────────────────────────────────────────────
    (
        "compound_name_unique",
        "CREATE CONSTRAINT compound_name_unique IF NOT EXISTS "
        "FOR (n:Compound) REQUIRE n.name IS UNIQUE",
    ),
    (
        "biological_name_unique",
        "CREATE CONSTRAINT biological_name_unique IF NOT EXISTS "
        "FOR (n:Biological) REQUIRE n.organism_name IS UNIQUE",
    ),
    (
        "peptide_name_unique",
        "CREATE CONSTRAINT peptide_name_unique IF NOT EXISTS "
        "FOR (n:Peptide) REQUIRE n.name IS UNIQUE",
    ),
    (
        "nanomaterial_name_unique",
        "CREATE CONSTRAINT nanomaterial_name_unique IF NOT EXISTS "
        "FOR (n:Nanomaterial) REQUIRE n.name IS UNIQUE",
    ),
    # ── Source Documents ─────────────────────────────────────────────────
    (
        "document_source_id_unique",
        "CREATE CONSTRAINT document_source_id_unique IF NOT EXISTS "
        "FOR (n:Document) REQUIRE n.source_id IS UNIQUE",
    ),
    # ── Classification & Taxonomy ────────────────────────────────────────
    (
        "functional_category_name_unique",
        "CREATE CONSTRAINT functional_category_name_unique IF NOT EXISTS "
        "FOR (n:FunctionalCategory) REQUIRE n.name IS UNIQUE",
    ),
    (
        "regulatory_body_name_unique",
        "CREATE CONSTRAINT regulatory_body_name_unique IF NOT EXISTS "
        "FOR (n:RegulatoryBody) REQUIRE n.name IS UNIQUE",
    ),
    (
        "crop_name_unique",
        "CREATE CONSTRAINT crop_name_unique IF NOT EXISTS "
        "FOR (n:Crop) REQUIRE n.name IS UNIQUE",
    ),
    (
        "target_organism_name_unique",
        "CREATE CONSTRAINT target_organism_name_unique IF NOT EXISTS "
        "FOR (n:TargetOrganism) REQUIRE n.name IS UNIQUE",
    ),
    # ── Formulation Recipes ──────────────────────────────────────────────
    (
        "formulation_id_unique",
        "CREATE CONSTRAINT formulation_id_unique IF NOT EXISTS "
        "FOR (n:Formulation) REQUIRE n.formulation_id IS UNIQUE",
    ),
]

# ── Indexes ──────────────────────────────────────────────────────────────────
# Range indexes for common property lookups and ordering.

INDEXES = [
    # CAS number lookup
    (
        "compound_cas_index",
        "CREATE INDEX compound_cas_index IF NOT EXISTS "
        "FOR (n:Compound) ON (n.cas_number)",
    ),
    # InChIKey lookup (canonical chemical identity)
    (
        "compound_inchikey_index",
        "CREATE INDEX compound_inchikey_index IF NOT EXISTS "
        "FOR (n:Compound) ON (n.inchikey)",
    ),
    # SMILES lookup
    (
        "compound_smiles_index",
        "CREATE INDEX compound_smiles_index IF NOT EXISTS "
        "FOR (n:Compound) ON (n.canonical_smiles)",
    ),
    # Compound class filtering
    (
        "compound_class_index",
        "CREATE INDEX compound_class_index IF NOT EXISTS "
        "FOR (n:Compound) ON (n.compound_class)",
    ),
    # HLB value range queries (critical for surfactant selection)
    (
        "compound_hlb_index",
        "CREATE INDEX compound_hlb_index IF NOT EXISTS "
        "FOR (n:Compound) ON (n.hlb_value)",
    ),
    # LogP range queries (hydrophobicity screening)
    (
        "compound_logp_index",
        "CREATE INDEX compound_logp_index IF NOT EXISTS "
        "FOR (n:Compound) ON (n.log_p)",
    ),
    # Molecular weight range queries
    (
        "compound_mw_index",
        "CREATE INDEX compound_mw_index IF NOT EXISTS "
        "FOR (n:Compound) ON (n.molecular_weight)",
    ),
    # Biological agent type
    (
        "biological_type_index",
        "CREATE INDEX biological_type_index IF NOT EXISTS "
        "FOR (n:Biological) ON (n.agent_type)",
    ),
    # NCBI Taxonomy ID lookup
    (
        "biological_taxid_index",
        "CREATE INDEX biological_taxid_index IF NOT EXISTS "
        "FOR (n:Biological) ON (n.ncbi_taxonomy_id)",
    ),
    # Nanomaterial particle size range queries
    (
        "nanomaterial_size_index",
        "CREATE INDEX nanomaterial_size_index IF NOT EXISTS "
        "FOR (n:Nanomaterial) ON (n.particle_size_nm)",
    ),
    # Nanomaterial zeta potential
    (
        "nanomaterial_zeta_index",
        "CREATE INDEX nanomaterial_zeta_index IF NOT EXISTS "
        "FOR (n:Nanomaterial) ON (n.zeta_potential_mv)",
    ),
    # Document source type filtering
    (
        "document_type_index",
        "CREATE INDEX document_type_index IF NOT EXISTS "
        "FOR (n:Document) ON (n.source_type)",
    ),
    # Peptide isoelectric point
    (
        "peptide_pi_index",
        "CREATE INDEX peptide_pi_index IF NOT EXISTS "
        "FOR (n:Peptide) ON (n.isoelectric_point)",
    ),
]

# ── Full-Text Indexes ────────────────────────────────────────────────────────
# Enable fuzzy and tokenized search across compound names and trade names.

FULLTEXT_INDEXES = [
    (
        "compound_fulltext",
        "CREATE FULLTEXT INDEX compound_fulltext IF NOT EXISTS "
        "FOR (n:Compound) ON EACH [n.name, n.iupac_name]",
    ),
    (
        "biological_fulltext",
        "CREATE FULLTEXT INDEX biological_fulltext IF NOT EXISTS "
        "FOR (n:Biological) ON EACH [n.organism_name, n.strain_designation]",
    ),
    (
        "document_fulltext",
        "CREATE FULLTEXT INDEX document_fulltext IF NOT EXISTS "
        "FOR (n:Document) ON EACH [n.title, n.summary]",
    ),
]


class GraphSchema:
    """
    Manages the Neo4j schema: constraints, indexes, and full-text indexes.

    Usage:
        schema = GraphSchema(neo4j_connection)
        await schema.initialize()          # Create all constraints + indexes
        stats = await schema.get_stats()   # Count nodes, rels, constraints
        await schema.drop_all()            # Nuclear option for dev/test
    """

    def __init__(self, neo4j: Neo4jConnection):
        self._neo4j = neo4j

    async def initialize(self) -> dict[str, int]:
        """
        Create all constraints, indexes, and full-text indexes.

        Idempotent — safe to call on every application startup.
        Uses IF NOT EXISTS so existing constraints are skipped.

        Returns:
            Dict with counts of created constraints, indexes, fulltext indexes.
        """
        created = {"constraints": 0, "indexes": 0, "fulltext_indexes": 0}

        async with self._neo4j.session() as session:
            # Constraints
            for name, query in CONSTRAINTS:
                try:
                    await session.run(query)
                    created["constraints"] += 1
                    logger.debug("Constraint OK: %s", name)
                except Exception as e:
                    logger.warning("Constraint %s: %s", name, str(e))

            # Range indexes
            for name, query in INDEXES:
                try:
                    await session.run(query)
                    created["indexes"] += 1
                    logger.debug("Index OK: %s", name)
                except Exception as e:
                    logger.warning("Index %s: %s", name, str(e))

            # Full-text indexes
            for name, query in FULLTEXT_INDEXES:
                try:
                    await session.run(query)
                    created["fulltext_indexes"] += 1
                    logger.debug("Fulltext index OK: %s", name)
                except Exception as e:
                    logger.warning("Fulltext index %s: %s", name, str(e))

        total = sum(created.values())
        logger.info(
            "Schema initialized: %d constraints, %d indexes, %d fulltext (%d total)",
            created["constraints"],
            created["indexes"],
            created["fulltext_indexes"],
            total,
        )
        return created

    async def get_stats(self) -> dict:
        """Return counts of nodes, relationships, constraints, and indexes."""
        async with self._neo4j.session() as session:
            # Node counts per label
            result = await session.run(
                "CALL db.labels() YIELD label "
                "CALL { WITH label "
                "  CALL db.stats.retrieve('GRAPH COUNTS') YIELD data "
                "  RETURN data } "
                "RETURN label"
            )
            # Simpler fallback: just count everything
            counts = await session.run(
                "MATCH (n) WITH labels(n) AS labs, count(*) AS cnt "
                "UNWIND labs AS label "
                "RETURN label, sum(cnt) AS count "
                "ORDER BY count DESC"
            )
            label_counts = {}
            async for record in counts:
                label_counts[record["label"]] = record["count"]

            # Total relationships
            rel_result = await session.run(
                "MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS count "
                "ORDER BY count DESC"
            )
            rel_counts = {}
            async for record in rel_result:
                rel_counts[record["type"]] = record["count"]

            # Constraint count
            constraint_result = await session.run("SHOW CONSTRAINTS")
            constraints = [r async for r in constraint_result]

            # Index count
            index_result = await session.run("SHOW INDEXES")
            indexes = [r async for r in index_result]

            return {
                "node_labels": label_counts,
                "relationship_types": rel_counts,
                "total_nodes": sum(label_counts.values()),
                "total_relationships": sum(rel_counts.values()),
                "constraints": len(constraints),
                "indexes": len(indexes),
            }

    async def drop_all(self) -> None:
        """
        ⚠️ DESTRUCTIVE: Drop all nodes, relationships, constraints, and indexes.

        Only for development/testing. Never call in production.
        """
        logger.warning("DROPPING ALL GRAPH DATA — this is destructive!")
        async with self._neo4j.session() as session:
            # Drop all constraints
            for name, _ in CONSTRAINTS:
                try:
                    await session.run(f"DROP CONSTRAINT {name} IF EXISTS")
                except Exception:
                    pass

            # Drop all indexes
            for name, _ in INDEXES + FULLTEXT_INDEXES:
                try:
                    await session.run(f"DROP INDEX {name} IF EXISTS")
                except Exception:
                    pass

            # Delete all data
            await session.run(
                "CALL { MATCH (n) DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS"
            )
            logger.info("All graph data dropped")
