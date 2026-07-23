"""Persistent traces for mismatched Primary vs Candidate payloads.

Writes are performed on a worker thread via ``asyncio.to_thread`` so the SQLite
call never blocks the event loop. A fresh connection per write keeps this
safe across threads without a shared-connection lock.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS mismatches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    primary_model TEXT,
    candidate_model TEXT,
    request TEXT,
    primary_output TEXT,
    candidate_output TEXT,
    primary_action TEXT,
    candidate_action TEXT
);
"""


class TraceStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _insert(self, row: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO mismatches (
                    created_at, primary_model, candidate_model, request,
                    primary_output, candidate_output, primary_action, candidate_action
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    row.get("primary_model"),
                    row.get("candidate_model"),
                    row.get("request"),
                    row.get("primary_output"),
                    row.get("candidate_output"),
                    row.get("primary_action"),
                    row.get("candidate_action"),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    async def record_mismatch(
        self,
        *,
        primary_model: str,
        candidate_model: str,
        request: Any,
        primary_output: str | None,
        candidate_output: str | None,
        primary_action: Any,
        candidate_action: Any,
    ) -> None:
        row = {
            "primary_model": primary_model,
            "candidate_model": candidate_model,
            "request": json.dumps(request),
            "primary_output": primary_output,
            "candidate_output": candidate_output,
            "primary_action": json.dumps(primary_action),
            "candidate_action": json.dumps(candidate_action),
        }
        await asyncio.to_thread(self._insert, row)

    def count(self) -> int:
        conn = self._connect()
        try:
            cur = conn.execute("SELECT COUNT(*) FROM mismatches")
            return int(cur.fetchone()[0])
        finally:
            conn.close()
