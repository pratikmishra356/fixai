"""Claude Bedrock LLM wrapper compatible with LangChain / LangGraph.

Uses the same Bedrock proxy pattern from claude_test.py but adds
tool-calling support for the agent loop.
"""

import json
import subprocess
from typing import Any, Iterator, List, Optional

import httpx
import structlog
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.config import settings

logger = structlog.get_logger(__name__)


def _get_api_key(override: str | None = None) -> str:
    """Get API key – org override > env var > helper binary."""
    if override:
        return override
    if settings.claude_api_key:
        return settings.claude_api_key
    try:
        result = subprocess.run(
            [settings.claude_api_key_helper_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception as exc:
        logger.error("api_key_helper_failed", error=str(exc))
        raise RuntimeError("Cannot obtain Claude API key") from exc


def _langchain_to_anthropic_messages(
    messages: List[BaseMessage],
) -> tuple[Optional[str], list[dict]]:
    """Convert LangChain messages to Anthropic API format.

    Returns (system_prompt, messages_list).
    """
    system_prompt: Optional[str] = None
    anthropic_msgs: list[dict] = []

    for msg in messages:
        if isinstance(msg, SystemMessage):
            system_prompt = msg.content
        elif isinstance(msg, HumanMessage):
            anthropic_msgs.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            content_blocks: list[dict] = []
            if msg.content:
                content_blocks.append({"type": "text", "text": msg.content})
            # Include tool_use blocks from additional_kwargs or tool_calls
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["args"],
                    })
            anthropic_msgs.append({"role": "assistant", "content": content_blocks or msg.content})
        elif isinstance(msg, ToolMessage):
            anthropic_msgs.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                ],
            })

    return system_prompt, anthropic_msgs


def _anthropic_tools_schema(tools: list[dict]) -> list[dict]:
    """Convert LangChain-style tool defs to Anthropic tool schema."""
    anthropic_tools = []
    for tool in tools:
        schema = tool.get("function", tool)
        anthropic_tools.append({
            "name": schema["name"],
            "description": schema.get("description", ""),
            "input_schema": schema.get("parameters", {"type": "object", "properties": {}}),
        })
    return anthropic_tools


class ClaudeBedrockChat(BaseChatModel):
    """Claude via Toast Bedrock proxy – LangChain-compatible."""

    model_id: str = Field(default_factory=lambda: settings.claude_model_id)
    bedrock_url: str = Field(default_factory=lambda: settings.claude_bedrock_url)
    max_tokens: int = Field(default_factory=lambda: settings.claude_max_tokens)
    api_key_override: str | None = None
    temperature: float = 0.0

    # Bind tools when agent is constructed
    _bound_tools: list[dict] = []

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "claude-bedrock"

    def bind_tools(self, tools: list, **kwargs) -> "ClaudeBedrockChat":
        """Return a copy with tools bound (LangGraph requirement)."""
        from langchain_core.tools import BaseTool

        tool_defs = []
        for t in tools:
            if isinstance(t, BaseTool):
                schema = t.get_input_schema().model_json_schema()
                # Remove title/definitions cruft
                schema.pop("title", None)
                schema.pop("definitions", None)
                tool_defs.append({
                    "name": t.name,
                    "description": t.description,
                    "parameters": schema,
                })
            elif isinstance(t, dict):
                tool_defs.append(t)
            else:
                raise ValueError(f"Unsupported tool type: {type(t)}")

        new = self.model_copy()
        new._bound_tools = tool_defs
        return new

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Call Claude synchronously (LangGraph uses this internally)."""
        api_key = _get_api_key(self.api_key_override)
        system_prompt, anthropic_msgs = _langchain_to_anthropic_messages(messages)

        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": anthropic_msgs,
        }
        if system_prompt:
            body["system"] = system_prompt
        if self._bound_tools:
            body["tools"] = _anthropic_tools_schema(self._bound_tools)

        logger.info(
            "claude_request",
            model=self.model_id,
            msg_count=len(anthropic_msgs),
            has_tools=bool(self._bound_tools),
        )

        resp = httpx.post(
            f"{self.bedrock_url}/bedrock/model/{self.model_id}/invoke",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> ChatResult:
        """Parse Anthropic response into LangChain ChatResult."""
        content_blocks = data.get("content", [])

        text_parts: list[str] = []
        tool_calls: list[dict] = []

        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block["id"],
                    "name": block["name"],
                    "args": block["input"],
                })

        text = "\n".join(text_parts)
        stop_reason = data.get("stop_reason", "end_turn")

        ai_msg = AIMessage(
            content=text,
            tool_calls=tool_calls if tool_calls else [],
            additional_kwargs={
                "stop_reason": stop_reason,
                "usage": data.get("usage", {}),
            },
        )

        return ChatResult(
            generations=[ChatGeneration(message=ai_msg)],
        )
