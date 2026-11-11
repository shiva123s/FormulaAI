"""
FormulaAI — Agent Orchestrator

Provides the entry point to run the compiled LangGraph pipeline.
"""
import asyncio
from langchain_core.messages import HumanMessage
from fastapi import WebSocket
from agents.graph import formulation_graph

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

async def run_formulation_agent(
    user_prompt: str,
    active_ingredient: str,
    target_pest: str,
    payload_type: str = "chemical",
    websocket: WebSocket | None = None
):
    """
    Initializes the state and runs the formulation pipeline.
    Streams progress over the WebSocket if provided.
    """
    msg = f"--- Starting Formulation Pipeline for: {active_ingredient} ---"
    print(msg)
    if websocket:
        await websocket.send_json({"type": "info", "message": msg})
    
    initial_state = {
        "messages": [HumanMessage(content=user_prompt)],
        "target_pest": target_pest,
        "active_ingredient": active_ingredient,
        "payload_type": payload_type,
        "current_draft": "",
        "toxicity_approval_status": "PENDING",
        "revision_count": 0
    }

    # Stream the output as the graph executes
    config = {"recursion_limit": 10}
    latest_draft = ""

    async for event in formulation_graph.astream(initial_state, config=config):
        for node_name, state_update in event.items():
            print(f"\n[{node_name.upper()}]:")
            if websocket:
                await websocket.send_json({"type": "node_start", "node": node_name})

            # Track latest draft from whichever node created it
            if "current_draft" in state_update and state_update["current_draft"]:
                latest_draft = extract_text_content(state_update["current_draft"])

            # Print the most recent message added to the state
            if "messages" in state_update and state_update["messages"]:
                last_message = state_update["messages"][-1]
                content = extract_text_content(last_message.content)
                
                # If the agent called a tool, content might be empty. Extract the tool name.
                if not content and hasattr(last_message, "tool_calls") and last_message.tool_calls:
                    tool_names = ", ".join([tc["name"] for tc in last_message.tool_calls])
                    content = f"Invoking tools: {tool_names}..."

                print(content)
                if websocket and content:
                    await websocket.send_json({
                        "type": "message", 
                        "node": node_name, 
                        "content": content
                    })
            
            if "toxicity_approval_status" in state_update:
                status = state_update["toxicity_approval_status"]
                print(f">> Approval Status: {status}")
                
                recipe_json = None
                if status == "APPROVED":
                    try:
                        from pydantic import BaseModel, Field
                        from typing import List, Optional
                        from langchain_google_genai import ChatGoogleGenerativeAI
                        from config import get_settings

                        class RecipeItem(BaseModel):
                            role: str
                            name: str
                            amount: str
                            citation: Optional[str] = Field(
                                default=None,
                                description="The patent number, DOI, or source document validating this ingredient's use."
                            )

                        class FinalRecipe(BaseModel):
                            items: List[RecipeItem]
                            
                        settings = get_settings()
                        extract_llm = ChatGoogleGenerativeAI(
                            model=settings.gemini_model_name,
                            google_api_key=settings.google_api_key,
                            temperature=0
                        )
                        structured_llm = extract_llm.with_structured_output(FinalRecipe)
                        
                        prompt_text = (
                            f"Extract or generate the structured recipe items (role, name, amount, citation) from this formulation draft: "
                            f"'{latest_draft}'. Active Ingredient: {active_ingredient}. Target: {target_pest}. "
                            f"Ensure each item has: role, name, amount, and citation (e.g. patent number like US Patent 10,842,154, WO2021/045812, DOI, or EPA List 4B)."
                        )
                        extracted = await structured_llm.ainvoke(prompt_text)
                        if extracted and hasattr(extracted, "items"):
                            recipe_json = [
                                item.model_dump() if hasattr(item, "model_dump") else item.dict()
                                for item in extracted.items
                            ]
                    except Exception as e:
                        print(f"Error extracting recipe: {e}")

                if websocket:
                    payload = {
                        "type": "status", 
                        "node": node_name, 
                        "status": status
                    }
                    if recipe_json:
                        payload["recipe"] = recipe_json
                    await websocket.send_json(payload)

if __name__ == "__main__":
    # Example usage for a simple chemical formulation
    test_prompt = "Design an emulsifiable concentrate (EC) formulation for Glyphosate targeting broadleaf weeds. I need it to be stable and have good leaf retention."
    
    # Run the pipeline (using asyncio for the async LangChain tools)
    asyncio.run(run_formulation_agent(
        user_prompt=test_prompt,
        active_ingredient="Glyphosate",
        target_pest="Broadleaf weeds",
        payload_type="chemical"
    ))
