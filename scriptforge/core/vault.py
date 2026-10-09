"""SQLite persistence: run history + per-script interface cache."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path.home() / ".scriptforge" / "history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    script      TEXT    NOT NULL,
    script_name TEXT    NOT NULL,
    kind        TEXT    NOT NULL,
    argv        TEXT    NOT NULL,
    answers     TEXT    NOT NULL DEFAULT '{}',
    exit_code   INTEGER NOT NULL,
    duration_s  REAL    NOT NULL,
    output      TEXT    NOT NULL DEFAULT '',
    created_at  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_script ON runs(script);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);

CREATE TABLE IF NOT EXISTS cache (
    script   TEXT PRIMARY KEY,
    mtime_ns INTEGER NOT NULL,
    ir       TEXT    NOT NULL,
    saved_at REAL    NOT NULL
);
"""


@dataclass
class RunRecord:
    id: int
    script: str
    script_name: str
    kind: str
    argv: str
    answers: str
    exit_code: int
    duration_s: float
    output: str
    created_at: float


class Vault:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Vault":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------- runs

    def log_run(
        self,
        script: str,
        kind: str,
        argv: list[str],
        exit_code: int,
        duration_s: float,
        output: str = "",
        answers: dict[str, str] | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (script, script_name, kind, argv, answers, exit_code, duration_s, output, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                script,
                Path(script).name,
                kind,
                " ".join(argv),
                json.dumps(answers or {}),
                exit_code,
                duration_s,
                output[-200_000:],
                time.time(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def recent_runs(self, limit: int = 50, script: str | None = None) -> list[RunRecord]:
        if script:
            cur = self.conn.execute(
                "SELECT * FROM runs WHERE script=? ORDER BY created_at DESC LIMIT ?", (script, limit)
            )
        else:
            cur = self.conn.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [RunRecord(**row) for row in cur.fetchall()]

    def last_run_for(self, script: str) -> RunRecord | None:
        cur = self.conn.execute(
            "SELECT * FROM runs WHERE script=? ORDER BY created_at DESC LIMIT 1", (script,)
        )
        row = cur.fetchone()
        return RunRecord(**row) if row else None

    def delete_run(self, run_id: int) -> None:
        self.conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
        self.conn.commit()

    # ------------------------------------------------------------- cache

    def cache_get(self, script: str, mtime_ns: int) -> dict | None:
        cur = self.conn.execute("SELECT ir FROM cache WHERE script=? AND mtime_ns=?", (script, mtime_ns))
        row = cur.fetchone()
        return json.loads(row["ir"]) if row else None

    def cache_put(self, script: str, mtime_ns: int, ir: dict) -> None:
        self.conn.execute(
            "INSERT INTO cache (script, mtime_ns, ir, saved_at) VALUES (?,?,?,?)"
            " ON CONFLICT(script) DO UPDATE SET mtime_ns=excluded.mtime_ns, ir=excluded.ir, saved_at=excluded.saved_at",
            (script, mtime_ns, json.dumps(ir), time.time()),
        )
        self.conn.commit()