"""
FormulaAI — Centralized Configuration

All environment variables are loaded via Pydantic BaseSettings.
Supports .env files and direct environment variable injection.
"""

import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application-wide settings loaded from environment variables."""

    # ── Neo4j ────────────────────────────────────────────────────────────
    neo4j_uri: str = Field("bolt://localhost:7687", alias="NEO4J_URI")
    neo4j_username: str = Field("neo4j", alias="NEO4J_USERNAME")
    neo4j_password: str = Field("password", alias="NEO4J_PASSWORD")

    # ── Redis ────────────────────────────────────────────────────────────
    redis_url: str = Field("redis://localhost:6379", alias="REDIS_URL")

    # ── Google Gemini (LLM Provider) ─────────────────────────────────────
    google_api_key: str = Field("", alias="GOOGLE_API_KEY")
    gemini_model_name: str = Field("gemini-3.1-pro-preview", alias="GEMINI_MODEL_NAME")

    # ── PubChem ──────────────────────────────────────────────────────────
    pubchem_api_base: str = Field(
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug",
        alias="PUBCHEM_API_BASE",
    )

    # ── OpenAlex ─────────────────────────────────────────────────────────
    openalex_api_base: str = Field(
        "https://api.openalex.org", alias="OPENALEX_API_BASE"
    )
    openalex_email: str = Field("", alias="OPENALEX_EMAIL")

    # ── NCBI (PubMed / Taxonomy) ─────────────────────────────────────────
    ncbi_api_key: str = Field("", alias="NCBI_API_KEY")
    ncbi_email: str = Field("", alias="NCBI_EMAIL")
    ncbi_eutils_base: str = Field(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        alias="NCBI_EUTILS_BASE",
    )

    # ── Semantic Scholar ─────────────────────────────────────────────────
    semantic_scholar_api_key: str = Field("", alias="SEMANTIC_SCHOLAR_API_KEY")

    # ── ChEMBL ───────────────────────────────────────────────────────────
    chembl_api_base: str = Field(
        "https://www.ebi.ac.uk/chembl/api/data", alias="CHEMBL_API_BASE"
    )

    # ── EPA INERTFinder ──────────────────────────────────────────────────
    epa_inert_api_base: str = Field("", alias="EPA_INERT_API_BASE")

    # ── Snowflake (Enterprise Patent C-RAG) ──────────────────────────────
    snowflake_account: str = Field("", alias="SNOWFLAKE_ACCOUNT")
    snowflake_user: str = Field("", alias="SNOWFLAKE_USER")
    snowflake_password: str = Field("", alias="SNOWFLAKE_PASSWORD")
    snowflake_warehouse: str = Field("FORMULA_APP_WH", alias="SNOWFLAKE_WAREHOUSE")
    snowflake_database: str = Field("FORMULA_KNOWLEDGE_DB", alias="SNOWFLAKE_DATABASE")
    snowflake_schema: str = Field("GLOBAL_PATENTS", alias="SNOWFLAKE_SCHEMA")

    @property
    def is_snowflake_configured(self) -> bool:
        """Return True when all required Snowflake credentials are set."""
        return bool(self.snowflake_account and self.snowflake_user and self.snowflake_password)

    # ── Celery (Task Queue) ──────────────────────────────────────────────
    celery_broker_url: str = Field(
        "redis://localhost:6379/1", alias="CELERY_BROKER_URL"
    )
    celery_result_backend: str = Field(
        "redis://localhost:6379/2", alias="CELERY_RESULT_BACKEND"
    )

    # ── Rate Limits (requests per second) ────────────────────────────────
    pubchem_rate_limit: float = Field(5.0, alias="PUBCHEM_RATE_LIMIT")
    openalex_rate_limit: float = Field(10.0, alias="OPENALEX_RATE_LIMIT")
    pubmed_rate_limit: float = Field(3.0, alias="PUBMED_RATE_LIMIT")
    chembl_rate_limit: float = Field(15.0, alias="CHEMBL_RATE_LIMIT")
    ncbi_rate_limit: float = Field(3.0, alias="NCBI_RATE_LIMIT")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "populate_by_name": True,
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton of application settings."""
    return Settings()
