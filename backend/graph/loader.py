"""
FormulaAI — Batch Neo4j Graph Loader

Loads ExtractionResult objects into the Neo4j Knowledge Graph using
batch MERGE + UNWIND queries for optimal performance.

Design Principles:
  1. MERGE-based — idempotent, safe to re-run on the same document
  2. UNWIND-based — batch all entities of the same type into a single
     Cypher call instead of N individual queries
  3. Property preservation — SET += to accumulate properties from
     multiple source documents without overwriting
  4. Provenance tracking — every node links to its source Document
     via EXTRACTED_FROM, preserving confidence scores
  5. Relationship properties — all edge metadata (ratio, pH, mechanism)
     stored directly on the relationship

Performance:
  - Single document with 50 entities + 30 relationships: ~6 Cypher queries
  - 1000 documents via batch: uses transaction batching to avoid OOM

Usage:
    from graph.loader import GraphLoader
    from graph.connection import get_neo4j

    neo4j = get_neo4j()
    await neo4j.connect()

    loader = GraphLoader(neo4j)
    stats = await loader.load(extraction_result)
    print(stats)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from graph.connection import Neo4jConnection
from extraction.schemas import (
    ExtractionResult,
    ExtractedCompound,
    ExtractedBiological,
    ExtractedPeptide,
    ExtractedNanomaterial,
    ExtractedRelationship,
)

logger = logging.getLogger(__name__)


@dataclass
class LoadStats:
    """Tracks what was loaded into the graph."""

    source_id: str
    compounds_merged: int = 0
    biologicals_merged: int = 0
    peptides_merged: int = 0
    nanomaterials_merged: int = 0
    relationships_merged: int = 0
    categories_linked: int = 0
    document_created: bool = False
    errors: list[str] = field(default_factory=list)
    started_at: str = field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z"
    )
    finished_at: str | None = None

    @property
    def total_nodes(self) -> int:
        return (
            self.compounds_merged
            + self.biologicals_merged
            + self.peptides_merged
            + self.nanomaterials_merged
        )

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def finish(self) -> None:
        self.finished_at = datetime.utcnow().isoformat() + "Z"


class GraphLoader:
    """
    Loads ExtractionResult objects into Neo4j using batch MERGE queries.

    All operations are idempotent — re-loading the same ExtractionResult
    will update existing nodes and add new properties without duplicating.

    Usage:
        loader = GraphLoader(neo4j_connection)
        stats = await loader.load(extraction_result)
        batch_stats = await loader.load_batch([result1, result2, ...])
    """

    def __init__(self, neo4j: Neo4jConnection):
        self._neo4j = neo4j

    # ── Public API ───────────────────────────────────────────────────────

    async def load(self, result: ExtractionResult) -> LoadStats:
        """
        Load a complete ExtractionResult into the graph.

        Creates/updates:
          1. Document node (source provenance)
          2. Compound nodes (with physicochemical properties)
          3. Biological nodes (with taxonomy and mode of action)
          4. Peptide nodes (with pI, sequence)
          5. Nanomaterial nodes (with zeta, particle size, PDI)
          6. EXTRACTED_FROM relationships (entity → document)
          7. CATEGORIZED_AS relationships (entity → FunctionalCategory)
          8. Inter-entity relationships (FORMULATED_WITH, STABILIZES, etc.)

        Returns:
            LoadStats with counts of what was created/updated.
        """
        stats = LoadStats(source_id=result.source_id)

        try:
            async with self._neo4j.session() as session:
                # 1. Create/update Document node
                await self._merge_document(session, result)
                stats.document_created = True

                # 2. Merge Compounds
                if result.compounds:
                    n = await self._merge_compounds(
                        session, result.compounds, result.source_id
                    )
                    stats.compounds_merged = n

                # 3. Merge Biologicals
                if result.biologicals:
                    n = await self._merge_biologicals(
                        session, result.biologicals, result.source_id
                    )
                    stats.biologicals_merged = n

                # 4. Merge Peptides
                if result.peptides:
                    n = await self._merge_peptides(
                        session, result.peptides, result.source_id
                    )
                    stats.peptides_merged = n

                # 5. Merge Nanomaterials
                if result.nanomaterials:
                    n = await self._merge_nanomaterials(
                        session, result.nanomaterials, result.source_id
                    )
                    stats.nanomaterials_merged = n

                # 6. Link FunctionalCategories
                categories = await self._link_categories(session, result)
                stats.categories_linked = categories

                # 7. Merge inter-entity relationships
                if result.relationships:
                    n = await self._merge_relationships(
                        session, result.relationships, result.source_id
                    )
                    stats.relationships_merged = n

        except Exception as e:
            stats.errors.append(str(e))
            logger.exception(
                "Failed to load extraction result: %s", result.source_id
            )

        stats.finish()
        logger.info(
            "Loaded %s: %d nodes, %d rels, %d categories (%s)",
            stats.source_id,
            stats.total_nodes,
            stats.relationships_merged,
            stats.categories_linked,
            "OK" if stats.success else f"ERRORS: {stats.errors}",
        )
        return stats

    async def load_batch(
        self,
        results: list[ExtractionResult],
        on_complete: Any = None,
    ) -> list[LoadStats]:
        """
        Load multiple ExtractionResults sequentially.

        Args:
            results: List of ExtractionResult objects.
            on_complete: Optional callback(source_id, stats) per document.

        Returns:
            List of LoadStats for each document.
        """
        all_stats = []
        for i, result in enumerate(results):
            logger.info(
                "Loading %d/%d: %s", i + 1, len(results), result.source_id
            )
            stats = await self.load(result)
            all_stats.append(stats)
            if on_complete:
                on_complete(result.source_id, stats)
        return all_stats

    # ── Document Node ────────────────────────────────────────────────────

    @staticmethod
    async def _merge_document(
        session: Any, result: ExtractionResult
    ) -> None:
        """MERGE the source Document node."""
        await session.run(
            """
            MERGE (d:Document {source_id: $source_id})
            SET d.source_type     = $source_type,
                d.formulation_type = $formulation_type,
                d.summary         = $summary,
                d.total_entities  = $total_entities,
                d.total_relationships = $total_relationships,
                d.negative_data_count = $negative_data_count,
                d.loaded_at       = datetime()
            """,
            {
                "source_id": result.source_id,
                "source_type": result.source_type,
                "formulation_type": result.formulation_type,
                "summary": result.document_summary,
                "total_entities": result.total_entities,
                "total_relationships": result.total_relationships,
                "negative_data_count": result.negative_data_count,
            },
        )

    # ── Compound Nodes ───────────────────────────────────────────────────

    @staticmethod
    async def _merge_compounds(
        session: Any,
        compounds: list[ExtractedCompound],
        source_id: str,
    ) -> int:
        """Batch MERGE Compound nodes + EXTRACTED_FROM edges using UNWIND."""
        params = []
        for c in compounds:
            params.append(
                {
                    "name": c.name,
                    "iupac_name": c.iupac_name,
                    "trade_names": c.trade_names,
                    "cas_number": c.cas_number,
                    "canonical_smiles": c.canonical_smiles,
                    "inchikey": c.inchikey,
                    "molecular_weight": c.molecular_weight,
                    "log_p": c.log_p,
                    "hlb_value": c.hlb_value,
                    "ph_stability_min": c.ph_stability_min,
                    "ph_stability_max": c.ph_stability_max,
                    "solubility_g_per_l": c.solubility_g_per_l,
                    "compound_class": c.compound_class.value if c.compound_class else None,
                    "confidence": c.confidence,
                    "source_context": c.source_context,
                }
            )

        await session.run(
            """
            UNWIND $batch AS row
            MERGE (c:Compound {name: row.name})
            SET c += {
                iupac_name:        coalesce(row.iupac_name, c.iupac_name),
                cas_number:        coalesce(row.cas_number, c.cas_number),
                canonical_smiles:  coalesce(row.canonical_smiles, c.canonical_smiles),
                inchikey:          coalesce(row.inchikey, c.inchikey),
                molecular_weight:  coalesce(row.molecular_weight, c.molecular_weight),
                log_p:             coalesce(row.log_p, c.log_p),
                hlb_value:         coalesce(row.hlb_value, c.hlb_value),
                ph_stability_min:  coalesce(row.ph_stability_min, c.ph_stability_min),
                ph_stability_max:  coalesce(row.ph_stability_max, c.ph_stability_max),
                solubility_g_per_l: coalesce(row.solubility_g_per_l, c.solubility_g_per_l),
                compound_class:    coalesce(row.compound_class, c.compound_class),
                trade_names:       row.trade_names,
                updated_at:        datetime()
            }
            WITH c, row
            MATCH (d:Document {source_id: $source_id})
            MERGE (c)-[r:EXTRACTED_FROM]->(d)
            SET r.confidence     = row.confidence,
                r.source_context = row.source_context
            """,
            {"batch": params, "source_id": source_id},
        )
        return len(params)

    # ── Biological Nodes ─────────────────────────────────────────────────

    @staticmethod
    async def _merge_biologicals(
        session: Any,
        biologicals: list[ExtractedBiological],
        source_id: str,
    ) -> int:
        """Batch MERGE Biological nodes + EXTRACTED_FROM edges."""
        params = []
        for b in biologicals:
            params.append(
                {
                    "organism_name": b.organism_name,
                    "strain_designation": b.strain_designation,
                    "ncbi_taxonomy_id": b.ncbi_taxonomy_id,
                    "agent_type": b.agent_type.value,
                    "target_organisms": b.target_organisms,
                    "mode_of_action": b.mode_of_action,
                    "confidence": b.confidence,
                    "source_context": b.source_context,
                }
            )

        await session.run(
            """
            UNWIND $batch AS row
            MERGE (b:Biological {organism_name: row.organism_name})
            SET b += {
                strain_designation: coalesce(row.strain_designation, b.strain_designation),
                ncbi_taxonomy_id:   coalesce(row.ncbi_taxonomy_id, b.ncbi_taxonomy_id),
                agent_type:         row.agent_type,
                target_organisms:   row.target_organisms,
                mode_of_action:     coalesce(row.mode_of_action, b.mode_of_action),
                updated_at:         datetime()
            }
            WITH b, row
            MATCH (d:Document {source_id: $source_id})
            MERGE (b)-[r:EXTRACTED_FROM]->(d)
            SET r.confidence     = row.confidence,
                r.source_context = row.source_context
            """,
            {"batch": params, "source_id": source_id},
        )

        # Also create TargetOrganism nodes and TARGETS relationships
        for b in biologicals:
            if b.target_organisms:
                await session.run(
                    """
                    UNWIND $targets AS target_name
                    MERGE (t:TargetOrganism {name: target_name})
                    WITH t
                    MATCH (b:Biological {organism_name: $organism_name})
                    MERGE (b)-[:TARGETS]->(t)
                    """,
                    {
                        "targets": b.target_organisms,
                        "organism_name": b.organism_name,
                    },
                )

        return len(params)

    # ── Peptide Nodes ────────────────────────────────────────────────────

    @staticmethod
    async def _merge_peptides(
        session: Any,
        peptides: list[ExtractedPeptide],
        source_id: str,
    ) -> int:
        """Batch MERGE Peptide nodes (Compound + Peptide labels)."""
        params = []
        for p in peptides:
            params.append(
                {
                    "name": p.name,
                    "iupac_name": p.iupac_name,
                    "cas_number": p.cas_number,
                    "canonical_smiles": p.canonical_smiles,
                    "inchikey": p.inchikey,
                    "molecular_weight": p.molecular_weight,
                    "log_p": p.log_p,
                    "hlb_value": p.hlb_value,
                    "ph_stability_min": p.ph_stability_min,
                    "ph_stability_max": p.ph_stability_max,
                    "solubility_g_per_l": p.solubility_g_per_l,
                    "isoelectric_point": p.isoelectric_point,
                    "amino_acid_sequence": p.amino_acid_sequence,
                    "sequence_length": p.sequence_length,
                    "is_cyclic": p.is_cyclic,
                    "compound_class": p.compound_class.value if p.compound_class else "peptide",
                    "confidence": p.confidence,
                    "source_context": p.source_context,
                }
            )

        await session.run(
            """
            UNWIND $batch AS row
            MERGE (p:Peptide {name: row.name})
            SET p:Compound,
                p += {
                    iupac_name:           coalesce(row.iupac_name, p.iupac_name),
                    cas_number:           coalesce(row.cas_number, p.cas_number),
                    canonical_smiles:     coalesce(row.canonical_smiles, p.canonical_smiles),
                    inchikey:             coalesce(row.inchikey, p.inchikey),
                    molecular_weight:     coalesce(row.molecular_weight, p.molecular_weight),
                    log_p:                coalesce(row.log_p, p.log_p),
                    hlb_value:            coalesce(row.hlb_value, p.hlb_value),
                    ph_stability_min:     coalesce(row.ph_stability_min, p.ph_stability_min),
                    ph_stability_max:     coalesce(row.ph_stability_max, p.ph_stability_max),
                    solubility_g_per_l:   coalesce(row.solubility_g_per_l, p.solubility_g_per_l),
                    isoelectric_point:    coalesce(row.isoelectric_point, p.isoelectric_point),
                    amino_acid_sequence:  coalesce(row.amino_acid_sequence, p.amino_acid_sequence),
                    sequence_length:      coalesce(row.sequence_length, p.sequence_length),
                    is_cyclic:            coalesce(row.is_cyclic, p.is_cyclic),
                    compound_class:       row.compound_class,
                    updated_at:           datetime()
                }
            WITH p, row
            MATCH (d:Document {source_id: $source_id})
            MERGE (p)-[r:EXTRACTED_FROM]->(d)
            SET r.confidence     = row.confidence,
                r.source_context = row.source_context
            """,
            {"batch": params, "source_id": source_id},
        )
        return len(params)

    # ── Nanomaterial Nodes ───────────────────────────────────────────────

    @staticmethod
    async def _merge_nanomaterials(
        session: Any,
        nanomaterials: list[ExtractedNanomaterial],
        source_id: str,
    ) -> int:
        """Batch MERGE Nanomaterial nodes (Compound + Nanomaterial labels)."""
        params = []
        for nm in nanomaterials:
            params.append(
                {
                    "name": nm.name,
                    "iupac_name": nm.iupac_name,
                    "cas_number": nm.cas_number,
                    "canonical_smiles": nm.canonical_smiles,
                    "inchikey": nm.inchikey,
                    "molecular_weight": nm.molecular_weight,
                    "log_p": nm.log_p,
                    "hlb_value": nm.hlb_value,
                    "ph_stability_min": nm.ph_stability_min,
                    "ph_stability_max": nm.ph_stability_max,
                    "solubility_g_per_l": nm.solubility_g_per_l,
                    "zeta_potential_mv": nm.zeta_potential_mv,
                    "particle_size_nm": nm.particle_size_nm,
                    "pdi": nm.pdi,
                    "encapsulation_efficiency": nm.encapsulation_efficiency,
                    "delivery_vector_type": nm.delivery_vector_type,
                    "cargo_type": nm.cargo_type,
                    "compound_class": nm.compound_class.value if nm.compound_class else "nanomaterial",
                    "confidence": nm.confidence,
                    "source_context": nm.source_context,
                }
            )

        await session.run(
            """
            UNWIND $batch AS row
            MERGE (nm:Nanomaterial {name: row.name})
            SET nm:Compound,
                nm += {
                    iupac_name:              coalesce(row.iupac_name, nm.iupac_name),
                    cas_number:              coalesce(row.cas_number, nm.cas_number),
                    canonical_smiles:        coalesce(row.canonical_smiles, nm.canonical_smiles),
                    inchikey:                coalesce(row.inchikey, nm.inchikey),
                    molecular_weight:        coalesce(row.molecular_weight, nm.molecular_weight),
                    log_p:                   coalesce(row.log_p, nm.log_p),
                    hlb_value:               coalesce(row.hlb_value, nm.hlb_value),
                    ph_stability_min:        coalesce(row.ph_stability_min, nm.ph_stability_min),
                    ph_stability_max:        coalesce(row.ph_stability_max, nm.ph_stability_max),
                    solubility_g_per_l:      coalesce(row.solubility_g_per_l, nm.solubility_g_per_l),
                    zeta_potential_mv:       coalesce(row.zeta_potential_mv, nm.zeta_potential_mv),
                    particle_size_nm:        coalesce(row.particle_size_nm, nm.particle_size_nm),
                    pdi:                     coalesce(row.pdi, nm.pdi),
                    encapsulation_efficiency: coalesce(row.encapsulation_efficiency, nm.encapsulation_efficiency),
                    delivery_vector_type:    coalesce(row.delivery_vector_type, nm.delivery_vector_type),
                    cargo_type:              coalesce(row.cargo_type, nm.cargo_type),
                    compound_class:          row.compound_class,
                    updated_at:              datetime()
                }
            WITH nm, row
            MATCH (d:Document {source_id: $source_id})
            MERGE (nm)-[r:EXTRACTED_FROM]->(d)
            SET r.confidence     = row.confidence,
                r.source_context = row.source_context
            """,
            {"batch": params, "source_id": source_id},
        )
        return len(params)

    # ── FunctionalCategory Linking ───────────────────────────────────────

    @staticmethod
    async def _link_categories(
        session: Any, result: ExtractionResult
    ) -> int:
        """
        Create FunctionalCategory nodes and link entities to them.

        Builds the taxonomy layer of the graph.
        """
        count = 0

        # Compounds
        for c in result.compounds:
            if c.functional_categories:
                cats = [fc.value for fc in c.functional_categories]
                await session.run(
                    """
                    UNWIND $categories AS cat_name
                    MERGE (fc:FunctionalCategory {name: cat_name})
                    WITH fc, cat_name
                    MATCH (c:Compound {name: $compound_name})
                    MERGE (c)-[:CATEGORIZED_AS]->(fc)
                    """,
                    {"categories": cats, "compound_name": c.name},
                )
                count += len(cats)

        # Biologicals
        for b in result.biologicals:
            if b.functional_categories:
                cats = [fc.value for fc in b.functional_categories]
                await session.run(
                    """
                    UNWIND $categories AS cat_name
                    MERGE (fc:FunctionalCategory {name: cat_name})
                    WITH fc, cat_name
                    MATCH (b:Biological {organism_name: $organism_name})
                    MERGE (b)-[:CATEGORIZED_AS]->(fc)
                    """,
                    {"categories": cats, "organism_name": b.organism_name},
                )
                count += len(cats)

        # Peptides
        for p in result.peptides:
            if p.functional_categories:
                cats = [fc.value for fc in p.functional_categories]
                await session.run(
                    """
                    UNWIND $categories AS cat_name
                    MERGE (fc:FunctionalCategory {name: cat_name})
                    WITH fc, cat_name
                    MATCH (p:Peptide {name: $peptide_name})
                    MERGE (p)-[:CATEGORIZED_AS]->(fc)
                    """,
                    {"categories": cats, "peptide_name": p.name},
                )
                count += len(cats)

        # Nanomaterials
        for nm in result.nanomaterials:
            if nm.functional_categories:
                cats = [fc.value for fc in nm.functional_categories]
                await session.run(
                    """
                    UNWIND $categories AS cat_name
                    MERGE (fc:FunctionalCategory {name: cat_name})
                    WITH fc, cat_name
                    MATCH (nm:Nanomaterial {name: $nm_name})
                    MERGE (nm)-[:CATEGORIZED_AS]->(fc)
                    """,
                    {"categories": cats, "nm_name": nm.name},
                )
                count += len(cats)

        return count

    # ── Inter-Entity Relationships ───────────────────────────────────────

    @staticmethod
    async def _merge_relationships(
        session: Any,
        relationships: list[ExtractedRelationship],
        source_id: str,
    ) -> int:
        """
        Merge all inter-entity relationships.

        Uses APOC-free dynamic relationship creation via FOREACH + CASE,
        since Neo4j Community edition doesn't have APOC.

        Each relationship type gets its own batched MERGE query to ensure
        the correct relationship type is created in Cypher.
        """
        # Group relationships by type for efficient batching
        grouped: dict[str, list[dict]] = {}
        for rel in relationships:
            rel_type = rel.relationship_type
            if rel_type not in grouped:
                grouped[rel_type] = []
            grouped[rel_type].append(
                {
                    "source_entity": rel.source_entity,
                    "target_entity": rel.target_entity,
                    "ratio": rel.ratio,
                    "ph": rel.ph,
                    "temperature_c": rel.temperature_c,
                    "mechanism": rel.mechanism,
                    "physical_state": rel.physical_state,
                    "target_use": rel.target_use,
                    "status": rel.status,
                    "reason": rel.reason,
                    "confidence": rel.confidence,
                    "source_context": rel.source_context,
                    "is_negative_data": rel.is_negative_data,
                }
            )

        total = 0
        for rel_type, batch in grouped.items():
            # Build the MERGE query with the specific relationship type.
            # We match source/target across ALL entity labels using
            # a union-match pattern.
            query = f"""
            UNWIND $batch AS row
            CALL {{
                WITH row
                OPTIONAL MATCH (s:Compound {{name: row.source_entity}})
                RETURN s AS source
                UNION ALL
                WITH row
                OPTIONAL MATCH (s:Biological {{organism_name: row.source_entity}})
                RETURN s AS source
            }}
            WITH row, source WHERE source IS NOT NULL
            CALL {{
                WITH row
                OPTIONAL MATCH (t:Compound {{name: row.target_entity}})
                RETURN t AS target
                UNION ALL
                WITH row
                OPTIONAL MATCH (t:Biological {{organism_name: row.target_entity}})
                RETURN t AS target
            }}
            WITH row, source, target WHERE target IS NOT NULL
            MERGE (source)-[r:{rel_type}]->(target)
            SET r += {{
                ratio:           row.ratio,
                ph:              row.ph,
                temperature_c:   row.temperature_c,
                mechanism:       row.mechanism,
                physical_state:  row.physical_state,
                target_use:      row.target_use,
                status:          row.status,
                reason:          row.reason,
                confidence:      row.confidence,
                source_context:  row.source_context,
                is_negative_data: row.is_negative_data,
                source_id:       $source_id,
                updated_at:      datetime()
            }}
            """

            try:
                await session.run(
                    query, {"batch": batch, "source_id": source_id}
                )
                total += len(batch)
            except Exception as e:
                logger.error(
                    "Failed to merge %d %s relationships: %s",
                    len(batch),
                    rel_type,
                    str(e),
                )
                # Fallback: try one-by-one
                for item in batch:
                    try:
                        await session.run(
                            query, {"batch": [item], "source_id": source_id}
                        )
                        total += 1
                    except Exception:
                        logger.debug(
                            "Skipped relationship: %s -[%s]-> %s",
                            item["source_entity"],
                            rel_type,
                            item["target_entity"],
                        )

        return total
