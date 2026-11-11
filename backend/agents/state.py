"""
FormulaAI — Multi-Agent State Definition

Defines the shared memory (State) passed between the LangGraph nodes.
"""
from typing import TypedDict, Annotated, Sequence, Literal
from langchain_core.messages import BaseMessage  # type: ignore
import operator

class FormulationState(TypedDict):
    """
    The shared state for the formulation pipeline.
    """
    # Conversation history. The 'reducer' ensures messages are appended, not overwritten.
    messages: Annotated[Sequence[BaseMessage], operator.add]
    
    # Metadata extracted from the user's initial request
    target_pest: str
    active_ingredient: str
    payload_type: Literal["chemical", "peptide", "microbe", "rnai", "unknown"]
    
    # Track the pipeline progress and approvals
    current_draft: str
    toxicity_approval_status: Literal["PENDING", "APPROVED", "REJECTED"]
    revision_count: int
