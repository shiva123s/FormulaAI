"""
FormulaAI — Ingestion Connectors Package

Modular async connectors for all data sources:
  • Patents   — USPTO PatentsView, EPO OPS, WIPO
  • Literature — OpenAlex, PubMed/PubChem, CrossRef, Semantic Scholar
  • Pharma    — FDA Inactive Ingredient Database, ChEMBL
  • Regulatory — EPA INERTFinder
  • Documents — TDS/SDS web scraper

All connectors inherit from BaseConnector and share:
  • Async httpx client
  • Per-source rate limiting (aiolimiter)
  • Retry with exponential backoff (tenacity)
  • Structured RawDocument output
"""

from ingestion.base import BaseConnector, RawDocument
from ingestion.openalex import OpenAlexConnector
from ingestion.pubmed import PubMedConnector
from ingestion.patents import PatentConnector
from ingestion.chembl import ChEMBLConnector
from ingestion.fda_iid import FDAIIDConnector
from ingestion.epa_inert import EPAInertConnector

__all__ = [
    "BaseConnector",
    "RawDocument",
    "OpenAlexConnector",
    "PubMedConnector",
    "PatentConnector",
    "ChEMBLConnector",
    "FDAIIDConnector",
    "EPAInertConnector",
]
