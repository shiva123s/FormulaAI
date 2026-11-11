"""
FormulaAI — Multi-Agent LangGraph Pipeline Unit Tests

Tests invoke_with_tools, agent specialist nodes, fallback responses, and tool resolution.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
from langchain_core.tools import tool

from agents.graph import (
    execute_single_tool,
    invoke_with_tools,
    extract_text_content,
    route_after_chemist,
    route_after_toxicity,
)
from agents.state import FormulationState


# ── Test Tools ─────────────────────────────────────────────────────────────────

@tool
def sample_sync_tool(query: str) -> str:
    """A sample synchronous tool."""
    return f"sync_result_for_{query}"


@tool
async def sample_async_tool(query: str) -> str:
    """A sample asynchronous tool."""
    return f"async_result_for_{query}"


# ── Test Suite ─────────────────────────────────────────────────────────────────

class TestExtractTextContent:
    def test_extract_from_string(self):
        assert extract_text_content("hello world") == "hello world"

    def test_extract_from_list_of_strings(self):
        assert extract_text_content(["line 1", "line 2"]) == "line 1\nline 2"

    def test_extract_from_dict_parts(self):
        parts = [{"text": "First part"}, {"content": "Second part"}]
        assert extract_text_content(parts) == "First part\nSecond part"

    def test_extract_from_none(self):
        assert extract_text_content(None) == ""


class TestExecuteSingleTool:
    @pytest.mark.asyncio
    async def test_execute_async_tool(self):
        res = await execute_single_tool(sample_async_tool, {"query": "test1"})
        assert "async_result_for_test1" in res

    @pytest.mark.asyncio
    async def test_execute_sync_tool(self):
        res = await execute_single_tool(sample_sync_tool, {"query": "test2"})
        assert "sync_result_for_test2" in res

    @pytest.mark.asyncio
    async def test_execute_tool_handles_exceptions(self):
        failing_tool = MagicMock()
        failing_tool.name = "failing_tool"
        failing_tool.coroutine = None
        failing_tool.invoke.side_effect = RuntimeError("Tool crashed")

        res = await execute_single_tool(failing_tool, {})
        assert "error" in res
        assert "Tool crashed" in res


class TestInvokeWithTools:
    @pytest.mark.asyncio
    @patch("agents.graph.llm")
    async def test_returns_immediately_when_no_tool_calls(self, mock_llm):
        expected_response = AIMessage(content="Here is the final formulation.")
        mock_bound = AsyncMock()
        mock_bound.ainvoke.return_value = expected_response
        mock_llm.bind_tools.return_value = mock_bound

        messages = [HumanMessage(content="Design an EC formulation")]
        result = await invoke_with_tools(messages, [sample_sync_tool])

        assert result.content == "Here is the final formulation."
        assert mock_bound.ainvoke.call_count == 1

    @pytest.mark.asyncio
    @patch("agents.graph.llm")
    async def test_executes_tool_calls_and_returns_synthesis(self, mock_llm):
        # Round 1: Model calls sample_sync_tool
        msg_with_tool_call = AIMessage(
            content="",
            tool_calls=[{"name": "sample_sync_tool", "args": {"query": "glyphosate"}, "id": "call_123"}]
        )
        # Round 2: Model synthesizes final recipe after tool output
        final_msg = AIMessage(content="Formulation using patent US-10842154")

        mock_bound = AsyncMock()
        mock_bound.ainvoke.side_effect = [msg_with_tool_call, final_msg]
        mock_llm.bind_tools.return_value = mock_bound

        messages = [HumanMessage(content="Design glyphosate recipe")]
        result = await invoke_with_tools(messages, [sample_sync_tool])

        assert result.content == "Formulation using patent US-10842154"
        assert mock_bound.ainvoke.call_count == 2


class TestRoutingLogic:
    def test_route_after_chemist_biological(self):
        state_microbe: FormulationState = {
            "messages": [],
            "target_pest": "Aphids",
            "active_ingredient": "Beauveria bassiana",
            "payload_type": "microbe",
            "current_draft": "",
            "toxicity_approval_status": "PENDING",
            "revision_count": 0,
        }
        assert route_after_chemist(state_microbe) == "biostability_expert"

    def test_route_after_chemist_chemical(self):
        state_chem: FormulationState = {
            "messages": [],
            "target_pest": "Weeds",
            "active_ingredient": "Glyphosate",
            "payload_type": "chemical",
            "current_draft": "",
            "toxicity_approval_status": "PENDING",
            "revision_count": 0,
        }
        assert route_after_chemist(state_chem) == "toxicity_expert"

    def test_route_after_toxicity_approved(self):
        state: FormulationState = {
            "messages": [],
            "target_pest": "Pest",
            "active_ingredient": "Act",
            "payload_type": "chemical",
            "current_draft": "Draft",
            "toxicity_approval_status": "APPROVED",
            "revision_count": 0,
        }
        assert route_after_toxicity(state) == "end"

    def test_route_after_toxicity_rejected_within_limit(self):
        state: FormulationState = {
            "messages": [],
            "target_pest": "Pest",
            "active_ingredient": "Act",
            "payload_type": "chemical",
            "current_draft": "Draft",
            "toxicity_approval_status": "REJECTED",
            "revision_count": 1,
        }
        assert route_after_toxicity(state) == "formulation_chemist"

    def test_route_after_toxicity_rejected_max_revisions(self):
        state: FormulationState = {
            "messages": [],
            "target_pest": "Pest",
            "active_ingredient": "Act",
            "payload_type": "chemical",
            "current_draft": "Draft",
            "toxicity_approval_status": "REJECTED",
            "revision_count": 3,
        }
        assert route_after_toxicity(state) == "end"
