"""Code Parser service client.

Wraps the code-parser REST API per API_FOR_AI.md.
All endpoints scoped: /api/v1/orgs/{org_id}/repos/{repo_id}/...
Supports regex search on entry points, files.
"""

from typing import Any

from app.clients.base import BaseServiceClient


class CodeParserClient(BaseServiceClient):
    """Client for the Code Parser service."""

    def __init__(self, base_url: str, org_id: str, repo_id: str):
        super().__init__(base_url)
        self.org_id = str(org_id)
        self.repo_id = str(repo_id)

    @property
    def _repo_prefix(self) -> str:
        return f"/api/v1/orgs/{self.org_id}/repos/{self.repo_id}"

    # --- Repository ---

    async def get_repository(self) -> dict:
        """Get repository metadata (name, description, status, languages, total_files)."""
        repos = await self._get(
            f"/api/v1/orgs/{self.org_id}/repos",
            params={"search": "", "limit": 100},
        )
        # Find the specific repo
        if isinstance(repos, list):
            for r in repos:
                if r.get("id") == self.repo_id:
                    return r
        return {"error": f"Repository {self.repo_id} not found"}

    async def list_repositories(self, search: str = "", limit: int = 50) -> list[dict]:
        """List repositories, optionally filtered by regex search."""
        return await self._get(
            f"/api/v1/orgs/{self.org_id}/repos",
            params={"search": search, "limit": limit},
        )

    # --- Entry Points ---

    async def search_entry_points(
        self,
        search: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Search entry points by regex pattern.

        Matches against name and description (case-insensitive).
        Returns: id, name, description, entry_point_type, framework, metadata, ai_confidence.
        """
        return await self._get(
            f"{self._repo_prefix}/entry-points",
            params={"search": search, "limit": limit, "offset": offset},
        )

    # --- Flows ---

    async def get_flows(self, entry_point_ids: list[str]) -> list[dict]:
        """Get execution flow documentation for one or more entry points.

        Returns step-by-step execution with code snippets and log lines.
        """
        return await self._post(
            f"{self._repo_prefix}/flows",
            json_body={"entry_point_ids": entry_point_ids},
        )

    # --- Files ---

    async def search_files(
        self,
        search: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Search files by regex pattern on relative_path.

        Returns: id, relative_path, language, content_hash.
        """
        return await self._get(
            f"{self._repo_prefix}/files",
            params={"search": search, "limit": limit, "offset": offset},
        )

    async def get_file_detail(self, file_id: str) -> dict:
        """Get full file details including source code content.

        Returns: content, relative_path, language, content_hash, folder_structure.
        """
        return await self._get(f"{self._repo_prefix}/files/{file_id}")
