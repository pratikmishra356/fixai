"""LangGraph tool definitions wrapping the 3 service clients.

Design principles:
- Each tool follows the actual API workflow from the service's API_FOR_AI.md.
- Discovery-first: overview tools reveal used_dashboards / used_indexes.
- Compact responses: summaries for lists, full detail only on drill-down.
- Structured errors: SERVICE_NOT_CONFIGURED / API_ERROR / UNKNOWN_ERROR.
- No false data: tools return exactly what the API returns, nothing fabricated.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from langchain_core.tools import tool

from app.clients.code_parser import CodeParserClient
from app.clients.metrics_explorer import MetricsExplorerClient
from app.clients.logs_explorer import LogsExplorerClient
from app.config import settings


# ---------------------------------------------------------------------------
# Client injection (set per-request from the agent graph)
# ---------------------------------------------------------------------------
_clients: dict = {}


def set_clients(
    code_parser: CodeParserClient | None = None,
    metrics_explorer: MetricsExplorerClient | None = None,
    logs_explorer: LogsExplorerClient | None = None,
) -> None:
    _clients["code_parser"] = code_parser
    _clients["metrics_explorer"] = metrics_explorer
    _clients["logs_explorer"] = logs_explorer


class ServiceNotConfiguredError(Exception):
    """Raised when a service client is not configured."""
    pass


def _cp() -> CodeParserClient:
    c = _clients.get("code_parser")
    if not c:
        raise ServiceNotConfiguredError("Code Parser is not configured for this organization")
    return c


def _me() -> MetricsExplorerClient:
    c = _clients.get("metrics_explorer")
    if not c:
        raise ServiceNotConfiguredError("Metrics Explorer is not configured for this organization")
    return c


def _le() -> LogsExplorerClient:
    c = _clients.get("logs_explorer")
    if not c:
        raise ServiceNotConfiguredError("Logs Explorer is not configured for this organization")
    return c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error_response(error_type: str, message: str, service: str, **extra: Any) -> str:
    return json.dumps({"error": error_type, "message": message, "service": service, **extra}, default=str)


def _safe_json(data: Any, max_len: int = 8000) -> str:
    result = json.dumps(data, indent=2, default=str)
    if len(result) > max_len:
        return result[:max_len] + "\n\n... [truncated – use more specific filters to narrow results]"
    return result


def _compact_list(items: list, keys: list[str], max_items: int = 30) -> list[dict]:
    """Extract only specified keys from each item, capped at max_items."""
    results = []
    for item in items[:max_items]:
        if isinstance(item, dict):
            entry = {k: item[k] for k in keys if k in item}
            results.append(entry)
        else:
            results.append(item)
    if len(items) > max_items:
        results.append({"_note": f"Showing {max_items} of {len(items)} total. Use search/filters to narrow."})
    return results


def _handle_error(e: Exception, service: str) -> str:
    if isinstance(e, ServiceNotConfiguredError):
        return _error_response("SERVICE_NOT_CONFIGURED", str(e), service)
    if isinstance(e, httpx.HTTPStatusError):
        body = e.response.text[:300] if e.response.text else ""
        return _error_response("API_ERROR", f"HTTP {e.response.status_code}: {body}", service, status_code=e.response.status_code)
    return _error_response("UNKNOWN_ERROR", str(e), service)


# ============================================================================
# METRICS EXPLORER TOOLS (5)
# ============================================================================

@tool
async def metrics_get_overview() -> str:
    """Get metrics organization overview including the list of important (used) dashboards.

    ALWAYS call this first for metrics investigation.
    Returns: org name, providers, used_dashboards with titles and IDs.
    """
    try:
        client = _me()
        org = await client.get_organization()

        result: dict[str, Any] = {
            "org_name": org.get("name"),
            "providers": [
                {"type": p.get("provider_type"), "name": p.get("name"), "active": p.get("is_active")}
                for p in org.get("providers", [])
            ],
            "used_dashboard_ids": org.get("used_dashboards", []),
        }

        # Get full details of used dashboards
        if org.get("used_dashboards"):
            try:
                used = await client.get_used_dashboards()
                result["used_dashboards"] = [
                    {
                        "db_id": d.get("id"),
                        "provider_dashboard_id": d.get("dashboard_id"),
                        "title": d.get("title"),
                        "provider_type": d.get("provider_type"),
                    }
                    for d in used.get("used_dashboards", [])
                ]
            except Exception:
                result["used_dashboards_error"] = "Could not fetch used dashboard details"

        return _safe_json(result)
    except Exception as e:
        return _handle_error(e, "Metrics Explorer")


@tool
async def metrics_search_dashboards(search: str) -> str:
    """Search for dashboards by keyword (wildcard supported).

    Space-separated terms = OR search. Use * for wildcards.
    Examples: 'DynamoDB', 'fraud*', 'payment latency'.

    Args:
        search: Wildcard search pattern for dashboard titles.
    """
    try:
        result = await _me().search_dashboards(search)
        dashboards = result.get("dashboards", [])
        return _safe_json({
            "total_count": result.get("total_count", len(dashboards)),
            "dashboards": _compact_list(
                dashboards,
                ["id", "dashboard_id", "title", "provider_type"],
                max_items=20,
            ),
        })
    except Exception as e:
        return _handle_error(e, "Metrics Explorer")


@tool
async def metrics_explore_dashboard(dashboard_db_id: str, metric_search: str = "") -> str:
    """Explore a dashboard: list its metrics and template variables.

    Use the db_id (UUID) from metrics_get_overview or metrics_search_dashboards.

    Args:
        dashboard_db_id: Database UUID of the dashboard (NOT the provider ID).
        metric_search: Optional wildcard to filter metrics (e.g. 'error*', 'latency').
    """
    try:
        client = _me()

        # Get metrics
        metrics_result = await client.search_metrics(dashboard_db_id, search=metric_search)
        metrics = metrics_result.get("metrics", [])

        # Get template variables
        try:
            variables_raw = await client.list_template_variables(dashboard_db_id)
            var_summary = []
            # Handle both list and dict wrapper formats
            var_list = variables_raw
            if isinstance(variables_raw, dict):
                var_list = variables_raw.get("template_variables", variables_raw.get("data", []))
            if isinstance(var_list, list):
                for v in var_list:
                    var_summary.append({
                        "name": v.get("variable_name") or v.get("name"),
                        "tag_key": v.get("tag_key"),
                        "default_value": v.get("default_value"),
                        "total_values": len(v.get("values", [])) or v.get("total_count"),
                    })
        except Exception:
            var_summary = []

        # Extract actual metric names from the query details
        enriched_metrics = []
        for m in metrics[:25]:
            entry = {
                "id": m.get("id"),
                "display_name": m.get("name"),
                "description": m.get("description"),
            }
            # Extract actual datadog metric names from the details
            details = m.get("details", {})
            requests = details.get("requests", [])
            actual_metrics = []
            for req in requests:
                for q in req.get("queries", []):
                    query_str = q.get("query", "")
                    if query_str:
                        actual_metrics.append(query_str)
            if actual_metrics:
                entry["actual_queries"] = actual_metrics[:3]  # Show first 3 raw queries
                # Try to extract the metric name from the first query (format: agg:metric_name{...})
                first_q = actual_metrics[0]
                if ":" in first_q and "{" in first_q:
                    metric_part = first_q.split(":", 1)[1].split("{")[0]
                    entry["metric_name"] = metric_part
            enriched_metrics.append(entry)

        return _safe_json({
            "total_metrics": metrics_result.get("total_count", len(metrics)),
            "metrics": enriched_metrics,
            "template_variables": var_summary,
        })
    except Exception as e:
        return _handle_error(e, "Metrics Explorer")


@tool
async def metrics_get_variable_values(
    dashboard_db_id: str,
    variable_name: str,
    search: str | None = None,
) -> str:
    """Get available values for a dashboard template variable.

    Use this to discover what filter values exist before querying metrics.

    Args:
        dashboard_db_id: Database UUID of the dashboard.
        variable_name: Variable name (e.g. 'tablename', 'service', 'environment').
        search: Optional search to narrow high-cardinality variables (e.g. 'prod', 'ccfraud').
    """
    try:
        result = await _me().get_variable_values(dashboard_db_id, variable_name, search=search)
        values = result.get("values", [])
        return _safe_json({
            "variable_name": result.get("variable_name"),
            "tag_key": result.get("tag_key"),
            "default_value": result.get("default_value"),
            "total_count": result.get("total_count"),
            "returned_count": result.get("returned_count", len(values)),
            "values": values[:50],
            "_note": f"Showing first 50 of {result.get('total_count', len(values))} values" if len(values) > 50 else None,
        })
    except Exception as e:
        return _handle_error(e, "Metrics Explorer")


@tool
async def metrics_query(
    dashboard_provider_id: str,
    metric_name: str,
    aggregation: str = "avg",
    filters: dict | None = None,
    group_by: list[str] | None = None,
    time_range: str = "1h",
) -> str:
    """Execute a metric query against a dashboard.

    Use the provider_dashboard_id (e.g. '4k2-qvg-h38') from dashboard search results.

    Args:
        dashboard_provider_id: Provider dashboard ID (e.g. '4k2-qvg-h38'), NOT the database UUID.
        metric_name: Full metric name (e.g. 'aws.dynamodb.consumed_read_capacity_units').
        aggregation: avg, sum, min, max, count, or last.
        filters: Tag filters dict (e.g. {'service': 'ccfraud', 'environment': 'prod'}). Optional.
        group_by: Tag keys to group results by (e.g. ['service']). Optional.
        time_range: Relative time range: '15m', '1h', '4h', '24h', '7d'. Default '1h'.
    """
    try:
        query: dict[str, Any] = {
            "metric_name": metric_name,
            "aggregation": aggregation,
        }
        if filters:
            query["filters"] = filters
        if group_by:
            query["group_by"] = group_by

        result = await _me().query_metrics(
            dashboard_provider_id=dashboard_provider_id,
            queries=[query],
            time_range={"relative": time_range},
        )

        # Compact the response: summarize series
        output: dict[str, Any] = {
            "dashboard_id": result.get("dashboard_id"),
            "provider": result.get("provider"),
            "execution_time_ms": result.get("execution_time_ms"),
            "total_series": result.get("total_series"),
            "total_datapoints": result.get("total_datapoints"),
        }

        for r in result.get("results", []):
            output["expression"] = r.get("expression")
            series_summary = []
            for s in r.get("series", []):
                datapoints = s.get("datapoints", [])
                values = [dp["value"] for dp in datapoints if dp.get("value") is not None]
                summary = {
                    "scope": s.get("scope"),
                    "tags": s.get("tags"),
                    "unit": s.get("unit"),
                    "datapoint_count": len(datapoints),
                }
                if values:
                    summary["avg"] = round(sum(values) / len(values), 4)
                    summary["min"] = round(min(values), 4)
                    summary["max"] = round(max(values), 4)
                    summary["latest"] = round(values[-1], 4)
                    # Include last 5 datapoints for trend
                    summary["recent_datapoints"] = [
                        {"ts": dp["timestamp"], "val": round(dp["value"], 4) if dp["value"] is not None else None}
                        for dp in datapoints[-5:]
                    ]
                else:
                    summary["note"] = "No non-null datapoints in this series"
                series_summary.append(summary)
            output["series"] = series_summary

        return _safe_json(output)
    except Exception as e:
        return _handle_error(e, "Metrics Explorer")


# ============================================================================
# LOGS EXPLORER TOOLS (3)
# ============================================================================

@tool
async def logs_get_overview() -> str:
    """Get logs organization overview including used (important) indexes.

    ALWAYS call this first for logs investigation.
    Returns: org name, used_indexes, total index/source/application counts.
    """
    try:
        org = await _le().get_organization()
        return _safe_json({
            "org_name": org.get("name"),
            "used_indexes": org.get("used_indexes", []),
            "index_count": org.get("index_count"),
            "source_count": org.get("source_count"),
            "application_count": org.get("application_count"),
            "provider_configured": org.get("provider_configured"),
        })
    except Exception as e:
        return _handle_error(e, "Logs Explorer")


@tool
async def logs_search_sources(search: str, repository_id: str | None = None) -> str:
    """Search for log sources (services) by keyword.

    Space-separated terms = OR search. Supports * wildcard.

    Args:
        search: Search pattern (e.g. 'ccfraud', 'payment*fraud', 'payment fraud').
        repository_id: Optional index/repo ID to scope the search.
    """
    try:
        result = await _le().search_sources(search, repository_id=repository_id)
        # Handle various response shapes
        if isinstance(result, dict):
            matches = result.get("matches", result.get("sources", result.get("data", [])))
            return _safe_json({
                "total_matches": len(matches) if isinstance(matches, list) else 0,
                "matches": _compact_list(
                    matches if isinstance(matches, list) else [],
                    ["name", "repository_name", "repository_id", "total_count", "last_event_at"],
                    max_items=30,
                ),
            })
        return _safe_json(result)
    except Exception as e:
        return _handle_error(e, "Logs Explorer")


@tool
async def logs_search(
    index: str,
    source: str | None = None,
    query_terms: list[str] | None = None,
    time_range_minutes: int = 60,
    max_results: int = 50,
) -> str:
    """Search application logs for errors, exceptions, and patterns.

    Args:
        index: Log index name (e.g. 'prod_g2'). Use logs_get_overview to find used_indexes.
        source: Service/source name filter (auto-wrapped with wildcards). Optional but recommended.
        query_terms: Search terms list (e.g. ['ERROR', 'exception', 'timeout']). Each is quoted.
        time_range_minutes: How many minutes back to search (default 60, max 10080 = 7 days).
        max_results: Max log entries (default 50, max 200).
    """
    try:
        now = datetime.now(timezone.utc)
        from_time = (now - timedelta(minutes=min(time_range_minutes, 10080))).isoformat()
        to_time = now.isoformat()

        result = await _le().search_logs(
            index=index,
            from_time=from_time,
            to_time=to_time,
            source=source,
            query=query_terms,
            max_results=min(max_results, 200),
        )

        # Summarize the log results
        data = result.get("data", [])
        if not data:
            return _safe_json({
                "total_results": 0,
                "query": {"index": index, "source": source, "terms": query_terms, "time_range_minutes": time_range_minutes},
                "note": "No logs found matching the query. Try different search terms, broader time range, or check the source name.",
            })

        # Return log entries with reasonable truncation per entry
        entries = []
        for log_entry in data[:max_results]:
            if isinstance(log_entry, dict):
                # Keep the raw field if it's the main content, otherwise keep all keys
                entry = {}
                for k, v in log_entry.items():
                    if isinstance(v, str) and len(v) > 500:
                        entry[k] = v[:500] + "..."
                    else:
                        entry[k] = v
                entries.append(entry)
            else:
                entries.append(str(log_entry)[:500])

        return _safe_json({
            "total_results": len(data),
            "showing": len(entries),
            "query": {"index": index, "source": source, "terms": query_terms, "time_range_minutes": time_range_minutes},
            "logs": entries,
        })
    except Exception as e:
        return _handle_error(e, "Logs Explorer")


# ============================================================================
# CODE PARSER TOOLS (4)
# ============================================================================

@tool
async def code_search_entry_points(search: str = "", entry_point_type: str | None = None) -> str:
    """Search entry points (HTTP endpoints, event handlers, schedulers) by regex.

    Args:
        search: Regex pattern to match entry point name/description (e.g. 'fraud', 'payment|transaction', 'POST.*risk').
        entry_point_type: Filter by type: 'HTTP', 'EVENT', 'SCHEDULER'. None for all.
    """
    try:
        results = await _cp().search_entry_points(search=search, limit=100)

        # Filter by type if specified
        if entry_point_type and isinstance(results, list):
            results = [ep for ep in results if ep.get("entry_point_type") == entry_point_type]

        if isinstance(results, list):
            return _safe_json({
                "total_count": len(results),
                "entry_points": _compact_list(
                    results,
                    ["id", "name", "description", "entry_point_type", "framework", "metadata", "ai_confidence"],
                    max_items=30,
                ),
            })
        return _safe_json(results)
    except Exception as e:
        return _handle_error(e, "Code Parser")


@tool
async def code_get_flows(entry_point_ids: list[str]) -> str:
    """Get detailed execution flow documentation for entry points.

    Shows step-by-step what happens when an endpoint is called, including
    code snippets, file paths, and log lines.

    Args:
        entry_point_ids: List of entry point IDs (from code_search_entry_points). Max 5.
    """
    try:
        ids = entry_point_ids[:5]  # Cap at 5
        result = await _cp().get_flows(ids)
        return _safe_json(result, max_len=settings.agent_tool_response_max_chars)  # Flows can be large but are highly valuable
    except Exception as e:
        return _handle_error(e, "Code Parser")


@tool
async def code_search_files(search: str) -> str:
    """Search source code files by regex on file path.

    Args:
        search: Regex pattern matching file relative_path (e.g. 'controller|handler', 'FraudService', '\\.py$', 'src/main/.*Service').
    """
    try:
        results = await _cp().search_files(search=search, limit=50)
        if isinstance(results, list):
            return _safe_json({
                "total_count": len(results),
                "files": _compact_list(
                    results,
                    ["id", "relative_path", "language"],
                    max_items=30,
                ),
            })
        return _safe_json(results)
    except Exception as e:
        return _handle_error(e, "Code Parser")


@tool
async def code_get_file(file_id: str) -> str:
    """Read the full source code of a specific file.

    Use after finding the file via code_search_files or from flow documentation.

    Args:
        file_id: File ID (from code_search_files or flow file_paths).
    """
    try:
        result = await _cp().get_file_detail(file_id)
        return _safe_json(result, max_len=settings.agent_tool_response_max_chars)
    except Exception as e:
        return _handle_error(e, "Code Parser")


# ---------------------------------------------------------------------------
ALL_TOOLS = [
    # Metrics Explorer (5)
    metrics_get_overview,
    metrics_search_dashboards,
    metrics_explore_dashboard,
    metrics_get_variable_values,
    metrics_query,
    # Logs Explorer (3)
    logs_get_overview,
    logs_search_sources,
    logs_search,
    # Code Parser (4)
    code_search_entry_points,
    code_get_flows,
    code_search_files,
    code_get_file,
]
