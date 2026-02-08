"""LangGraph ReAct agent graph with guardrails.

Guardrails:
- MAX_AI_CALLS: Hard cap on LLM invocations per conversation turn.
- MAX_INPUT_TOKENS: Estimated token budget for AI input context.
  When approaching the limit, the agent is told to wrap up.

Each agent→tool round counts as 2 graph steps.
"""

import time
from uuid import UUID

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph

from app.agent.llm import ClaudeBedrockChat
from app.agent.state import AgentState
from app.agent.tools import ALL_TOOLS, set_clients
from app.clients.code_parser import CodeParserClient
from app.clients.logs_explorer import LogsExplorerClient
from app.clients.metrics_explorer import MetricsExplorerClient
from app.config import settings
from app.models.organization import Organization

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Guardrail constants (from config, can be overridden via env vars)
# ---------------------------------------------------------------------------
MAX_AI_CALLS = settings.agent_max_ai_calls
MAX_INPUT_TOKENS = settings.agent_max_input_tokens
RECURSION_LIMIT = settings.agent_recursion_limit
TOOL_RESPONSE_MAX_CHARS = settings.agent_tool_response_max_chars
TOKEN_ESTIMATION_DIVISOR = settings.agent_token_estimation_divisor


def _estimate_tokens(messages: list[BaseMessage]) -> int:
    """Rough token estimate: total characters / divisor (default 4)."""
    total_chars = 0
    for m in messages:
        if isinstance(m.content, str):
            total_chars += len(m.content)
        elif isinstance(m.content, list):
            for block in m.content:
                if isinstance(block, dict):
                    total_chars += len(str(block.get("text", "")))
                else:
                    total_chars += len(str(block))
    return total_chars // TOKEN_ESTIMATION_DIVISOR


SYSTEM_PROMPT = """\
You are FixAI — an elite on-call debugging AI that rivals the best senior SREs. \
You diagnose production issues by systematically analyzing metrics, logs, and code, \
and you NEVER fabricate findings. Every claim you make must be backed by data from your tools.

## Your 12 Tools

**Metrics Explorer (dashboard-centric):**
1. `metrics_get_overview` — org info + important (used) dashboards. CALL THIS FIRST.
2. `metrics_search_dashboards` — search dashboards by keyword/wildcard.
3. `metrics_explore_dashboard` — list metrics & template variables in a dashboard.
4. `metrics_get_variable_values` — discover available filter values for a template variable.
5. `metrics_query` — execute a metric query (uses provider_dashboard_id, NOT db_id).

**Logs Explorer:**
6. `logs_get_overview` — org info + important (used) indexes. CALL THIS FIRST.
7. `logs_search_sources` — find services/sources by keyword.
8. `logs_search` — search logs by index, source, and query terms.

**Code Parser:**
9. `code_search_entry_points` — search HTTP endpoints, event handlers, schedulers by regex.
10. `code_get_flows` — get step-by-step execution flow for entry points.
11. `code_search_files` — search files by regex on path.
12. `code_get_file` — read full source code of a file.

## CRITICAL: Dashboard ID Types

Metrics Explorer uses TWO different IDs:
- **db_id** (UUID like "a1b2c3d4-..."): Used for `metrics_explore_dashboard` and `metrics_get_variable_values`.
- **provider_dashboard_id** (like "4k2-qvg-h38"): Used for `metrics_query` (the `dashboard_provider_id` param).
You get BOTH from `metrics_get_overview` and `metrics_search_dashboards`. Do NOT confuse them.

## Investigation Methodology

Follow this systematic approach. Adapt based on the question, but always cover all three data sources.

### Phase 1: Discovery (2-3 parallel-ready calls)
- `metrics_get_overview` → learn which dashboards matter (used_dashboards)
- `logs_get_overview` → learn which indexes matter (used_indexes)
- Identify the service name patterns to search for

### Phase 2: Metrics Deep Dive (2-4 calls)
- Search dashboards related to the service: `metrics_search_dashboards`
- Explore the most relevant dashboard: `metrics_explore_dashboard`
- Query key metrics (error rates, latency, throughput): `metrics_query`
- If needed, check variable values to find the right filter: `metrics_get_variable_values`

### Phase 3: Log Analysis (2-3 calls)
- Find the service in logs: `logs_search_sources`
- Search for errors/exceptions: `logs_search` with query_terms like ['ERROR', 'exception', 'timeout']
- If first search is too broad, narrow with more specific terms from the errors found

### Phase 4: Code Understanding (1-3 calls)
- Find entry points: `code_search_entry_points` with the relevant service/feature name
- Get execution flows: `code_get_flows` for the suspicious endpoints
- Read specific files only if the flow reveals a likely code-level issue

### Phase 5: Synthesize (no tools)
Write your final report.

## STRICT Rules for Avoiding False Positives

1. **Only report what the data shows.** If a metric is at 0 errors, say "0 errors observed" — don't speculate about hidden issues.
2. **Distinguish clearly between:**
   - "No data available" (tool returned error or empty) → means observability gap, NOT a problem
   - "Data shows normal" → means the service appears healthy by that measure
   - "Data shows anomaly" → only if there's a clear deviation (e.g., error spike, latency increase)
3. **Never say "might be" without evidence.** Either you found evidence of a problem, or you didn't.
4. **Context matters.** A single error in 10,000 requests is noise, not a crisis. Quantify.
5. **If a service is not found** in logs/metrics, it may use a different name. Try variations before concluding.
6. **If SERVICE_NOT_CONFIGURED** for a service, clearly note it as "not configured" — don't treat it as a finding.

## Report Format

Structure your final answer as:

### Summary
One-paragraph overall assessment. Be definitive: healthy, degraded, or impaired.

### Metrics
What the dashboards and metrics show. Include specific numbers (error rates, latency p50/p99, throughput).
If no relevant dashboards found, say so explicitly.

### Logs
What the log search revealed. Quote specific error messages. Count occurrences.
If no errors found, state "No errors in the last N minutes."

### Code Architecture
What the entry points and flows reveal about how the service works.
Only include if relevant to the issue.

### Root Cause Analysis
Based on ALL evidence above. Be specific. If inconclusive, say so and explain what's missing.

### Recommendations
Concrete, prioritized actions. Distinguish between immediate (fix now) and strategic (improve later).
"""


SYNTHESIS_REQUEST = (
    "INVESTIGATION COMPLETE — CALL LIMIT REACHED.\n\n"
    "You MUST now write your final comprehensive report based on ALL the data collected above. "
    "Do NOT say 'let me check' or 'let me query'. Do NOT request any tools. "
    "Synthesize everything you have found into a structured report.\n\n"
    "## Required Report Format\n\n"
    "### Summary\n"
    "One-paragraph definitive assessment: healthy, degraded, or impaired.\n\n"
    "### Metrics\n"
    "Dashboard and metric findings with specific numbers. State if none found.\n\n"
    "### Logs\n"
    "Log search findings. Quote errors, count occurrences. State if clean.\n\n"
    "### Code Architecture\n"
    "Entry points and flows (only if relevant).\n\n"
    "### Root Cause Analysis\n"
    "Based on ALL evidence. State what's missing if inconclusive.\n\n"
    "### Recommendations\n"
    "Concrete, prioritized actions.\n\n"
    "IMPORTANT RULES:\n"
    "- ONLY report what data shows — never fabricate.\n"
    "- Tool errors (401, connection failed) = 'unavailable', not a finding.\n"
    "- 'No data' = observability gap, NOT a problem.\n"
    "- Quantify everything: counts, rates, latencies.\n"
    "- Write the report NOW. This is your FINAL response."
)


def _build_tool_map() -> dict:
    return {t.name: t for t in ALL_TOOLS}


def _build_synthesis_messages(messages: list) -> list:
    """Keep the original system prompt and conversation, append a synthesis request as HumanMessage."""
    return list(messages) + [HumanMessage(content=SYNTHESIS_REQUEST)]


# ---------- Node functions ----------

def agent_node(state: AgentState) -> dict:
    """Invoke Claude with current messages and tools.

    Enforces:
    - MAX_AI_CALLS: on the LAST call, forces synthesis (no tools).
    - MAX_INPUT_TOKENS: forces synthesis when context is too large.
    """
    call_count = state.get("ai_call_count", 0) + 1
    messages = state["messages"]
    token_est = _estimate_tokens(messages)

    logger.info(
        "agent_node",
        ai_call=call_count,
        max_calls=MAX_AI_CALLS,
        estimated_tokens=token_est,
        max_tokens=MAX_INPUT_TOKENS,
    )

    # --- Guardrail: Hard limit exceeded (should not happen) ---
    if call_count > MAX_AI_CALLS:
        logger.warning("guardrail_ai_calls_exceeded", count=call_count)
        return {
            "messages": [AIMessage(content=(
                "**Investigation limit reached** — see findings above. "
                "Start a follow-up conversation for deeper investigation."
            ))],
            "ai_call_count": call_count,
            "total_input_tokens_est": token_est,
        }

    # Determine if we must force synthesis on this call
    force_synthesis = (
        call_count == MAX_AI_CALLS or
        token_est > MAX_INPUT_TOKENS
    )

    if force_synthesis:
        logger.info("forcing_synthesis", call_count=call_count, token_est=token_est)
        # Replace system prompt with synthesis-only prompt, no tools bound
        synthesis_msgs = _build_synthesis_messages(messages)
        llm = ClaudeBedrockChat()
        response = llm.invoke(synthesis_msgs)

        logger.info(
            "synthesis_response",
            content_len=len(response.content or ""),
            content_preview=(response.content or "")[:120],
            has_tool_calls=bool(getattr(response, 'tool_calls', None)),
        )

        # Safety: strip any tool calls (shouldn't happen without tools bound)
        if hasattr(response, 'tool_calls') and response.tool_calls:
            logger.warning("stripping_tool_calls_on_synthesis")
            response = AIMessage(
                content=response.content or "Investigation complete. See findings above.",
                tool_calls=[],
            )

        return {
            "messages": [response],
            "ai_call_count": call_count,
            "total_input_tokens_est": token_est,
        }

    # --- Normal AI call (tools bound) ---
    llm = ClaudeBedrockChat()
    llm_with_tools = llm.bind_tools(ALL_TOOLS)
    response = llm_with_tools.invoke(messages)

    return {
        "messages": [response],
        "ai_call_count": call_count,
        "total_input_tokens_est": token_est,
    }


async def tool_node(state: AgentState) -> dict:
    """Execute tool calls from the last AI message."""
    tool_map = _build_tool_map()
    last_message: AIMessage = state["messages"][-1]
    tool_messages = []

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_id = tool_call["id"]

        logger.info("tool_call", tool=tool_name, args_keys=list(tool_args.keys()))

        tool_fn = tool_map.get(tool_name)
        if not tool_fn:
            tool_messages.append(
                ToolMessage(content=f"Unknown tool: {tool_name}", tool_call_id=tool_id)
            )
            continue

        try:
            result = await tool_fn.ainvoke(tool_args)
            # Hard cap on tool response size (configurable)
            if isinstance(result, str) and len(result) > TOOL_RESPONSE_MAX_CHARS:
                result = result[:TOOL_RESPONSE_MAX_CHARS] + "\n\n... [truncated – use more specific filters]"
            tool_messages.append(ToolMessage(content=str(result), tool_call_id=tool_id))
        except Exception as e:
            logger.error("tool_error", tool=tool_name, error=str(e))
            tool_messages.append(ToolMessage(content=f"Tool error: {e}", tool_call_id=tool_id))

    return {"messages": tool_messages}


def should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    call_count = state.get("ai_call_count", 0)
    has_tool_calls = isinstance(last, AIMessage) and bool(last.tool_calls)
    content_preview = (last.content or "")[:100] if isinstance(last, AIMessage) else ""

    logger.info(
        "should_continue",
        call_count=call_count,
        has_tool_calls=has_tool_calls,
        content_preview=content_preview,
        msg_type=type(last).__name__,
    )

    # If AI returned tool calls and we haven't exceeded limits, continue
    if has_tool_calls:
        if call_count >= MAX_AI_CALLS:
            # Limit reached — don't execute tools, end the graph
            logger.warning("should_continue_blocked_at_limit", call_count=call_count)
            return END
        return "tools"

    return END


# ---------- Build the graph ----------

def build_agent_graph():
    """Construct and compile the LangGraph agent."""
    graph = StateGraph(AgentState)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile()


# ---------- Public entry point ----------

async def run_agent(
    organization: Organization,
    user_message: str,
    conversation_history: list[BaseMessage] | None = None,
    context: dict | None = None,
    capture_full_trace: bool = False,
):
    """Run the agent for one user turn.

    Yields (event_type, data) tuples for streaming:
    - ("token", str) — streamed text chunk
    - ("tool_start", dict) — tool call initiated
    - ("tool_end", dict) — tool call completed
    - ("stats", dict) — current guardrail metrics
    - ("done", str) — final response
    - ("error", str) — error message
    - ("trace", dict) — full debug trace (if capture_full_trace)
    """
    # Set up service clients based on org configuration
    cp_client = None
    me_client = None
    le_client = None

    if organization.code_parser_base_url and organization.code_parser_org_id and organization.code_parser_repo_id:
        cp_client = CodeParserClient(
            organization.code_parser_base_url or settings.code_parser_base_url,
            organization.code_parser_org_id,
            organization.code_parser_repo_id,
        )
    if organization.metrics_explorer_base_url and organization.metrics_explorer_org_id:
        me_client = MetricsExplorerClient(
            organization.metrics_explorer_base_url or settings.metrics_explorer_base_url,
            organization.metrics_explorer_org_id,
        )
    if organization.logs_explorer_base_url and organization.logs_explorer_org_id:
        le_client = LogsExplorerClient(
            organization.logs_explorer_base_url or settings.logs_explorer_base_url,
            organization.logs_explorer_org_id,
        )

    set_clients(code_parser=cp_client, metrics_explorer=me_client, logs_explorer=le_client)

    # Build messages
    messages: list[BaseMessage] = [SystemMessage(content=SYSTEM_PROMPT)]

    if context:
        parts = []
        if context.get("service"):
            parts.append(f"Service: {context['service']}")
        if context.get("environment"):
            parts.append(f"Environment: {context['environment']}")
        if context.get("file_path"):
            parts.append(f"File path: {context['file_path']}")
        if parts:
            context_hint = "User provided context:\n" + "\n".join(parts)
            messages.append(SystemMessage(content=context_hint))

    if conversation_history:
        messages.extend(conversation_history)

    messages.append(HumanMessage(content=user_message))

    # Run the graph
    agent = build_agent_graph()

    # Trace capture
    full_trace: list[dict] = []
    tool_calls_captured: list[dict] = []
    tool_responses_captured: list[dict] = []
    ai_call_count = 0
    tool_call_count = 0
    start_time = time.time()

    try:
        final_response = ""
        last_ai_content = ""          # Content from the LAST on_chat_model_end
        chain_end_response = ""        # Content from on_chain_end (fallback)
        current_tool_call: dict | None = None

        async for event in agent.astream_events(
            {"messages": messages, "ai_call_count": 0, "total_input_tokens_est": 0},
            {"recursion_limit": RECURSION_LIMIT},
            version="v2",
        ):
            kind = event.get("event", "")
            event_data = event.get("data", {})

            if kind == "on_chat_model_start":
                ai_call_count += 1
                elapsed = round(time.time() - start_time, 1)

                yield ("stats", {
                    "ai_calls": ai_call_count,
                    "max_ai_calls": MAX_AI_CALLS,
                    "tool_calls": tool_call_count,
                    "elapsed_seconds": elapsed,
                    "estimated_tokens": _estimate_tokens(messages),
                    "max_tokens": MAX_INPUT_TOKENS,
                })

                if capture_full_trace:
                    full_trace.append({
                        "type": "ai_invoke",
                        "ai_call_number": ai_call_count,
                        "elapsed_seconds": elapsed,
                    })

            elif kind == "on_chat_model_stream":
                chunk = event_data.get("chunk")
                if chunk and hasattr(chunk, "content") and isinstance(chunk.content, str):
                    yield ("token", chunk.content)

            elif kind == "on_chat_model_end":
                output = event_data.get("output", {})

                # Extract AIMessage from various output formats
                ai_msg = None
                if isinstance(output, AIMessage):
                    ai_msg = output
                elif hasattr(output, "generations") and output.generations:
                    gens = output.generations
                    if isinstance(gens[0], list) and gens[0]:
                        ai_msg = getattr(gens[0][0], "message", None)
                    elif hasattr(gens[0], "message"):
                        ai_msg = gens[0].message

                if ai_msg and isinstance(ai_msg, AIMessage) and ai_msg.content:
                    # Always overwrite — the LAST AI response wins (synthesis)
                    last_ai_content = ai_msg.content

                    if capture_full_trace:
                        usage = ai_msg.additional_kwargs.get("usage", {})
                        full_trace.append({
                            "type": "ai_response",
                            "ai_call_number": ai_call_count,
                            "content_preview": ai_msg.content[:200],
                            "tool_calls": [
                                {"id": tc.get("id"), "name": tc.get("name"), "args": tc.get("args", {})}
                                for tc in (ai_msg.tool_calls or [])
                            ],
                            "usage": usage,
                        })

            elif kind == "on_tool_start":
                tool_call_count += 1
                tool_name = event.get("name", "unknown")
                tool_input = event_data.get("input", {})

                current_tool_call = {
                    "name": tool_name,
                    "input": tool_input,
                    "start_time": time.time(),
                    "tool_number": tool_call_count,
                }
                tool_calls_captured.append(current_tool_call)

                yield ("tool_start", {
                    "tool": tool_name,
                    "args": tool_input,
                    "tool_number": tool_call_count,
                    "ai_call": ai_call_count,
                })

                if capture_full_trace:
                    full_trace.append({
                        "type": "tool_call",
                        "tool": tool_name,
                        "input": tool_input,
                        "tool_number": tool_call_count,
                    })

            elif kind == "on_tool_end":
                tool_name = event.get("name", "unknown")
                output = event_data.get("output", "")
                output_str = str(output)
                duration_ms = 0

                if current_tool_call and current_tool_call["name"] == tool_name:
                    duration_ms = int((time.time() - current_tool_call["start_time"]) * 1000)
                    current_tool_call["output"] = output_str
                    current_tool_call["duration_ms"] = duration_ms
                    tool_responses_captured.append(current_tool_call)
                    current_tool_call = None

                yield ("tool_end", {
                    "tool": tool_name,
                    "result_preview": output_str[:300],
                    "result_length": len(output_str),
                    "duration_ms": duration_ms,
                })

                if capture_full_trace:
                    full_trace.append({
                        "type": "tool_response",
                        "tool": tool_name,
                        "output_preview": output_str[:300],
                        "output_length": len(output_str),
                        "duration_ms": duration_ms,
                    })

            elif kind == "on_chain_end":
                output = event_data.get("output", {})
                if isinstance(output, dict) and "messages" in output:
                    msgs = output["messages"]
                    if msgs:
                        last = msgs[-1] if isinstance(msgs, list) else msgs
                        if isinstance(last, AIMessage) and last.content:
                            chain_end_response = last.content

        # Determine final_response: last AI call content > chain_end > fallback
        final_response = last_ai_content or chain_end_response
        logger.info(
            "final_response_selected",
            source="on_chat_model_end" if last_ai_content else ("on_chain_end" if chain_end_response else "none"),
            content_len=len(final_response),
        )

        elapsed_total = round(time.time() - start_time, 1)

        # Final stats
        yield ("stats", {
            "ai_calls": ai_call_count,
            "max_ai_calls": MAX_AI_CALLS,
            "tool_calls": tool_call_count,
            "elapsed_seconds": elapsed_total,
            "estimated_tokens": _estimate_tokens(messages),
            "max_tokens": MAX_INPUT_TOKENS,
            "final": True,
        })

        if final_response:
            yield ("done", final_response)
        else:
            yield ("done", "I was unable to generate a response. Please try again.")

        if capture_full_trace:
            yield ("trace", {
                "full_trace": full_trace,
                "tool_calls": tool_calls_captured,
                "tool_responses": tool_responses_captured,
                "final_response": final_response,
                "stats": {
                    "ai_calls": ai_call_count,
                    "tool_calls": tool_call_count,
                    "elapsed_seconds": elapsed_total,
                },
            })

    except Exception as e:
        logger.error("agent_error", error=str(e))
        yield ("error", f"Agent error: {str(e)}")
    finally:
        for client in [cp_client, me_client, le_client]:
            if client:
                await client.close()
