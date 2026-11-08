"""Local durable execution store.

This is deliberately small: it prevents a completed action from being executed
twice if the result POST fails, and it lets the agent report results after a
crash without keeping anything sensitive in memory.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ExecutionStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), timeout=30)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS executions (
                job_id INTEGER PRIMARY KEY,
                lease_id TEXT NOT NULL,
                execution_type TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'started',
                result_json TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get(self, job_id: int) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT job_id, lease_id, execution_type, status, result_json, updated_at "
            "FROM executions WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "job_id": row[0],
            "lease_id": row[1],
            "execution_type": row[2],
            "status": row[3],
            "result": json.loads(row[4]) if row[4] else None,
            "updated_at": row[5],
        }

    def start(self, job_id: int, lease_id: str, execution_type: str) -> None:
        existing = self.get(job_id)
        if existing is None:
            self._db.execute(
                "INSERT INTO executions "
                "(job_id, lease_id, execution_type, status, updated_at) "
                "VALUES (?, ?, ?, 'started', ?)",
                (job_id, lease_id, execution_type, self._now()),
            )
        else:
            self._db.execute(
                "UPDATE executions SET lease_id = ?, execution_type = ?, "
                "status = 'started', updated_at = ? WHERE job_id = ?",
                (lease_id, execution_type, self._now(), job_id),
            )
        self._db.commit()

    def save_result(self, job_id: int, result: dict[str, Any]) -> None:
        self._db.execute(
            "UPDATE executions SET result_json = ?, status = 'result_ready', "
            "updated_at = ? WHERE job_id = ?",
            (json.dumps(result), self._now(), job_id),
        )
        self._db.commit()

    def mark_reported(self, job_id: int) -> None:
        self._db.execute(
            "UPDATE executions SET status = 'reported', updated_at = ? "
            "WHERE job_id = ?",
            (self._now(), job_id),
        )
        self._db.commit()

    def pending_results(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT job_id, result_json FROM executions "
            "WHERE status = 'result_ready' ORDER BY updated_at LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {"job_id": row[0], "result": json.loads(row[1])}
            for row in rows
        ]
