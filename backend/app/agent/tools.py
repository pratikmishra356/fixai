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
import structlog
from langchain_core.tools import tool

logger = structlog.get_logger(__name__)

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
        logger.error("metrics_explorer_not_configured", available_clients=list(_clients.keys()))
        raise ServiceNotConfiguredError("Metrics Explorer is not configured for this organization")
    logger.debug("metrics_explorer_client", base_url=c.base_url, org_id=c.org_id)
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
    """Get metrics organization overview: providers and important dashboards.

    Returns org name, active providers, and used_dashboards (each with db_id and provider_dashboard_id).
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
    """List metrics and template variables in a dashboard.

    Returns: provider (e.g. datadog), metrics (metric_name, queries list), template_variables
    (name, tag_key). Does NOT include variable values — call metrics_get_variable_values
    with variable names from template_variables when you need filter values.

    Args:
        dashboard_db_id: Database UUID of the dashboard (from metrics_get_overview or metrics_search_dashboards).
        metric_search: Optional wildcard to filter metrics. Empty = all metrics.
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

        # Build minimal response: queries list + template_variables
        metrics_list = []
        for m in metrics[:40]:
            details = m.get("details", {})
            requests = details.get("requests", [])
            queries = []
            for req in requests:
                for q in req.get("queries", []):
                    query_str = q.get("query", "")
                    if query_str:
                        queries.append(query_str)
            if not queries:
                continue
            metric_name = None
            first_q = queries[0]
            if ":" in first_q and "{" in first_q:
                metric_name = first_q.split(":", 1)[1].split("{")[0]
            metrics_list.append({"metric_name": metric_name or "unknown", "queries": queries})

        # Minimal template_variables: name, tag_key (for metrics_get_variable_values and filters)
        template_vars = [
            {"name": v.get("name"), "tag_key": v.get("tag_key")}
            for v in var_summary
            if v.get("name") and v.get("tag_key")
        ]

        # Provider from first metric (e.g. datadog, grafana)
        provider = metrics[0].get("provider") if metrics else None

        return _safe_json(
            {"provider": provider, "metrics": metrics_list, "template_variables": template_vars},
            max_len=16_000,
        )
    except Exception as e:
        return _handle_error(e, "Metrics Explorer")


@tool
async def metrics_get_variable_values(
    dashboard_db_id: str,
    variable_requests: list[dict],
) -> str:
    """Get filter values for one or more template variables in a single call.

    Call when you need actual values for metrics_query filters. Use name from
    template_variables (metrics_explore_dashboard). Pass a list of {variable_name,
    search_string}. If search_string returns no values, returns first 50 values.

    Args:
        dashboard_db_id: Database UUID of the dashboard (from used_dashboards).
        variable_requests: List of {"variable_name": str, "search_string": str | None}.
            Use template_variables[].name from metrics_explore_dashboard.
    """
    try:
        client = _me()
        requests = variable_requests if isinstance(variable_requests, list) else []
        if isinstance(variable_requests, dict):
            requests = [variable_requests]
        results = []
        for req in requests:
            if not isinstance(req, dict):
                continue
            vname = req.get("variable_name") or req.get("name")
            search_str = req.get("search_string") or req.get("search")
            if not vname:
                continue
            try:
                result = await client.get_variable_values(
                    dashboard_db_id, vname, search=search_str if search_str else None
                )
                values = result.get("values", [])
                total = result.get("total_count", len(values))
                fallback = False
                if not values and (search_str or "").strip():
                    result = await client.get_variable_values(dashboard_db_id, vname, search=None)
                    values = result.get("values", [])[:50]
                    total = result.get("total_count", len(result.get("values", [])))
                    fallback = True
                else:
                    values = values[:50]
                results.append({
                    "variable_name": result.get("variable_name", vname),
                    "tag_key": result.get("tag_key"),
                    "default_value": result.get("default_value"),
                    "search_used": search_str,
                    "values": values,
                    "total_count": total,
                    "returned_count": len(values),
                    "fallback_to_first_50": fallback,
                })
            except Exception as e:
                results.append({
                    "variable_name": vname,
                    "error": str(e),
                })
        return _safe_json({"results": results})
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
    start_time: str | None = None,
    end_time: str | None = None,
) -> str:
    """Execute a metric query and return datapoints.

    Args:
        dashboard_provider_id: Provider dashboard ID (e.g. '4k2-qvg-h38'), NOT the database UUID.
        metric_name: Full metric name from metrics_explore_dashboard.
        aggregation: avg, sum, min, max, count, or last.
        filters: Tag filters. Use tag_key from template_variables; values from
                 metrics_get_variable_values (use name from template_variables).
        group_by: Tag keys to group results by. Optional.
        time_range: Relative time range: '15m', '1h', '4h', '24h', '7d'. Default '1h'.
            Ignored when start_time and end_time are provided.
        start_time: Absolute start as ISO 8601 string (e.g. '2026-02-10T00:00:00Z').
            Use with end_time for calendar-based date ranges.
        end_time: Absolute end as ISO 8601 string (e.g. '2026-02-11T23:59:59Z').
            Use with start_time for calendar-based date ranges.
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

        # Build time_range payload: absolute dates take precedence over relative
        if start_time and end_time:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            time_range_payload: dict[str, Any] = {
                "start": int(start_dt.timestamp()),
                "end": int(end_dt.timestamp()),
            }
        else:
            time_range_payload = {"relative": time_range}

        logger.info(
            "metrics_query_calling",
            dashboard_provider_id=dashboard_provider_id,
            metric_name=metric_name,
            aggregation=aggregation,
            filters=filters,
            time_range=time_range_payload,
        )

        result = await _me().query_metrics(
            dashboard_provider_id=dashboard_provider_id,
            queries=[query],
            time_range=time_range_payload,
        )

        logger.info(
            "metrics_query_result",
            dashboard_id=result.get("dashboard_id"),
            total_series=result.get("total_series", 0),
            total_datapoints=result.get("total_datapoints", 0),
            results_count=len(result.get("results", [])),
        )

        # Compact the response: summarize series
        output: dict[str, Any] = {
            "dashboard_id": result.get("dashboard_id"),
            "provider": result.get("provider"),
            "execution_time_ms": result.get("execution_time_ms"),
            "total_series": result.get("total_series", 0),
            "total_datapoints": result.get("total_datapoints", 0),
        }

        results = result.get("results", [])
        if not results:
            output["note"] = "Query executed successfully but returned no results. This may mean: (1) no data exists for this metric/filter combination, (2) the metric name is incorrect, or (3) the filters exclude all data."
            return _safe_json(output)

        for r in results:
            output["expression"] = r.get("expression")
            series_summary = []
            series_list = r.get("series", [])
            if not series_list:
                output["note"] = "Query returned expression but no series data. This typically means the metric exists but has no data points for the specified time range or filters."
                continue

            for s in series_list:
                datapoints = s.get("datapoints", [])
                values = [dp["value"] for dp in datapoints if dp.get("value") is not None]
                summary: dict[str, Any] = {
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
        logger.error("metrics_query_error", error=str(e), error_type=type(e).__name__, dashboard_provider_id=dashboard_provider_id, metric_name=metric_name)
        return _handle_error(e, "Metrics Explorer")


# ============================================================================
# LOGS EXPLORER TOOLS (3)
# ============================================================================

@tool
async def logs_get_overview() -> str:
    """Get logs organization overview: used indexes and source/application counts.

    Returns org name, used_indexes, and counts of available indexes, sources, and applications.
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
async def logs_search_sources(
    search: str,
    index_name: str | None = None,
    repository_id: str | None = None,
) -> str:
    """Search for log sources (services) by keyword.

    Prefer index_name from used_indexes to scope the search to that index only.
    Space-separated terms = OR search. Supports * wildcard.

    Args:
        search: Search pattern (e.g. 'my-service', 'auth*', 'payment gateway').
        index_name: Optional. Index name from used_indexes. Use to scope the search to that
            index only. If omitted, search runs across all indexes.
        repository_id: Optional index/repo UUID to scope the search. Use index_name instead
            when you have index names from logs_get_overview.
    """
    try:
        repo_id: str | None = None
        if index_name:
            indexes = await _le().list_indexes()
            index_list = indexes if isinstance(indexes, list) else indexes.get("indexes", [])
            matched = next((idx for idx in index_list if isinstance(idx, dict) and idx.get("name") == index_name), None)
            if matched and matched.get("id"):
                repo_id = str(matched["id"])
            else:
                available = [idx.get("name", "") for idx in index_list if isinstance(idx, dict) and idx.get("name")]
                return _error_response(
                    "INDEX_NOT_FOUND",
                    f"Index '{index_name}' not found. Available indexes: {available}. Use one of these or omit index_name to search all.",
                    "Logs Explorer",
                    available_indexes=available,
                )
        elif repository_id:
            repo_id = repository_id

        result = await _le().search_sources(search, repository_id=repo_id)
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
    start_time: str | None = None,
    end_time: str | None = None,
) -> str:
    """Search application logs for errors, exceptions, and patterns.

    Args:
        index: Log index name (e.g. 'prod_g2'). Use logs_get_overview to find used_indexes.
        source: Service/source name filter (auto-wrapped with wildcards). Optional but recommended.
        query_terms: Search terms list (e.g. ['ERROR', 'exception', 'timeout']). Each is quoted.
        time_range_minutes: How many minutes back to search (default 60, max 10080 = 7 days).
            Ignored when start_time and end_time are provided.
        max_results: Max log entries (default 50, max 200).
        start_time: Absolute start as ISO 8601 string (e.g. '2026-02-10T00:00:00Z').
            Use with end_time for calendar-based date ranges. Max span 7 days.
        end_time: Absolute end as ISO 8601 string (e.g. '2026-02-11T23:59:59Z').
            Use with start_time for calendar-based date ranges.
    """
    try:
        if start_time and end_time:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            from_time = start_dt.isoformat()
            to_time = end_dt.isoformat()
        else:
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
                "query": {"index": index, "source": source, "terms": query_terms, "from_time": from_time, "to_time": to_time},
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
            "query": {"index": index, "source": source, "terms": query_terms, "from_time": from_time, "to_time": to_time},
            "logs": entries,
        })
    except Exception as e:
        return _handle_error(e, "Logs Explorer")


# ============================================================================
# CODE PARSER TOOLS (6)
# ============================================================================

@tool
async def code_search_repositories(search: str = "") -> str:
    """List repositories in this organization, optionally filtered by regex.

    Returns repo id, name, description, languages, and file count.
    Use the returned 'id' as repo_id in other code tools.

    Args:
        search: Regex pattern to match repo name/description. Empty string = list all repos.
    """
    try:
        repos = await _cp().list_repositories(search=search, limit=50)
        if isinstance(repos, list):
            return _safe_json({
                "total_count": len(repos),
                "repositories": _compact_list(
                    repos,
                    ["id", "name", "description", "languages", "total_files", "status"],
                    max_items=20,
                ),
            })
        return _safe_json(repos)
    except Exception as e:
        return _handle_error(e, "Code Parser")


@tool
async def code_get_repo_info(repo_id: str | None = None) -> str:
    """Get repository metadata: name, description, languages, file count.

    Args:
        repo_id: Repository ID (from code_search_repositories). Omit to use the default repo.
    """
    try:
        repo = await _cp().get_repository(repo_id=repo_id)
        return _safe_json({
            "repo_id": repo.get("id"),
            "name": repo.get("name"),
            "description": repo.get("description"),
            "languages": repo.get("languages"),
            "total_files": repo.get("total_files"),
            "status": repo.get("status"),
        })
    except Exception as e:
        return _handle_error(e, "Code Parser")


@tool
async def code_search_entry_points(
    search: str = "",
    entry_point_type: str | None = None,
    repo_id: str | None = None,
) -> str:
    """Search entry points (HTTP endpoints, event handlers, schedulers) by regex.

    Args:
        search: Regex pattern to match entry point name/description (e.g. 'fraud', 'payment|transaction', 'POST.*risk').
        entry_point_type: Filter by type: 'HTTP', 'EVENT', 'SCHEDULER'. None for all.
        repo_id: Repository ID from code_search_repositories. If omitted, uses the default configured repo.
    """
    try:
        results = await _cp().search_entry_points(search=search, limit=100, repo_id=repo_id)

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
async def code_get_flows(entry_point_ids: list[str], repo_id: str | None = None) -> str:
    """Get detailed execution flow documentation for entry points.

    Shows step-by-step what happens when an endpoint is called, including
    code snippets, file paths, and log lines.

    Args:
        entry_point_ids: List of entry point IDs (from code_search_entry_points). Max 5.
        repo_id: Repository ID from code_search_repositories. If omitted, uses the default configured repo.
    """
    try:
        ids = entry_point_ids[:5]  # Cap at 5
        result = await _cp().get_flows(ids, repo_id=repo_id)
        return _safe_json(result, max_len=settings.agent_tool_response_max_chars)
    except Exception as e:
        return _handle_error(e, "Code Parser")


@tool
async def code_search_files(search: str, repo_id: str | None = None) -> str:
    """Search source code files by regex on file path.

    Args:
        search: Regex pattern matching file relative_path (e.g. 'controller|handler', 'FraudService', '\\.py$', 'src/main/.*Service').
        repo_id: Repository ID from code_search_repositories. If omitted, uses the default configured repo.
    """
    try:
        results = await _cp().search_files(search=search, limit=50, repo_id=repo_id)
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
async def code_get_file(file_id: str, repo_id: str | None = None) -> str:
    """Read the full source code of a specific file.

    Use after finding the file via code_search_files or from flow documentation.

    Args:
        file_id: File ID (from code_search_files or flow file_paths).
        repo_id: Repository ID from code_search_repositories. If omitted, uses the default configured repo.
    """
    try:
        result = await _cp().get_file_detail(file_id, repo_id=repo_id)
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
    # Code Parser (6)
    code_search_repositories,
    code_get_repo_info,
    code_search_entry_points,
    code_get_flows,
    code_search_files,
    code_get_file,
]
