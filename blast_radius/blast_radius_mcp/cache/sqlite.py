"""SQLite-based caching for tool results."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from blast_radius_mcp.logging_config import get_logger

logger = get_logger("cache")

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    repo_root TEXT NOT NULL,
    repo_fingerprint TEXT NOT NULL,
    intent TEXT NOT NULL,
    anchors TEXT NOT NULL,
    diff_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_results (
    cache_key TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    query_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    repo_fingerprint_hash TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    timing_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    repo_fingerprint_hash TEXT NOT NULL,
    path_or_blob TEXT
);

CREATE INDEX IF NOT EXISTS idx_tool_results_tool_name
    ON tool_results(tool_name);

CREATE INDEX IF NOT EXISTS idx_tool_results_run_id
    ON tool_results(run_id);

CREATE INDEX IF NOT EXISTS idx_tool_results_created_at
    ON tool_results(created_at);

CREATE INDEX IF NOT EXISTS idx_artifacts_kind
    ON artifacts(kind);
"""


class CacheDB:
    """SQLite cache for blast radius tool results.

    Thread-safe via a threading lock. Uses WAL mode and
    synchronous=NORMAL for performance.
    """

    def __init__(self, db_path: str) -> None:
        """Initialize the cache database.

        Args:
            db_path: Path to the SQLite database file.
                     Parent directories are created automatically.
        """
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a new connection with standard pragmas."""
        path = Path(self._db_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.executescript(_CREATE_TABLES_SQL)
                conn.commit()
            finally:
                conn.close()

    def get_cached_result(self, cache_key: str) -> dict[str, Any] | None:
        """Look up a cached tool result.

        Args:
            cache_key: The deterministic cache key.

        Returns:
            Parsed JSON response dict, or None on cache miss.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT response_json FROM tool_results WHERE cache_key = ?",
                    (cache_key,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                return json.loads(row["response_json"])
            finally:
                conn.close()

    def store_result(
        self,
        cache_key: str,
        tool_name: str,
        query_id: str,
        run_id: str,
        repo_fp_hash: str,
        request_json: str,
        response_json: str,
        timing_ms: int,
    ) -> None:
        """Store a tool result in the cache.

        Uses INSERT OR REPLACE to handle duplicate keys gracefully.

        Args:
            cache_key: Deterministic cache key.
            tool_name: Name of the tool.
            query_id: Deterministic query ID.
            run_id: Deterministic run ID.
            repo_fp_hash: Repository fingerprint hash.
            request_json: Serialized request JSON.
            response_json: Serialized response JSON.
            timing_ms: Execution time in milliseconds.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO tool_results
                       (cache_key, tool_name, query_id, run_id,
                        repo_fingerprint_hash, request_json, response_json,
                        timing_ms, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        cache_key,
                        tool_name,
                        query_id,
                        run_id,
                        repo_fp_hash,
                        request_json,
                        response_json,
                        timing_ms,
                        now,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def store_run(
        self,
        run_id: str,
        repo_root: str,
        repo_fp: dict,
        intent: str,
        anchors: list,
        diff_hash: str,
    ) -> None:
        """Store a run record.

        Args:
            run_id: Deterministic run ID.
            repo_root: Repository root path.
            repo_fp: Repository fingerprint as dict.
            intent: Normalized intent string.
            anchors: List of anchor strings.
            diff_hash: Hash of the diff.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO runs
                       (run_id, created_at, repo_root, repo_fingerprint,
                        intent, anchors, diff_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        now,
                        repo_root,
                        json.dumps(repo_fp, sort_keys=True),
                        intent,
                        json.dumps(anchors, sort_keys=False),
                        diff_hash,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def store_artifact(
        self,
        artifact_id: str,
        kind: str,
        repo_fp_hash: str,
        path_or_blob: str | None = None,
    ) -> None:
        """Store an artifact reference.

        Args:
            artifact_id: Unique artifact identifier.
            kind: Artifact kind (e.g., "ast_index", "semantic_index").
            repo_fp_hash: Repository fingerprint hash.
            path_or_blob: Optional path or serialized data.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO artifacts
                       (artifact_id, kind, repo_fingerprint_hash, path_or_blob)
                       VALUES (?, ?, ?, ?)""",
                    (artifact_id, kind, repo_fp_hash, path_or_blob),
                )
                conn.commit()
            finally:
                conn.close()

    def cleanup(self, max_age_days: int = 30, max_size_mb: int = 500) -> int:
        """Remove old cache entries.

        Args:
            max_age_days: Remove entries older than this many days.
            max_size_mb: Target maximum database size (advisory).

        Returns:
            Number of entries removed.
        """
        from datetime import timedelta

        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max_age_days)
        ).isoformat()

        removed = 0
        with self._lock:
            conn = self._get_connection()
            try:
                # Remove old tool results
                cursor = conn.execute(
                    "DELETE FROM tool_results WHERE created_at < ?",
                    (cutoff,),
                )
                removed += cursor.rowcount

                # Remove old runs
                cursor = conn.execute(
                    "DELETE FROM runs WHERE created_at < ?",
                    (cutoff,),
                )
                removed += cursor.rowcount

                conn.commit()

                # Reclaim space
                conn.execute("PRAGMA incremental_vacuum")

                logger.info(
                    f"Cache cleanup: removed {removed} entries older than {max_age_days} days"
                )
            finally:
                conn.close()

        return removed

    def get_stats(self) -> dict[str, int]:
        """Get cache statistics.

        Returns:
            Dict with counts of runs, tool_results, and artifacts.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                stats = {}
                for table in ("runs", "tool_results", "artifacts"):
                    cursor = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}")
                    stats[table] = cursor.fetchone()["cnt"]
                return stats
            finally:
                conn.close()
