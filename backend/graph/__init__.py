"""
FormulaAI — Neo4j Graph Module

Provides async Neo4j connectivity, schema management, and batch loading
for the agrochemical knowledge graph.

Components:
  • connection.py — Async driver pool (singleton)
  • schema.py    — Constraints, indexes, full-text indexes
  • loader.py    — Batch MERGE queries from ExtractionResult → Neo4j
"""

from graph.connection import Neo4jConnection, get_neo4j, reset_neo4j
from graph.schema import GraphSchema
from graph.loader import GraphLoader, LoadStats

__all__ = [
    "Neo4jConnection",
    "get_neo4j",
    "reset_neo4j",
    "GraphSchema",
    "GraphLoader",
    "LoadStats",
]
