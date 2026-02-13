"""LangGraph agent state definition."""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State carried through the LangGraph agent loop.

    - messages: full conversation (system + user + assistant + tool messages)
    - ai_call_count: number of LLM invocations so far
    - total_input_tokens_est: estimated cumulative input tokens (chars / 4)
    - ai_*: org-level AI config overrides (set once from organization in run_agent)
    """
    messages: Annotated[list[BaseMessage], add_messages]
    ai_call_count: int
    total_input_tokens_est: int
    # AI config (org-level overrides, empty string = use global default)
    ai_api_key: str
    ai_bedrock_url: str
    ai_model_id: str
    ai_max_tokens: int
