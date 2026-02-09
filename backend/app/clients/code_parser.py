"""Code Parser service client.

Wraps the code-parser REST API per API_FOR_AI.md.
Org-level endpoints: /api/v1/orgs/{org_id}/repos/...
Repo-scoped endpoints: /api/v1/orgs/{org_id}/repos/{repo_id}/...
Supports regex search on entry points, files.
"""

from typing import Any

from app.clients.base import BaseServiceClient


class CodeParserClient(BaseServiceClient):
    """Client for the Code Parser service.

    Supports dynamic repo switching: a default repo_id can be set at init,
    but every repo-scoped method accepts an optional repo_id override.
    """

    def __init__(self, base_url: str, org_id: str, repo_id: str | None = None):
        super().__init__(base_url)
        self.org_id = str(org_id)
        self.default_repo_id = str(repo_id) if repo_id else None

    def _resolve_repo_id(self, repo_id: str | None) -> str:
        """Return explicit repo_id if given, else fall back to default."""
        rid = repo_id or self.default_repo_id
        if not rid:
            raise ValueError(
                "No repo_id provided and no default configured. "
                "Call code_search_repositories first to find the correct repository, "
                "then pass its id to the tool."
            )
        return rid

    def _repo_prefix(self, repo_id: str | None = None) -> str:
        rid = self._resolve_repo_id(repo_id)
        return f"/api/v1/orgs/{self.org_id}/repos/{rid}"

    # --- Org-level (no repo_id needed) ---

    async def list_repositories(self, search: str = "", limit: int = 50) -> list[dict]:
        """List repositories, optionally filtered by regex search."""
        return await self._get(
            f"/api/v1/orgs/{self.org_id}/repos",
            params={"search": search, "limit": limit},
        )

    async def get_repository(self, repo_id: str | None = None) -> dict:
        """Get repository metadata (name, description, status, languages, total_files)."""
        rid = self._resolve_repo_id(repo_id)
        repos = await self._get(
            f"/api/v1/orgs/{self.org_id}/repos",
            params={"search": "", "limit": 100},
        )
        if isinstance(repos, list):
            for r in repos:
                if r.get("id") == rid:
                    return r
        return {"error": f"Repository {rid} not found"}

    # --- Repo-scoped ---

    async def search_entry_points(
        self,
        search: str = "",
        limit: int = 100,
        offset: int = 0,
        repo_id: str | None = None,
    ) -> list[dict]:
        """Search entry points by regex pattern.

        Matches against name and description (case-insensitive).
        Returns: id, name, description, entry_point_type, framework, metadata, ai_confidence.
        """
        return await self._get(
            f"{self._repo_prefix(repo_id)}/entry-points",
            params={"search": search, "limit": limit, "offset": offset},
        )

    async def get_flows(
        self,
        entry_point_ids: list[str],
        repo_id: str | None = None,
    ) -> list[dict]:
        """Get execution flow documentation for one or more entry points.

        Returns step-by-step execution with code snippets and log lines.
        """
        return await self._post(
            f"{self._repo_prefix(repo_id)}/flows",
            json_body={"entry_point_ids": entry_point_ids},
        )

    async def search_files(
        self,
        search: str = "",
        limit: int = 100,
        offset: int = 0,
        repo_id: str | None = None,
    ) -> list[dict]:
        """Search files by regex pattern on relative_path.

        Returns: id, relative_path, language, content_hash.
        """
        return await self._get(
            f"{self._repo_prefix(repo_id)}/files",
            params={"search": search, "limit": limit, "offset": offset},
        )

    async def get_file_detail(
        self,
        file_id: str,
        repo_id: str | None = None,
    ) -> dict:
        """Get full file details including source code content.

        Returns: content, relative_path, language, content_hash, folder_structure.
        """
        return await self._get(f"{self._repo_prefix(repo_id)}/files/{file_id}")
