"""Base async HTTP client for downstream services."""

from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class BaseServiceClient:
    """Async HTTP client base with retry and error handling."""

    def __init__(self, base_url: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict | list:
        """HTTP GET with logging."""
        full_url = f"{self.base_url}{path}"
        logger.debug("http_get", url=full_url, params=params)
        try:
            resp = await self.client.get(path, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("http_get_error", url=full_url, status_code=e.response.status_code, response_text=e.response.text[:500])
            raise
        except httpx.RequestError as e:
            logger.error("http_get_connection_error", url=full_url, error=str(e), error_type=type(e).__name__)
            raise
        except Exception as e:
            logger.error("http_get_unexpected_error", url=full_url, error=str(e), error_type=type(e).__name__)
            raise

    async def _post(
        self,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict | list:
        """HTTP POST with logging."""
        full_url = f"{self.base_url}{path}"
        logger.info("http_post", url=full_url, body_keys=list((json_body or {}).keys()), headers=list((headers or {}).keys()))
        try:
            resp = await self.client.post(path, json=json_body, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("http_post_error", url=full_url, status_code=e.response.status_code, response_text=e.response.text[:500])
            raise
        except httpx.RequestError as e:
            logger.error("http_post_connection_error", url=full_url, error=str(e), error_type=type(e).__name__)
            raise
        except Exception as e:
            logger.error("http_post_unexpected_error", url=full_url, error=str(e), error_type=type(e).__name__)
            raise
