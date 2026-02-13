"""Chat API routes with SSE streaming and full debug capture."""

import asyncio
import json
import uuid as _uuid
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.conversation import Conversation, Message
from app.models.organization import Organization
from app.schemas.chat import (
    ConversationCreate,
    ConversationDetailResponse,
    ConversationResponse,
    MessageCreate,
    MessageResponse,
)
from app.agent.graph import run_agent
from app.agent.summarize import summarize_conversation

logger = structlog.get_logger(__name__)

# When conversation has at least this many messages (including the new one), we use
# summarization: summarize older messages and pass summary + last 2 exchanges only.
RECENT_MESSAGE_COUNT = 4  # last 2 user + 2 assistant before the new user message
MIN_MESSAGES_FOR_SUMMARY = 6  # need at least 6 messages to have something to summarize

router = APIRouter(tags=["chat"])


# ---------- helpers ----------

async def _get_org(db: AsyncSession, org_id: UUID) -> Organization:
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


async def _get_conversation(db: AsyncSession, conversation_id: UUID) -> Conversation:
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages))
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


def _message_to_langchain(m: Message):
    if m.role == "user":
        return HumanMessage(content=m.content or "")
    if m.role == "assistant":
        return AIMessage(content=m.content or "")
    return None


async def _build_conversation_history(conv: Conversation, new_user_content: str):
    """
    Build conversation_history for the agent. When the chat is large we summarize
    older messages and pass summary + last 2 exchanges. Otherwise pass full history.
    The new user message is NOT included in history; it is passed separately as user_message.
    """
    all_messages = list(conv.messages)
    # Exclude the new user message (last one we just added in send_message)
    existing = all_messages[:-1] if all_messages else []

    if len(existing) < MIN_MESSAGES_FOR_SUMMARY:
        # Small chat: pass full history (user + assistant only, no tool messages in stored history)
        history = []
        for m in existing:
            msg = _message_to_langchain(m)
            if msg is not None:
                history.append(msg)
        return history

    # Large chat: summarize older part, keep last 2 exchanges
    to_summarize = existing[:-RECENT_MESSAGE_COUNT]
    recent = existing[-RECENT_MESSAGE_COUNT:]
    if not to_summarize:
        history = []
        for m in recent:
            msg = _message_to_langchain(m)
            if msg is not None:
                history.append(msg)
        return history

    need_summary = (
        conv.conversation_summary is None
        or conv.conversation_summary_message_count is None
        or conv.conversation_summary_message_count < len(to_summarize)
    )
    if need_summary:
        summary_text = await asyncio.to_thread(summarize_conversation, to_summarize)
        conv.conversation_summary = summary_text
        conv.conversation_summary_message_count = len(to_summarize)

    summary_msg = SystemMessage(
        content=f"Previous conversation summary:\n{conv.conversation_summary}"
    )
    history = [summary_msg]
    for m in recent:
        msg = _message_to_langchain(m)
        if msg is not None:
            history.append(msg)
    return history


# ---------- Conversation CRUD ----------

@router.post(
    "/organizations/{org_id}/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    org_id: UUID,
    body: ConversationCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new conversation."""
    await _get_org(db, org_id)
    conv = Conversation(
        id=_uuid.uuid4(),
        organization_id=org_id,
        title=body.title,
    )
    db.add(conv)
    await db.flush()
    await db.refresh(conv)
    return ConversationResponse(
        id=conv.id,
        organization_id=conv.organization_id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=0,
    )


@router.get(
    "/organizations/{org_id}/conversations",
    response_model=list[ConversationResponse],
)
async def list_conversations(
    org_id: UUID,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List conversations for an organization."""
    await _get_org(db, org_id)
    result = await db.execute(
        select(
            Conversation,
            func.count(Message.id).label("message_count"),
        )
        .outerjoin(Message)
        .where(Conversation.organization_id == org_id)
        .group_by(Conversation.id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.all()
    return [
        ConversationResponse(
            id=conv.id,
            organization_id=conv.organization_id,
            title=conv.title,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            message_count=count,
        )
        for conv, count in rows
    ]


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
)
async def get_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get conversation with all messages."""
    conv = await _get_conversation(db, conversation_id)
    return ConversationDetailResponse(
        id=conv.id,
        organization_id=conv.organization_id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[
            MessageResponse(
                id=m.id,
                conversation_id=m.conversation_id,
                role=m.role,
                content=m.content,
                context=m.context,
                tool_name=m.tool_name,
                created_at=m.created_at,
            )
            for m in conv.messages
        ],
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation and all its messages."""
    conv = await _get_conversation(db, conversation_id)
    await db.delete(conv)


@router.get("/conversations/{conversation_id}/debug")
async def get_conversation_debug(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get full debug trace of a conversation including all tool calls and responses."""
    conv = await _get_conversation(db, conversation_id)

    # Build detailed trace from messages
    trace: list[dict] = []

    for msg in conv.messages:
        if msg.role == "user":
            trace.append({
                "type": "user_message",
                "timestamp": msg.created_at.isoformat(),
                "content": msg.content,
                "context": msg.context,
            })
        elif msg.role == "assistant":
            if msg.tool_name:
                trace.append({
                    "type": "tool_call",
                    "timestamp": msg.created_at.isoformat(),
                    "tool": msg.tool_name,
                    "tool_call_id": msg.tool_call_id,
                    "arguments": msg.context,
                })
            else:
                trace.append({
                    "type": "assistant_response",
                    "timestamp": msg.created_at.isoformat(),
                    "content": msg.content,
                })
        elif msg.role == "tool":
            trace.append({
                "type": "tool_response",
                "timestamp": msg.created_at.isoformat(),
                "tool": msg.tool_name,
                "tool_call_id": msg.tool_call_id,
                "content": msg.content,
            })

    return {
        "conversation_id": str(conv.id),
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
        "trace": trace,
        "summary": {
            "total_messages": len(conv.messages),
            "user_messages": len([m for m in conv.messages if m.role == "user"]),
            "assistant_messages": len([m for m in conv.messages if m.role == "assistant" and not m.tool_name]),
            "tool_calls": len([m for m in conv.messages if m.role == "assistant" and m.tool_name]),
            "tool_responses": len([m for m in conv.messages if m.role == "tool"]),
        },
    }


# ---------- Send message (SSE streaming) ----------

@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: UUID,
    body: MessageCreate,
    db: AsyncSession = Depends(get_db),
):
    """Send a message and stream the AI response via Server-Sent Events.

    SSE event types:
    - token: streamed text chunk {content}
    - tool_start: tool call initiated {tool, args, tool_number, ai_call}
    - tool_end: tool call completed {tool, result_preview, result_length, duration_ms}
    - stats: guardrail metrics {ai_calls, max_ai_calls, tool_calls, elapsed_seconds, estimated_tokens, max_tokens}
    - done: final response {content}
    - error: error message {error}
    """
    conv = await _get_conversation(db, conversation_id)
    org = await _get_org(db, conv.organization_id)

    # Persist user message
    user_msg = Message(
        id=_uuid.uuid4(),
        conversation_id=conv.id,
        role="user",
        content=body.content,
        context=body.context.model_dump() if body.context else None,
    )
    db.add(user_msg)
    await db.flush()

    # Build conversation history: full history if small, else summary + last 2 exchanges
    history = await _build_conversation_history(conv, body.content)

    # Context from user
    context = body.context.model_dump(exclude_none=True) if body.context else None

    # Auto-title on first message
    if len(conv.messages) <= 1:
        conv.title = body.content[:80] + ("..." if len(body.content) > 80 else "")

    # Commit (including any updated conversation_summary) before streaming
    await db.commit()

    async def event_stream():
        """Generate SSE events from the agent."""
        full_response = ""
        tool_calls_to_save: list[dict] = []
        tool_responses_to_save: list[dict] = []

        try:
            async for event_type, data in run_agent(
                organization=org,
                user_message=body.content,
                conversation_history=history,
                context=context,
                capture_full_trace=True,
            ):
                if event_type == "token":
                    full_response += data
                    yield f"event: token\ndata: {json.dumps({'content': data})}\n\n"

                elif event_type == "tool_start":
                    tool_name = data.get("tool", "unknown")
                    tool_args = data.get("args", {})
                    tool_number = data.get("tool_number", 0)
                    ai_call = data.get("ai_call", 0)

                    tool_call_id = _uuid.uuid4().hex[:16]
                    tool_calls_to_save.append({
                        "id": tool_call_id,
                        "name": tool_name,
                        "args": tool_args,
                        "tool_number": tool_number,
                    })
                    yield f"event: tool_start\ndata: {json.dumps({'tool': tool_name, 'args': tool_args, 'id': tool_call_id, 'tool_number': tool_number, 'ai_call': ai_call})}\n\n"

                elif event_type == "tool_end":
                    tool_name = data.get("tool", "unknown")
                    result_preview = data.get("result_preview", "")
                    result_length = data.get("result_length", 0)
                    duration_ms = data.get("duration_ms", 0)

                    if tool_calls_to_save:
                        last_call = tool_calls_to_save[-1]
                        tool_responses_to_save.append({
                            "tool_call_id": last_call["id"],
                            "tool_name": tool_name,
                            "content": result_preview,
                            "duration_ms": duration_ms,
                        })

                    yield f"event: tool_end\ndata: {json.dumps({'tool': tool_name, 'result_preview': result_preview, 'result_length': result_length, 'duration_ms': duration_ms})}\n\n"

                elif event_type == "stats":
                    yield f"event: stats\ndata: {json.dumps(data)}\n\n"

                elif event_type == "done":
                    # Prefer the graph's final_response (synthesis from last AIMessage)
                    # over accumulated tokens (which include intermediate thinking)
                    done_content = data or full_response or "No response generated."
                    full_response = done_content
                    yield f"event: done\ndata: {json.dumps({'content': done_content})}\n\n"

                elif event_type == "trace":
                    pass  # Trace data handled internally

                elif event_type == "error":
                    yield f"event: error\ndata: {json.dumps({'error': data})}\n\n"

            # Persist all messages in a new session
            from app.database import async_session_factory
            async with async_session_factory() as save_db:
                # Save tool calls as assistant messages
                for tool_call in tool_calls_to_save:
                    tool_msg = Message(
                        id=_uuid.uuid4(),
                        conversation_id=conv.id,
                        role="assistant",
                        content=f"Calling tool: {tool_call['name']}",
                        tool_name=tool_call["name"],
                        tool_call_id=tool_call["id"],
                        context=tool_call.get("args"),
                    )
                    save_db.add(tool_msg)

                # Save tool responses
                for tool_resp in tool_responses_to_save:
                    tool_msg = Message(
                        id=_uuid.uuid4(),
                        conversation_id=conv.id,
                        role="tool",
                        content=tool_resp["content"],
                        tool_name=tool_resp["tool_name"],
                        tool_call_id=tool_resp["tool_call_id"],
                    )
                    save_db.add(tool_msg)

                # Save final assistant response
                assistant_msg = Message(
                    id=_uuid.uuid4(),
                    conversation_id=conv.id,
                    role="assistant",
                    content=full_response or "No response generated.",
                )
                save_db.add(assistant_msg)
                await save_db.commit()

        except Exception as e:
            logger.error("stream_error", error=str(e))
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
