"""
FormulaAI — LangGraph Orchestration (Sequential Pipeline)

Constructs the StateGraph, defining the nodes (agents) and the conditional
edges that control the flow of the formulation process.
"""
import asyncio
import logging
from typing import Sequence
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from config import get_settings

from agents.state import FormulationState
from agents.personas import (
    FORMULATION_CHEMIST_PROMPT,
    BIOSTABILITY_EXPERT_PROMPT,
    TOXICITY_REGULATORY_EXPERT_PROMPT,
)
from agents.tools import (
    get_neo4j_context_for_active,
    search_global_patents,
    check_excipient_compatibility,
    find_stabilizers_for_target,
    check_epa_status,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize the Gemini LLM
llm = ChatGoogleGenerativeAI(
    model=settings.gemini_model_name,
    google_api_key=settings.google_api_key,
    temperature=0.2,
)

# Tool sets per specialist agent
CHEMIST_TOOLS: list[BaseTool] = [search_global_patents, check_excipient_compatibility]
BIOSTABILITY_TOOLS: list[BaseTool] = [search_global_patents, find_stabilizers_for_target]
TOXICITY_TOOLS: list[BaseTool] = [check_epa_status, search_global_patents]


def extract_text_content(content) -> str:
    """Safely extracts a clean string from message content which can be str or list of parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if "text" in item:
                    parts.append(str(item["text"]))
                elif "content" in item:
                    parts.append(str(item["content"]))
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content or "")


async def execute_single_tool(tool_obj: BaseTool, tool_args: dict) -> str:
    """
    Executes either an async Neo4j tool or the sync Snowflake tool without
    blocking the FastAPI event loop.
    """
    try:
        if getattr(tool_obj, "coroutine", None) is not None:
            return str(await tool_obj.ainvoke(tool_args))
        # Run synchronous tools (like Snowflake search_global_patents) in a worker thread
        return str(await asyncio.to_thread(tool_obj.invoke, tool_args))
    except Exception as exc:
        logger.warning("Tool '%s' execution error: %s", tool_obj.name, exc)
        return f'{{"status": "error", "message": "{exc}"}}'


async def invoke_with_tools(
    messages: Sequence[BaseMessage],
    tools: Sequence[BaseTool],
    max_rounds: int = 3,
) -> AIMessage:
    """
    Binds tools to Gemini, executes any requested tool_calls (Snowflake C-RAG or Neo4j)
    across up to `max_rounds`, and returns a clean final AIMessage with synthesized text.
    """
    tool_map = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)
    local_messages: list[BaseMessage] = list(messages)

    for round_idx in range(max_rounds):
        response: AIMessage = await llm_with_tools.ainvoke(local_messages)
        local_messages.append(response)

        # If no tool calls were requested, Gemini has finished its synthesis
        if not getattr(response, "tool_calls", None):
            return response

        for tc in response.tool_calls:
            t_name = tc.get("name", "")
            t_args = tc.get("args", {}) or {}
            t_id = tc.get("id", t_name)

            logger.info("[Tool Round %d] Calling %s(%s)", round_idx + 1, t_name, t_args)
            tool_obj = tool_map.get(t_name)

            if tool_obj is None:
                tool_output = f'{{"status": "error", "message": "Unknown tool {t_name}"}}'
            else:
                tool_output = await execute_single_tool(tool_obj, t_args)

            local_messages.append(
                ToolMessage(
                    content=tool_output,
                    name=t_name,
                    tool_call_id=t_id,
                )
            )

    # If max_rounds of tool calling were reached, invoke plain `llm` (no tools bound)
    # to guarantee a final written formulation/review response.
    local_messages.append(
        HumanMessage(
            content="Using the tool results above, now provide your complete written analysis and recipe."
        )
    )
    final_response: AIMessage = await llm.ainvoke(local_messages)
    return final_response


# --- Node Definitions ---

async def formulation_chemist_node(state: FormulationState):
    """The Formulation Chemist drafts or revises the recipe using Knowledge Graph & Snowflake Patent context."""
    kg_context = await get_neo4j_context_for_active(
        state["active_ingredient"], state["target_pest"]
    )

    prompt = (
        f"{FORMULATION_CHEMIST_PROMPT}\n\n"
        f"--- KNOWLEDGE GRAPH EVIDENCE ---\n{kg_context}\n\n"
        f"Target Parameters:\n"
        f"- Active Ingredient: {state['active_ingredient']}\n"
        f"- Target Pest / Pathogen: {state['target_pest']}\n"
        f"- Payload Type: {state['payload_type']}\n\n"
        "Instructions:\n"
        "1. Use `search_global_patents` to find empirical patent grounding in Snowflake and `check_excipient_compatibility` if needed.\n"
        "2. Recommend a specific formulation type (e.g. SC, EC, OD, WP, WDG, Microencapsulation).\n"
        "3. Provide a clear recipe table with: Role (Active Ingredient, Surfactant/Emulsifier, Protectant/Stabilizer, Carrier), Ingredient Name, Amount (% w/w or % v/v), and Citation (patent number e.g. US-10849321-B2, BR-112021008412-A2, DOI, or EPA List 4B).\n"
        "4. Provide scientific rationale for excipient compatibility, stability, delivery mechanism, and literature grounding."
    )

    messages = [SystemMessage(content=prompt)] + list(state["messages"])

    if state["toxicity_approval_status"] == "REJECTED":
        messages.append(
            HumanMessage(
                content="Revise the formulation to address the previous feedback from toxicity and regulatory review."
            )
        )

    response = await invoke_with_tools(messages, CHEMIST_TOOLS)
    text_content = extract_text_content(response.content)

    # Store a clean AIMessage without raw tool_calls so downstream nodes have valid history
    clean_ai_message = AIMessage(content=text_content, name="formulation_chemist")

    new_revision_count = (
        state["revision_count"] + 1
        if state["toxicity_approval_status"] == "REJECTED"
        else state["revision_count"]
    )

    return {
        "messages": [clean_ai_message],
        "current_draft": text_content,
        "revision_count": new_revision_count,
        "toxicity_approval_status": "PENDING",
    }


async def biostability_expert_node(state: FormulationState):
    """The BioStability Expert reviews for payload protection and environmental resilience."""
    prompt = (
        f"{BIOSTABILITY_EXPERT_PROMPT}\n\n"
        f"Active Ingredient: {state['active_ingredient']}\n"
        f"Payload Type: {state['payload_type']}\n\n"
        f"Review the following formulation recipe for payload stability, UV protection, and viability:\n\n"
        f"{state['current_draft']}\n\n"
        "You may call `find_stabilizers_for_target` or `search_global_patents` once if needed, "
        "then provide your analysis of protective excipients, antioxidant/UV blockers, and overall biostability."
    )
    messages = [SystemMessage(content=prompt)] + list(state["messages"])
    response = await invoke_with_tools(messages, BIOSTABILITY_TOOLS)
    text_content = extract_text_content(response.content)

    clean_ai_message = AIMessage(content=text_content, name="biostability_expert")
    return {"messages": [clean_ai_message]}


async def toxicity_expert_node(state: FormulationState):
    """The Toxicity Expert checks regulatory compliance (EPA/FIFRA) and environmental safety."""
    prompt = (
        f"{TOXICITY_REGULATORY_EXPERT_PROMPT}\n\n"
        f"Active Ingredient: {state['active_ingredient']}\n\n"
        f"Review this formulation draft for regulatory approval (EPA 4A/4B inert list, pollinator safety, aquatic toxicity):\n\n"
        f"{state['current_draft']}\n\n"
        "You may use `check_epa_status` to verify co-formulants. "
        "Conclude with your final assessment and clearly state whether this formulation is APPROVED or REJECTED."
    )
    messages = [SystemMessage(content=prompt)] + list(state["messages"])
    response = await invoke_with_tools(messages, TOXICITY_TOOLS)
    text_content = extract_text_content(response.content)

    status = (
        "REJECTED"
        if "REJECT" in text_content.upper() or "NOT APPROVED" in text_content.upper()
        else "APPROVED"
    )

    clean_ai_message = AIMessage(content=text_content, name="toxicity_expert")
    return {
        "messages": [clean_ai_message],
        "toxicity_approval_status": status,
    }


# --- Routing Logic (Conditional Edges) ---

def route_after_chemist(state: FormulationState):
    """Route to BioStability if needed, otherwise straight to Toxicity."""
    if str(state.get("payload_type", "")).lower() in ["peptide", "microbe", "rnai", "biological"]:
        return "biostability_expert"
    return "toxicity_expert"


def route_after_toxicity(state: FormulationState):
    """Route to END if approved, back to Chemist if rejected (with limit)."""
    if state["toxicity_approval_status"] == "APPROVED":
        return "end"
    if state["revision_count"] >= 3:
        # Prevent infinite loops. Force an end if we can't get approval.
        return "end"
    return "formulation_chemist"


# --- Build the Graph ---

builder = StateGraph(FormulationState)

# Add Nodes
builder.add_node("formulation_chemist", formulation_chemist_node)
builder.add_node("biostability_expert", biostability_expert_node)
builder.add_node("toxicity_expert", toxicity_expert_node)

# Add Edges
builder.add_edge(START, "formulation_chemist")

# Add Conditional Edges
builder.add_conditional_edges(
    "formulation_chemist",
    route_after_chemist,
    {
        "biostability_expert": "biostability_expert",
        "toxicity_expert": "toxicity_expert",
    },
)

builder.add_edge("biostability_expert", "toxicity_expert")

builder.add_conditional_edges(
    "toxicity_expert",
    route_after_toxicity,
    {
        "end": END,
        "formulation_chemist": "formulation_chemist",
    },
)

# Compile the graph
formulation_graph = builder.compile()