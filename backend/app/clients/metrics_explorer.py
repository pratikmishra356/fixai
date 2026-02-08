"""Metrics Explorer service client.

Wraps the metrics-explorer REST API per API_FOR_AI.md.
Dashboard-centric workflow: org → used_dashboards → search → metrics → query.
Uses X-Organization-Id header for query endpoints.
"""

from typing import Any
from uuid import UUID

from app.clients.base import BaseServiceClient


class MetricsExplorerClient(BaseServiceClient):
    """Client for the Metrics Explorer service."""

    def __init__(self, base_url: str, org_id: UUID):
        super().__init__(base_url)
        self.org_id = str(org_id)

    @property
    def _org_prefix(self) -> str:
        return f"/api/v1/organizations/{self.org_id}"

    @property
    def _org_header(self) -> dict[str, str]:
        return {"X-Organization-Id": self.org_id}

    # --- Organization ---

    async def get_organization(self) -> dict:
        """Get org details including used_dashboards list and providers."""
        return await self._get(f"{self._org_prefix}")

    async def get_used_dashboards(self) -> dict:
        """Get details for dashboards marked as important (used_dashboards).

        Returns: dashboard_ids, used_dashboards[{id, dashboard_id, title, provider_type}].
        """
        return await self._get(f"{self._org_prefix}/used-dashboards")

    # --- Dashboard Discovery ---

    async def search_dashboards(self, search: str) -> dict:
        """Search dashboards by wildcard pattern.

        Space-separated terms = OR search. Supports * wildcard.
        Returns: dashboards[{id, dashboard_id, title, provider_type}], total_count.
        """
        return await self._get(
            f"{self._org_prefix}/dashboards/search",
            params={"search": search},
        )

    # --- Metrics within a Dashboard ---

    async def search_metrics(
        self,
        dashboard_db_id: str,
        search: str = "",
    ) -> dict:
        """Search metrics (widgets) within a specific dashboard.

        Args:
            dashboard_db_id: Database UUID of the dashboard (from search_dashboards).
            search: Wildcard pattern for metric name.

        Returns: metrics[{id, widget_id, name, description, provider, details}].
        """
        return await self._get(
            f"{self._org_prefix}/dashboards/{dashboard_db_id}/metrics/search",
            params={"search": search or "*"},
        )

    # --- Template Variables ---

    async def list_template_variables(self, dashboard_db_id: str) -> list[dict]:
        """List all template variables for a dashboard with their resolved values."""
        return await self._get(
            f"{self._org_prefix}/template-variables",
            params={"dashboard_id": dashboard_db_id},
        )

    async def get_variable_values(
        self,
        dashboard_db_id: str,
        variable_name: str,
        search: str | None = None,
    ) -> dict:
        """Get resolved values for a specific template variable.

        Args:
            dashboard_db_id: Database UUID of the dashboard.
            variable_name: Name of the variable (e.g. 'tablename').
            search: Optional search to narrow high-cardinality variables.

        Returns: variable_name, tag_key, default_value, values[], total_count.
        """
        params: dict[str, Any] = {}
        if search:
            params["search"] = search
        return await self._get(
            f"{self._org_prefix}/dashboards/{dashboard_db_id}/variables/{variable_name}/values",
            params=params,
        )

    # --- Query Metrics ---

    async def query_metrics(
        self,
        dashboard_provider_id: str,
        queries: list[dict],
        time_range: dict,
    ) -> dict:
        """Execute metric queries against a dashboard.

        Args:
            dashboard_provider_id: Provider dashboard ID (e.g. '4k2-qvg-h38'), NOT database UUID.
            queries: List of query dicts with:
                - metric_name (str)
                - aggregation (str): avg, sum, min, max, count, last
                - filters (dict, optional): tag filters
                - group_by (list[str], optional): tag keys to group by
            time_range: Either {"relative": "1h"} or {"start": epoch, "end": epoch}.

        Returns: results with series data, datapoints, expression.
        """
        return await self._post(
            f"/api/v1/dashboards/{dashboard_provider_id}/query",
            json_body={"queries": queries, "time_range": time_range},
            headers=self._org_header,
        )
