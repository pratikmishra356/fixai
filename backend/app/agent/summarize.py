"""Conversation summarization for long chat memory.

When conversation history exceeds a threshold, we summarize older messages
and pass summary + last N exchanges to the agent to keep context manageable.
"""

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.llm import ClaudeBedrockChat

logger = structlog.get_logger(__name__)

SUMMARY_SYSTEM = """You are summarizing a prior SRE/on-call debugging chat session.
Produce a single short paragraph (2-4 sentences) that captures:
- What the user asked and any services/endpoints mentioned
- What was investigated (which tools: code, metrics, logs) and key findings
- Any conclusions or open questions
Keep it factual and concise. No markdown. Write in past tense."""


def _messages_to_summarizable_text(messages: list) -> str:
    """Turn a list of DB messages (with .role and .content) into plain text for summarization."""
    parts = []
    for m in messages:
        role = getattr(m, "role", "unknown")
        content = (getattr(m, "content", "") or "").strip()
        if not content or role == "tool":
            continue
        if role == "user":
            parts.append(f"User: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")
    return "\n\n".join(parts)


def summarize_conversation(messages: list) -> str:
    """
    Summarize a list of conversation messages (objects with .role and .content).
    Returns a short paragraph. Uses the same Claude LLM without tools.
    """
    if not messages:
        return ""
    text = _messages_to_summarizable_text(messages)
    if not text.strip():
        return ""
    llm = ClaudeBedrockChat()
    prompt = (
        "Summarize the following conversation between the user and the SRE assistant.\n\n"
        f"---\n{text}\n---"
    )
    msgs = [
        SystemMessage(content=SUMMARY_SYSTEM),
        HumanMessage(content=prompt),
    ]
    try:
        response = llm.invoke(msgs)
        summary = (response.content or "").strip()
        logger.info("conversation_summarized", message_count=len(messages), summary_len=len(summary))
        return summary
    except Exception as e:
        logger.error("summarization_failed", error=str(e))
        # Fallback: truncate to first 500 chars of concatenated content
        return text[:500] + "..." if len(text) > 500 else text
