"""
FormulaAI — Pipeline Event Models

Pydantic models representing the inputs and outputs of the Celery-based
extraction pipeline. Used by the FastAPI endpoints for request validation
and status reporting.
"""

from pydantic import BaseModel, Field
from typing import Any, Literal
from datetime import datetime

from extraction.schemas import SOURCE_TYPES


class PipelineJobRequest(BaseModel):
    """Request payload to start a new extraction job."""
    
    source_type: SOURCE_TYPES = Field(
        ..., description="Type of source (e.g., patent, paper, chembl, fda_iid)"
    )
    source_args: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments for the specific ingestion connector (e.g., {'patent_number': 'US10234567'})"
    )


class PipelineJobResponse(BaseModel):
    """Response returned immediately when a job is queued."""
    
    job_id: str = Field(..., description="Celery task ID")
    status: str = Field("queued", description="Initial status of the job")
    message: str = Field(..., description="Human-readable message")


class PipelineStatus(BaseModel):
    """Detailed status of a running or completed pipeline job."""
    
    job_id: str
    status: Literal["PENDING", "STARTED", "SUCCESS", "FAILURE", "RETRY", "REVOKED"]
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
