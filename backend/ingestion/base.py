"""
FormulaAI — Abstract Base Connector

All ingestion connectors inherit from this class to guarantee:
  • Async httpx client lifecycle
  • Per-source token-bucket rate limiting
  • Retry with exponential backoff on transient HTTP errors
  • Structured RawDocument output
  • Consistent logging and error handling
  • Cursor/offset-based pagination helpers
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator

import httpx
from aiolimiter import AsyncLimiter
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


# ── Shared Data Models ───────────────────────────────────────────────────────


@dataclass
class RawDocument:
    """
    A single document ingested from any source, before LLM extraction.

    This is the universal exchange format between ingestion connectors
    and the downstream parsing/extraction pipeline.
    """

    source_id: str                              # DOI, patent number, PMID, etc.
    source_type: str                            # "patent", "paper", "tds", "sds", etc.
    title: str
    abstract: str | None = None
    full_text: str | None = None
    authors: list[str] = field(default_factory=list)
    publication_date: str | None = None         # ISO-8601 string
    keywords: list[str] = field(default_factory=list)
    url: str | None = None                      # Link to original document
    pdf_url: str | None = None                  # Direct link to PDF if available
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_response: dict[str, Any] = field(default_factory=dict)
    ingested_at: str = field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z"
    )


@dataclass
class IngestionStats:
    """Tracks connector run statistics for monitoring."""

    connector_name: str
    documents_fetched: int = 0
    documents_failed: int = 0
    api_calls_made: int = 0
    started_at: str = field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z"
    )
    finished_at: str | None = None

    def finish(self) -> None:
        self.finished_at = datetime.utcnow().isoformat() + "Z"


# ── Abstract Base Connector ──────────────────────────────────────────────────


class BaseConnector(ABC):
    """
    Abstract base class for all ingestion connectors.

    Subclasses must define:
      - SOURCE_TYPE: class-level string (e.g., "patent", "paper")
      - search(): async generator yielding RawDocument
      - fetch_document(): fetch a single document by its ID

    Usage:
        async with MyConnector(rate_limit=5.0) as conn:
            async for doc in conn.search("glyphosate formulation"):
                process(doc)
    """

    SOURCE_TYPE: str = "unknown"

    def __init__(
        self,
        base_url: str,
        rate_limit: float = 5.0,
        timeout: float = 30.0,
        max_retries: int = 3,
        headers: dict[str, str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._limiter = AsyncLimiter(max_rate=rate_limit, time_period=1.0)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "User-Agent": "FormulaAI-DataFactory/1.0",
                **(headers or {}),
            },
        )
        self._stats = IngestionStats(connector_name=self.__class__.__name__)

    async def __aenter__(self) -> BaseConnector:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the HTTP client and finalize stats."""
        self._stats.finish()
        await self._client.aclose()
        logger.info(
            "%s finished: %d fetched, %d failed, %d API calls",
            self._stats.connector_name,
            self._stats.documents_fetched,
            self._stats.documents_failed,
            self._stats.api_calls_made,
        )

    @property
    def stats(self) -> IngestionStats:
        return self._stats

    # ── HTTP Helpers ─────────────────────────────────────────────────────

    async def _get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> dict | None:
        """
        Rate-limited GET request with retry on transient failures.

        Returns parsed JSON or None on 404.
        Raises on persistent failures after max_retries.
        """
        return await self._request("GET", url, params=params)

    async def _post(
        self,
        url: str,
        json_data: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict | None:
        """Rate-limited POST request with retry."""
        return await self._request("POST", url, json_data=json_data, data=data)

    @retry(
        retry=retry_if_exception_type(
            (httpx.TimeoutException, httpx.HTTPStatusError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        reraise=True,
    )
    async def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict | None:
        """Core request method with rate limiting and retry."""
        async with self._limiter:
            self._stats.api_calls_made += 1
            logger.debug("%s %s params=%s", method, url, params)

            resp = await self._client.request(
                method, url, params=params, json=json_data, data=data
            )

            if resp.status_code == 404:
                return None
            if resp.status_code == 429:
                # Rate limited — let tenacity retry
                logger.warning("Rate limited by %s, backing off...", url)
                raise httpx.HTTPStatusError(
                    "429 Too Many Requests",
                    request=resp.request,
                    response=resp,
                )
            resp.raise_for_status()
            return resp.json()

    async def _get_text(
        self, url: str, params: dict[str, Any] | None = None
    ) -> str | None:
        """Rate-limited GET returning raw text (for XML/HTML responses)."""
        async with self._limiter:
            self._stats.api_calls_made += 1
            resp = await self._client.get(url, params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.text

    # ── Pagination Helper ────────────────────────────────────────────────

    async def _paginate(
        self,
        url: str,
        params: dict[str, Any],
        results_key: str,
        cursor_key: str = "cursor",
        cursor_response_key: str | None = None,
        page_size: int = 50,
        max_pages: int = 100,
    ) -> AsyncIterator[list[dict]]:
        """
        Generic cursor-based pagination helper.

        Yields batches of results (list[dict]) from each page.

        Args:
            url: The API endpoint to paginate.
            params: Base query parameters (will be mutated with cursor).
            results_key: JSON key containing the results list.
            cursor_key: Query parameter name for the cursor/page token.
            cursor_response_key: JSON key in the response containing the
                next cursor value. If None, uses cursor_key.
            page_size: Number of results per page.
            max_pages: Safety cap on total pages to prevent runaway loops.
        """
        params = {**params, "per_page": page_size}
        cursor_resp_key = cursor_response_key or cursor_key
        pages = 0

        while pages < max_pages:
            data = await self._get(url, params=params)
            if data is None:
                break

            results = data.get(results_key, [])
            if not results:
                break

            yield results
            pages += 1

            # Advance cursor
            next_cursor = data.get("meta", {}).get(cursor_resp_key)
            if next_cursor is None:
                next_cursor = data.get(cursor_resp_key)
            if next_cursor is None:
                break
            params[cursor_key] = next_cursor

        logger.info(
            "%s: paginated %d pages from %s",
            self.__class__.__name__,
            pages,
            url,
        )

    # ── Abstract Interface ───────────────────────────────────────────────

    @abstractmethod
    async def search(
        self, query: str, max_results: int = 100, **kwargs: Any
    ) -> AsyncIterator[RawDocument]:
        """
        Search this source for documents matching the query.

        Yields RawDocument instances as they are fetched.
        """
        ...

    @abstractmethod
    async def fetch_document(self, doc_id: str) -> RawDocument | None:
        """Fetch a single document by its source-specific ID."""
        ...
