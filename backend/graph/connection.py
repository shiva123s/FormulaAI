"""
FormulaAI — Async Neo4j Connection Manager

Provides a singleton async Neo4j driver pool for the entire application.
All graph operations (schema init, MERGE queries, reads) go through this.

Design:
  • Singleton pattern via module-level instance — one driver per process
  • Async session factory for use in FastAPI endpoints and Celery tasks
  • Health-check / connectivity verification
  • Graceful shutdown with driver.close()

Usage:
    from graph.connection import get_neo4j, Neo4jConnection

    # In FastAPI startup:
    neo4j = get_neo4j()
    await neo4j.connect()

    # In a route or task:
    async with neo4j.session() as session:
        result = await session.run("MATCH (n) RETURN count(n)")

    # In FastAPI shutdown:
    await neo4j.close()
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession

from config import get_settings

logger = logging.getLogger(__name__)

# Module-level singleton
_instance: Neo4jConnection | None = None


class Neo4jConnection:
    """
    Async Neo4j connection manager.

    Wraps the neo4j async driver with lifecycle management,
    health checking, and a convenient session context manager.
    """

    def __init__(
        self,
        uri: str | None = None,
        username: str | None = None,
        password: str | None = None,
        max_connection_pool_size: int = 50,
        connection_timeout: float = 3.0,
    ):
        settings = get_settings()
        self._uri = uri or settings.neo4j_uri
        self._username = username or settings.neo4j_username
        self._password = password or settings.neo4j_password
        self._pool_size = max_connection_pool_size
        self._timeout = connection_timeout
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        """
        Initialize the async Neo4j driver.

        Call this during application startup (FastAPI lifespan).
        """
        if self._driver is not None:
            logger.warning("Neo4j driver already connected")
            return

        self._driver = AsyncGraphDatabase.driver(
            self._uri,
            auth=(self._username, self._password),
            max_connection_pool_size=self._pool_size,
            connection_timeout=self._timeout,
        )

        # Verify connectivity
        try:
            await self._driver.verify_connectivity()
            server_info = await self._driver.get_server_info()
            logger.info(
                "Neo4j connected: %s (v%s) at %s",
                server_info.agent,
                server_info.protocol_version,
                self._uri,
            )
        except Exception:
            logger.exception("Failed to connect to Neo4j at %s", self._uri)
            self._driver = None
            raise

    async def close(self) -> None:
        """Close the driver and release all connections."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("Neo4j driver closed")

    @property
    def is_connected(self) -> bool:
        return self._driver is not None

    @property
    def driver(self) -> AsyncDriver:
        if self._driver is None:
            raise RuntimeError(
                "Neo4j driver not initialized. Call connect() first."
            )
        return self._driver

    @asynccontextmanager
    async def session(
        self,
        database: str | None = None,
    ) -> AsyncIterator[AsyncSession]:
        """
        Yield an async Neo4j session.

        Usage:
            async with neo4j.session() as session:
                result = await session.run("MATCH ...")
        """
        async with self.driver.session(database=database) as session:
            yield session

    async def execute_write(
        self,
        query: str,
        parameters: dict | None = None,
        database: str | None = None,
    ) -> list[dict]:
        """
        Execute a single write query and return all records as dicts.

        Convenience method for simple one-off writes. For batch
        operations, use session() directly.
        """
        async with self.session(database=database) as session:
            result = await session.run(query, parameters or {})
            records = await result.data()
            return records

    async def execute_read(
        self,
        query: str,
        parameters: dict | None = None,
        database: str | None = None,
    ) -> list[dict]:
        """Execute a single read query and return all records as dicts."""
        async with self.session(database=database) as session:
            result = await session.run(query, parameters or {})
            records = await result.data()
            return records

    async def health_check(self) -> dict:
        """
        Verify Neo4j connectivity and return server info.

        Returns:
            Dict with status, server_agent, uri, and node/relationship counts.
        """
        if not self.is_connected:
            return {"status": "disconnected", "uri": self._uri}

        try:
            await self._driver.verify_connectivity()
            counts = await self.execute_read(
                "MATCH (n) WITH count(n) AS nodes "
                "OPTIONAL MATCH ()-[r]->() "
                "RETURN nodes, count(r) AS relationships"
            )
            row = counts[0] if counts else {"nodes": 0, "relationships": 0}
            return {
                "status": "connected",
                "uri": self._uri,
                "nodes": row.get("nodes", 0),
                "relationships": row.get("relationships", 0),
            }
        except Exception as e:
            return {"status": "error", "uri": self._uri, "error": str(e)}


def get_neo4j() -> Neo4jConnection:
    """
    Get or create the singleton Neo4jConnection.

    Thread-safe for use in FastAPI and Celery workers.
    """
    global _instance
    if _instance is None:
        _instance = Neo4jConnection()
    return _instance


async def reset_neo4j() -> None:
    """Close and clear the singleton. Used in tests and shutdown."""
    global _instance
    if _instance is not None:
        await _instance.close()
        _instance = None
