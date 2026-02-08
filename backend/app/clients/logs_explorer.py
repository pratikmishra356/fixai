"""Logs Explorer service client.

Wraps the logs-explorer REST API per API_FOR_AI.md.
Workflow: org → used_indexes → search sources → search logs.
"""

from typing import Any
from uuid import UUID

from app.clients.base import BaseServiceClient


class LogsExplorerClient(BaseServiceClient):
    """Client for the Logs Explorer service."""

    def __init__(self, base_url: str, org_id: UUID):
        super().__init__(base_url)
        self.org_id = str(org_id)

    @property
    def _org_prefix(self) -> str:
        return f"/api/v1/organizations/{self.org_id}"

    # --- Organization ---

    async def get_organization(self) -> dict:
        """Get org details including used_indexes list."""
        return await self._get(f"{self._org_prefix}")

    # --- Indexes ---

    async def list_indexes(self) -> list[dict]:
        """List available log indexes/repositories.

        Returns: [{id, name, description, synced_at}].
        """
        return await self._get(f"{self._org_prefix}/indexes")

    async def get_index_sources(self, index_id: str) -> list[dict]:
        """List sources (services) within a specific log index.

        Returns: [{id, name, total_count, last_event_at, repository_id}].
        """
        return await self._get(f"{self._org_prefix}/indexes/{index_id}/sources")

    # --- Sources ---

    async def search_sources(
        self,
        search: str,
        repository_id: str | None = None,
    ) -> dict:
        """Search sources (services) across all indexes.

        Space-separated terms = OR search. Supports * wildcard.

        Args:
            search: Search pattern (e.g. 'payment fraud', 'ccfraud*').
            repository_id: Optional index/repo ID to scope the search.

        Returns: matches[{name, repository_name, repository_id}].
        """
        body: dict[str, Any] = {"search": search}
        if repository_id:
            body["repository_id"] = repository_id
        return await self._post(f"{self._org_prefix}/sources/search", json_body=body)

    # --- Search Logs ---

    async def search_logs(
        self,
        index: str,
        from_time: str,
        to_time: str,
        source: str | None = None,
        query: list[str] | None = None,
        max_results: int = 100,
    ) -> dict:
        """Search logs in a specific index.

        Args:
            index: Index name (e.g. 'prod_g2'). Required.
            from_time: ISO 8601 start time.
            to_time: ISO 8601 end time.
            source: Service/source filter (auto-wrapped with wildcards).
            query: Search terms (each quoted in the underlying query).
            max_results: Max entries (default 100, max 1000).

        Returns: {data: [log_entry_dict[]]}.
        """
        body: dict[str, Any] = {
            "index": index,
            "from_time": from_time,
            "to_time": to_time,
            "max_results": max_results,
        }
        if source:
            body["source"] = source
        if query:
            body["query"] = query
        return await self._post(f"{self._org_prefix}/search", json_body=body)
