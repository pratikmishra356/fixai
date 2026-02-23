"""LangGraph ReAct agent graph with guardrails.

Guardrails:
- MAX_AI_CALLS: Hard cap on LLM invocations per conversation turn.
- MAX_INPUT_TOKENS: Estimated token budget for AI input context.
  When approaching the limit, the agent is told to wrap up.

Each agent→tool round counts as 2 graph steps.
"""

import asyncio
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
    """Rough token estimate: total characters / divisor.
    Counts message content, tool_calls (id/name/args), and tool results.
    Uses ~4 chars/token for English; configurable via agent_token_estimation_divisor.
    Handles message objects, dicts, and nested lists from stream events.
    """
    total_chars = 0
    if not messages or not isinstance(messages, list):
        return 0

    def _process_item(item):
        nonlocal total_chars
        if isinstance(item, list):
            for x in item:
                _process_item(x)
            return
        content = None
        tool_calls = None
        if hasattr(item, "content"):
            content = item.content
            tool_calls = getattr(item, "tool_calls", None)
        elif isinstance(item, dict):
            content = item.get("content", item.get("data", {}).get("content") if isinstance(item.get("data"), dict) else None)
            tool_calls = item.get("tool_calls")
        else:
            return
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total_chars += len(str(block.get("text", block.get("content", ""))))
                else:
                    total_chars += len(str(block))
        if tool_calls:
            for tc in tool_calls:
                args = tc.get("args", tc) if isinstance(tc, dict) else getattr(tc, "args", "")
                name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                total_chars += len(str(args)) + len(str(name))

    for m in messages:
        _process_item(m)
    return max(0, total_chars // TOKEN_ESTIMATION_DIVISOR)


SYSTEM_PROMPT = """\
You are FixAI, an SRE on-call assistant. You have access to three data sources — code, \
metrics, and logs — but you do not have to use all three for every question. Use only \
the tools that are needed to answer what the user asked. Every claim must be backed by \
tool data. Never fabricate.

**Adapt to the question**: Match your response to the user's intent. For a simple \
question (e.g. "what's the error rate for X?") give a short, direct answer. For a broad \
investigation (e.g. "is service Y healthy?", "debug this endpoint") give a structured \
report. Do not force a fixed report format when the user asked something narrow.

**Use tool outputs to drive next steps**: After each tool call, read the result before \
deciding what to do next. Use metric names and filter keys from `metrics_explore_dashboard` \
to choose which `metrics_query` to run. Use the log source name from `logs_search_sources` \
in `logs_search`. Use entry point paths or component names from code to refine log search \
terms or dashboard filters. Let the data from one call inform the next.

## Tools

You have 14 tools across three services. Read each tool's description carefully — \
it explains the inputs, outputs, and how results connect to other tools.

**Code Parser (6):** `code_search_repositories`, `code_get_repo_info`, \
`code_search_entry_points`, `code_get_flows`, `code_search_files`, `code_get_file`. \
The org may have multiple repos. Use `code_search_repositories` to find the right one \
and pass its `repo_id` to the other code tools.

**Metrics Explorer (5):** `metrics_get_overview`, `metrics_search_dashboards`, \
`metrics_explore_dashboard`, `metrics_get_variable_values`, `metrics_query`. \
Dashboards have two ID types — read the tool descriptions to know which to use where. \
**IMPORTANT**: Use ONLY dashboards from `metrics_get_overview`'s `used_dashboards`. \
Do not search for other dashboards unless the used ones don't have relevant metrics.

**Logs Explorer (3):** `logs_get_overview`, `logs_search_sources`, `logs_search`.

## Investigation Approach

**1. Discover** (first call — parallel):
- Find the service's repo, dashboards, log sources, and indexes.

**2. Understand context** (lightweight):
- Get basic repo info and key entry points for the matched repo.
- Use service name and entry point paths to inform what to search for in metrics and logs.

**3. Gather operational data** (metrics AND logs — they answer different questions):
- **Metrics**: Start with `used_dashboards` — explore one, check its metrics and query. \
  If satisfied, use it; if not, try another used dashboard or search for more. \
  For each used dashboard: (1) Use its `db_id` with `metrics_explore_dashboard` to get \
  provider, template_variables (name, tag_key) and metrics (metric_name, queries). \
  (2) Call `metrics_get_variable_values` with template_variables[].name when you need \
  filter values.   (3) Call `metrics_query` with metric_name and filters — use \
  `dashboard_provider_id` (not `db_id`). Use tag keys from template_variables and \
  queries; different metrics may use different tag conventions. \
  Always follow exploration with queries to get actual time-series data. If metric values \
  look suspicious (e.g., very large numbers that don't match expected traffic), check the \
  `recent_datapoints` trend — if values steadily increase, it's likely a cumulative counter \
  and you should report the delta (latest - earliest) or rate, not the raw values.
- **Logs**: Start with `used_indexes` from `logs_get_overview` — use one, search and \
  check. If satisfied, use it; if not, try another used index. Call `logs_search_sources` \
  with `index_name` from used_indexes to scope the search to that index, then `logs_search` \
  with that index and source.
- **Time ranges**: Both `metrics_query` and `logs_search` support relative time ranges \
  (e.g. '1h', '24h') AND absolute calendar date ranges via `start_time`/`end_time` \
  ISO 8601 parameters (e.g. '2026-02-10T00:00:00Z'). When the user asks about a \
  specific date or date range, use absolute times instead of relative.
- For error/exception investigations, check both metrics and logs — they capture \
  different failure modes (infrastructure 5xx vs application exceptions).

**4. Deep dive** (after operational data):
- Once you have metrics and logs data, use code to understand why issues occurred. \
  Get flows, read relevant source files, trace execution paths. Code explains \
  the "why" behind what the operational data shows.

**5. Synthesize**: Write your answer when you have sufficient evidence.

**Cross-tool reasoning**: Use each tool's output to decide the next. Metric names and \
template_variables from explore_dashboard → which metrics_query to run. Log source \
names from search_sources → index and source in logs_search. Entry points and paths \
from code → search terms for logs and metrics. Do not call tools blindly; read the \
previous results and use them.

## Principles

- Operational data (metrics + logs) answers "what is happening." Code answers "why."
- Report only what data shows. No data = observability gap, not a problem.
- Quantify: counts, rates, percentiles. Avoid vague language.
- Stop when you have enough evidence. Don't pad calls.
- **Metric interpretation** — CRITICAL: Many metrics are cumulative counters, not per-interval \
  counts. A metric named `.count` (e.g., `requests.count`) typically represents the total \
  cumulative count since the service started, NOT requests per 5-minute interval. To detect \
  this: (1) Check `recent_datapoints` — if values steadily increase (e.g., 277K → 278K → 279K), \
  it's a cumulative counter, (2) Also check if `min` and `max` are very different but both \
  large — this indicates a cumulative counter, (3) Calculate the actual count: `max - min` \
  (or `latest - min`), (4) Report the delta and rate, NOT the raw average. Example: If \
  avg=295K, min=277K, max=312K, and recent_datapoints show steady increase, report \
  "~35K requests total over 24h (~0.4 req/sec)" NOT "295K requests per 5-minute interval". \
  The average of a cumulative counter is meaningless — always report the delta. If unsure, \
  query with a shorter time range to see if the pattern repeats.

## Report Format (for broad investigations)

When the query warrants a full investigation, structure your answer as: Summary, Metrics, \
Logs, Code (if relevant), Root Cause Analysis, Recommendations. For narrow questions, \
a short direct answer is enough. Omit sections that have no data.
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
    - MAX_AI_CALLS: hard limit of 15 calls.
    - MAX_INPUT_TOKENS: forces synthesis when context is too large.
    - On the LAST allowed call, forces synthesis (no tools).
    """
    call_count = state.get("ai_call_count", 0) + 1
    messages = state["messages"]
    token_est = _estimate_tokens(messages)

    logger.info(
        "agent_node",
        ai_call=call_count,
        max_calls=MAX_AI_CALLS,
        estimated_tokens=token_est,
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

    # --- Build LLM with org-level overrides ---
    llm_kwargs: dict = {}
    if state.get("ai_model_id"):
        llm_kwargs["model_id"] = state["ai_model_id"]
    if state.get("ai_bedrock_url"):
        llm_kwargs["bedrock_url"] = state["ai_bedrock_url"]
    if state.get("ai_max_tokens"):
        llm_kwargs["max_tokens"] = state["ai_max_tokens"]
    if state.get("ai_api_key"):
        llm_kwargs["api_key_override"] = state["ai_api_key"]

    if force_synthesis:
        logger.info("forcing_synthesis", call_count=call_count, max_calls=MAX_AI_CALLS, token_est=token_est)
        synthesis_msgs = _build_synthesis_messages(messages)
        llm = ClaudeBedrockChat(**llm_kwargs)
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
    llm = ClaudeBedrockChat(**llm_kwargs)
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

    logger.info(
        "should_continue",
        call_count=call_count,
        max_calls=MAX_AI_CALLS,
        has_tool_calls=has_tool_calls,
    )

    # If AI returned tool calls and we haven't exceeded limits, continue
    if has_tool_calls:
        if call_count >= MAX_AI_CALLS:
            logger.warning("should_continue_blocked_at_limit", call_count=call_count, max_calls=MAX_AI_CALLS)
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
    cancel_event: asyncio.Event | None = None,
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

    if organization.code_parser_base_url and organization.code_parser_org_id:
        cp_client = CodeParserClient(
            organization.code_parser_base_url or settings.code_parser_base_url,
            organization.code_parser_org_id,
            organization.code_parser_repo_id,  # Optional — may be None
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
    last_known_messages: list[BaseMessage] = messages  # Updated from stream for token est

    try:
        final_response = ""
        last_ai_content = ""          # Content from the LAST on_chat_model_end
        chain_end_response = ""        # Content from on_chain_end (fallback)
        current_tool_call: dict | None = None

        # Populate org-level AI config into state (fall back to global settings)
        initial_state = {
            "messages": messages,
            "ai_call_count": 0,
            "total_input_tokens_est": 0,
            "ai_api_key": organization.claude_api_key or "",
            "ai_bedrock_url": organization.claude_bedrock_url or "",
            "ai_model_id": organization.claude_model_id or "",
            "ai_max_tokens": organization.claude_max_tokens or 0,
        }

        stopped_by_user = False

        async for event in agent.astream_events(
            initial_state,
            {"recursion_limit": RECURSION_LIMIT},
            version="v2",
        ):
            if cancel_event and cancel_event.is_set():
                stopped_by_user = True
                logger.info("agent_stopped_by_user", ai_calls=ai_call_count, tool_calls=tool_call_count)
                break

            kind = event.get("event", "")
            event_data = event.get("data", {})

            if kind == "on_chat_model_start":
                ai_call_count += 1
                elapsed = round(time.time() - start_time, 1)
                # Use actual input messages (includes tool responses) for token estimation
                input_data = event_data.get("input", {})
                if isinstance(input_data, list):
                    msgs_for_tokens = input_data
                elif isinstance(input_data, dict) and "messages" in input_data:
                    msgs_for_tokens = input_data["messages"]
                else:
                    msgs_for_tokens = last_known_messages
                if isinstance(msgs_for_tokens, list) and msgs_for_tokens:
                    last_known_messages = msgs_for_tokens

                yield ("stats", {
                    "ai_calls": ai_call_count,
                    "max_ai_calls": MAX_AI_CALLS,
                    "tool_calls": tool_call_count,
                    "elapsed_seconds": elapsed,
                    "estimated_tokens": _estimate_tokens(last_known_messages),
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
                    "result_preview": output_str[:2000],
                    "result_length": len(output_str),
                    "duration_ms": duration_ms,
                })

                if capture_full_trace:
                    full_trace.append({
                        "type": "tool_response",
                        "tool": tool_name,
                        "output_preview": output_str[:2000],
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

        if stopped_by_user:
            suffix = "\n\n---\n*Investigation stopped by user. Above is a partial summary based on data collected so far.*"
            if final_response.strip():
                final_response = final_response.strip() + suffix
            else:
                final_response = "Investigation stopped by user before any results were collected."

        logger.info(
            "final_response_selected",
            source="stopped_by_user" if stopped_by_user else (
                "on_chat_model_end" if last_ai_content else ("on_chain_end" if chain_end_response else "none")
            ),
            content_len=len(final_response),
        )

        elapsed_total = round(time.time() - start_time, 1)

        # Final stats (use last known messages from stream for token estimate)
        yield ("stats", {
            "ai_calls": ai_call_count,
            "max_ai_calls": MAX_AI_CALLS,
            "tool_calls": tool_call_count,
            "elapsed_seconds": elapsed_total,
            "estimated_tokens": _estimate_tokens(last_known_messages),
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
