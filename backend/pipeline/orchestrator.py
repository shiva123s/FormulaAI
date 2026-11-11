"""
FormulaAI — Celery Pipeline Orchestrator

This module defines the Celery application and the main task pipeline
that chains: Ingestion -> Parsing -> Extraction -> Normalization -> Graph Loading.

Because our core components (Connectors, GeminiExtractor, GraphLoader)
are highly async, this Celery worker spins up an asyncio event loop
per task to execute them.
"""

import asyncio
import logging
from typing import Any
from celery import Celery

from config import get_settings
from ingestion.openalex import OpenAlexConnector
from ingestion.patents import PatentConnector
from ingestion.chembl import ChEMBLConnector
from ingestion.pubmed import PubMedConnector
from ingestion.fda_iid import FDAIIDConnector
from ingestion.epa_inert import EPAInertConnector
from ingestion.tds_sds_scraper import TDSSDSScraper
from parsing.pdf_parser import PDFParser
from extraction.extractor import GeminiExtractor
from normalization.rdkit_resolver import RDKitResolver
from normalization.pubchem_resolver import PubChemResolver
from graph.connection import get_neo4j
from graph.loader import GraphLoader

logger = logging.getLogger(__name__)

settings = get_settings()

celery_app = Celery(
    "formula_pipeline",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)


def get_connector(source_type: str) -> Any:
    """Factory method for ingestion connectors."""
    connectors = {
        "openalex": OpenAlexConnector,
        "patent": PatentConnector,
        "chembl": ChEMBLConnector,
        "pubmed": PubMedConnector,
        "fda_iid": FDAIIDConnector,
        "epa_inert": EPAInertConnector,
        "tds": TDSSDSScraper,
        "sds": TDSSDSScraper,
        "paper": OpenAlexConnector,  # Default mapping
    }
    connector_class = connectors.get(source_type)
    if not connector_class:
        raise ValueError(f"Unknown source_type: {source_type}")
    return connector_class()


async def _run_extraction_pipeline_async(job_id: str, source_type: str, source_args: dict) -> dict:
    """
    Async core of the pipeline execution.
    """
    logger.info("Pipeline [%s] Started: %s with args %s", job_id, source_type, source_args)

    # 1. Initialize Components
    connector = get_connector(source_type)
    parser = PDFParser()
    extractor = GeminiExtractor()
    rdkit_resolver = RDKitResolver()
    pubchem_resolver = PubChemResolver()

    neo4j = get_neo4j()
    await neo4j.connect()
    graph_loader = GraphLoader(neo4j)

    results_summary = {
        "source_type": source_type,
        "documents_processed": 0,
        "entities_extracted": 0,
        "relationships_extracted": 0,
        "graph_nodes_merged": 0,
        "errors": [],
    }

    try:
        # 2. Ingestion
        logger.info("Pipeline [%s] Phase 1: Ingestion", job_id)
        raw_documents = []
        if "query" in source_args:
            async for doc in connector.search(source_args["query"], limit=1):
                raw_documents.append(doc)
        elif "id" in source_args:
            doc = await connector.fetch_by_id(source_args["id"])
            if doc:
                raw_documents.append(doc)
        else:
            raise ValueError("source_args must contain 'query' or 'id' to fetch data.")

        results_summary["documents_processed"] = len(raw_documents)
        if not raw_documents:
            logger.warning("Pipeline [%s] No documents found.", job_id)
            return results_summary

        # 3. Parsing & 4. Extraction
        logger.info("Pipeline [%s] Phase 2 & 3: Parsing & LLM Extraction", job_id)
        extracted_results = []
        for raw_doc in raw_documents:
            ext_result = await extractor.extract_from_raw_document(raw_doc)
            extracted_results.append(ext_result)
            results_summary["entities_extracted"] += ext_result.total_entities
            results_summary["relationships_extracted"] += ext_result.total_relationships

        # 5. Normalization (RDKit / PubChem validation of ExtractedCompounds)
        logger.info("Pipeline [%s] Phase 4: Normalization", job_id)
        for ext_result in extracted_results:
            for compound in ext_result.compounds:
                # 5a. Validate existing SMILES via RDKit
                if getattr(compound, "canonical_smiles", None):
                    norm = rdkit_resolver.compute_properties(compound.canonical_smiles)
                    if norm is not None and norm.canonical_smiles:
                        compound.canonical_smiles = norm.canonical_smiles
                        compound.inchikey = norm.inchikey or getattr(compound, "inchikey", None)
                        compound.molecular_weight = (
                            compound.molecular_weight or norm.molecular_weight
                        )
                        compound.log_p = (
                            compound.log_p if getattr(compound, "log_p", None) is not None else norm.log_p
                        )
                    else:
                        # Clear invalid SMILES so 5b can attempt PubChem resolution by name
                        compound.canonical_smiles = None

                # 5b. Fallback to PubChem resolution by name if SMILES is absent or invalidated
                if not getattr(compound, "canonical_smiles", None) and getattr(compound, "name", None):
                    pc_norm = await pubchem_resolver.resolve_by_name(compound.name)
                    if pc_norm is not None and getattr(pc_norm, "canonical_smiles", None):
                        compound.canonical_smiles = pc_norm.canonical_smiles
                        compound.molecular_weight = (
                            compound.molecular_weight or pc_norm.molecular_weight
                        )
                        if getattr(pc_norm, "cas_number", None) and hasattr(compound, "cas_number"):
                            compound.cas_number = compound.cas_number or pc_norm.cas_number

                        # Compute InChIKey and LogP via RDKit from the resolved PubChem SMILES
                        rd_norm = rdkit_resolver.compute_properties(compound.canonical_smiles)
                        if rd_norm is not None:
                            compound.inchikey = rd_norm.inchikey or getattr(compound, "inchikey", None)
                            compound.log_p = (
                                compound.log_p if getattr(compound, "log_p", None) is not None else rd_norm.log_p
                            )

        # 6. Graph Load
        logger.info("Pipeline [%s] Phase 5: Graph Load", job_id)
        load_stats = await graph_loader.load_batch(extracted_results)

        for stat in load_stats:
            results_summary["graph_nodes_merged"] += stat.total_nodes
            if not stat.success:
                results_summary["errors"].extend(stat.errors)

        logger.info("Pipeline [%s] Completed Successfully.", job_id)
        return results_summary

    except Exception as e:
        logger.exception("Pipeline [%s] failed", job_id)
        results_summary["errors"].append(str(e))
        raise
    finally:
        # Cleanup Neo4j Connection
        await neo4j.close()


@celery_app.task(bind=True, name="pipeline.run_extraction")
def run_extraction_pipeline(self, source_type: str, source_args: dict) -> dict:
    """
    Celery task entrypoint.
    Executes the fully async pipeline workflow using asyncio.run.
    """
    job_id = self.request.id
    return asyncio.run(_run_extraction_pipeline_async(job_id, source_type, source_args))